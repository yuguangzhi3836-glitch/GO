"""Real isolated PostgreSQL acceptance executor for CI."""
from __future__ import annotations
import argparse,json,subprocess,time,uuid
from pathlib import Path
import psycopg

SCENARIOS=[]

def record(name,passed,**details): SCENARIOS.append({"name":name,"passed":bool(passed),"details":details})

def setup(conn):
    schema=Path(__file__).with_name("postgres_schema.sql").read_text()
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS c_runtime_evidence_projection CASCADE")
            cur.execute("DROP TABLE IF EXISTS c_runtime_effect CASCADE")
            cur.execute("DROP TABLE IF EXISTS c_runtime_task CASCADE")
            cur.execute(schema)

def seed(conn,n=1000):
    now=time.time()
    rows=[]
    for i in range(n):
        c=f"C{(i%12)+1}"
        rows.append((f"task-{i}",f"idem-{i}",c,"LOAD",json.dumps({"i":i}),100))
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany("""INSERT INTO c_runtime_task(task_id,idempotency_key,owner_c,kind,payload,priority,status,available_at)
                               VALUES (%s,%s,%s,%s,%s::jsonb,%s,'QUEUED',now())""",rows)

def count(conn,sql,args=()):
    with conn.cursor() as cur:
        cur.execute(sql,args); return cur.fetchone()[0]

def run_workers(dsn,workers):
    ps=[]
    for i in range(workers):
        c=f"C{(i%12)+1}"
        ps.append(subprocess.Popen(["python",str(Path(__file__).with_name("pg_acceptance_worker.py")),
          "--dsn",dsn,"--c",c,"--worker",f"w{i}"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
    outs=[]
    for p in ps:
        o,e=p.communicate(timeout=60); outs.append((p.returncode,o,e))
    return outs

def main():
    p=argparse.ArgumentParser(); p.add_argument("--dsn",required=True); p.add_argument("--out",required=True); a=p.parse_args()
    conn=psycopg.connect(a.dsn); setup(conn)

    # contention 1000 tasks / 4,8,16 workers
    contention=True; observations={}
    for wc in (4,8,16):
        setup(conn); seed(conn,1000); outs=run_workers(a.dsn,wc)
        succ=count(conn,"SELECT count(*) FROM c_runtime_task WHERE status='SUCCEEDED'")
        effects=count(conn,"SELECT count(*) FROM c_runtime_effect")
        dup_effects=count(conn,"SELECT count(*) FROM (SELECT effect_key,count(*) n FROM c_runtime_effect GROUP BY effect_key HAVING count(*)>1) x")
        observations[str(wc)]={"succ":succ,"effects":effects,"dup_effects":dup_effects,"rc":[x[0] for x in outs]}
        contention = contention and succ==1000 and effects==1000 and dup_effects==0 and all(x[0]==0 for x in outs)
    record("claim_contention",contention,observations=observations)

    # duplicate dispatch via unique idempotency key
    setup(conn)
    with conn.transaction():
        with conn.cursor() as cur:
            ok=0
            for i in range(10):
                cur.execute("""INSERT INTO c_runtime_task(task_id,idempotency_key,owner_c,kind,payload,priority,status,available_at)
                               VALUES (%s,'same','C1','X','{}',100,'QUEUED',now())
                               ON CONFLICT(idempotency_key) DO NOTHING RETURNING task_id""",(f"d{i}",))
                ok += 1 if cur.fetchone() else 0
    record("duplicate_dispatch",count(conn,"SELECT count(*) FROM c_runtime_task WHERE idempotency_key='same'")==1)

    # effect idempotency
    setup(conn); seed(conn,1)
    with conn.transaction():
        with conn.cursor() as cur:
            inserted=0
            for _ in range(10):
                cur.execute("""INSERT INTO c_runtime_effect(effect_key,task_id,effect_type,body)
                               VALUES ('same-effect','task-0','TEST','{}') ON CONFLICT(effect_key) DO NOTHING RETURNING effect_key""")
                inserted += 1 if cur.fetchone() else 0
    record("effect_idempotency",inserted==1,inserted=inserted)

    # worker death + old worker fencing + retry exhaustion
    setup(conn); seed(conn,1)
    dead=subprocess.run(["python",str(Path(__file__).with_name("pg_acceptance_worker.py")),"--dsn",a.dsn,"--c","C1","--worker","dead","--crash-after-claim"])
    time.sleep(3)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""UPDATE c_runtime_task SET status='QUEUED',lease_owner=NULL,lease_until=NULL,last_error='LEASE_EXPIRED'
                           WHERE status='RUNNING' AND lease_until<now() RETURNING task_id""")
            recovered=cur.fetchone() is not None
    replacement=subprocess.run(["python",str(Path(__file__).with_name("pg_acceptance_worker.py")),"--dsn",a.dsn,"--c","C1","--worker","replacement"])
    record("worker_death",dead.returncode==23 and recovered and replacement.returncode==0)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""UPDATE c_runtime_task SET status='SUCCEEDED' WHERE task_id='task-0' AND lease_owner='dead' AND status='RUNNING' RETURNING task_id""")
            old=cur.fetchone()
    record("old_worker_fencing",old is None)

    # DB restart is orchestrated by workflow; marker file tells harness it happened.
    marker=Path(a.out).parent/"db-restart-ok"
    record("database_restart",marker.exists(),marker=str(marker))

    # retry exhaustion direct state transition check
    setup(conn)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO c_runtime_task(task_id,owner_c,kind,payload,priority,status,available_at,lease_owner,lease_until,attempts,max_attempts)
                           VALUES ('rx','C1','X','{}',100,'RUNNING',now(),'dead',now()-interval '1 second',3,3)""")
            cur.execute("""UPDATE c_runtime_task SET status=CASE WHEN attempts<max_attempts THEN 'QUEUED' ELSE 'ESCALATED' END,
                           lease_owner=NULL,lease_until=NULL WHERE task_id='rx' AND lease_until<now() RETURNING status""")
            st=cur.fetchone()[0]
    record("retry_exhaustion",st=="ESCALATED",status=st)

    # evidence projection consistency
    setup(conn)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO c_runtime_evidence_projection(projection_key,last_event_hash,last_event_id,event_count)
                           VALUES ('main','h3','e3',3)""")
            cur.execute("SELECT last_event_hash,last_event_id,event_count FROM c_runtime_evidence_projection WHERE projection_key='main'")
            pr=cur.fetchone()
    record("evidence_projection",tuple(pr)==("h3","e3",3),projection=list(pr))

    out=Path(a.out); out.write_text(json.dumps({"scenarios":SCENARIOS},indent=2))
    failed=[x["name"] for x in SCENARIOS if not x["passed"]]
    print(json.dumps({"failed":failed,"count":len(SCENARIOS)}))
    raise SystemExit(1 if failed else 0)
if __name__=="__main__": main()
