"""Isolated PostgreSQL contention worker used only by CI acceptance."""
from __future__ import annotations
import argparse,json,os
import psycopg

DOMAINS=tuple(f"C{i}" for i in range(1,13))

CLAIM_ANY_SQL = """
WITH next_task AS (
 SELECT task_id,owner_c FROM c_runtime_task
 WHERE owner_c = ANY(%s) AND status='QUEUED' AND available_at<=now()
 ORDER BY priority,created_at
 FOR UPDATE SKIP LOCKED LIMIT 1
)
UPDATE c_runtime_task t
SET status='RUNNING',lease_owner=%s,lease_until=now()+interval '2 seconds',
    attempts=attempts+1,updated_at=now()
FROM next_task n WHERE t.task_id=n.task_id
RETURNING t.task_id,t.owner_c;
"""

def main():
 p=argparse.ArgumentParser()
 p.add_argument("--dsn",required=True); p.add_argument("--c",default="ALL"); p.add_argument("--worker",required=True)
 p.add_argument("--limit",type=int,default=10000); p.add_argument("--crash-after-claim",action="store_true")
 a=p.parse_args()
 domains=list(DOMAINS if a.c=="ALL" else (a.c,))
 conn=psycopg.connect(a.dsn)
 done=0
 while done<a.limit:
  with conn.transaction():
   with conn.cursor() as cur:
    cur.execute(CLAIM_ANY_SQL,(domains,a.worker))
    row=cur.fetchone()
    if row is None: break
    task_id,owner_c=row
    if a.crash_after_claim:
     conn.commit()
     os._exit(23)
    cur.execute("""INSERT INTO c_runtime_effect(effect_key,task_id,effect_type,body)
                   VALUES (%s,%s,'TEST',%s::jsonb)
                   ON CONFLICT(effect_key) DO NOTHING RETURNING effect_key""",
                (f"effect:{task_id}",task_id,json.dumps({"worker":a.worker,"owner_c":owner_c})))
    effect_inserted=cur.fetchone() is not None
    if not effect_inserted:
     raise RuntimeError(f"duplicate effect for {task_id}")
    cur.execute("""UPDATE c_runtime_task
                   SET status='SUCCEEDED',lease_owner=NULL,lease_until=NULL,updated_at=now()
                   WHERE task_id=%s AND owner_c=%s AND status='RUNNING' AND lease_owner=%s
                   RETURNING task_id""",(task_id,owner_c,a.worker))
    if cur.fetchone() is None:
     raise RuntimeError(f"completion fencing rejected current owner for {task_id}")
  done+=1
 print(json.dumps({"worker":a.worker,"done":done}),flush=True)

if __name__=="__main__": main()
