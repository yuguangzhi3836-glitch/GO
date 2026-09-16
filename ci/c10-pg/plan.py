"""C10 candidate-bound PostgreSQL EXPLAIN evidence runner."""
import argparse, hashlib, json, os, pathlib, time, uuid
import psycopg

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--evidence-dir",required=True);a=ap.parse_args()
    out=pathlib.Path(a.evidence_dir);out.mkdir(parents=True,exist_ok=True)
    url=os.environ["GO_C10_RUNTIME_DATABASE_URL"].replace("postgresql+psycopg://","postgresql://")
    schema="c10plan_"+uuid.uuid4().hex[:12]
    query="""SELECT j.journey_id,j.account_id,j.title,j.destination_summary,j.starts_at,j.created_at
FROM go_journey j
WHERE (j.account_id=%s OR EXISTS (
 SELECT 1 FROM consumer_trip_member m
 WHERE m.journey_id=j.journey_id AND m.user_id=%s AND m.status='ACTIVE'))
AND (lower(j.title) LIKE %s OR lower(coalesce(j.destination_summary,'')) LIKE %s)
ORDER BY j.starts_at ASC NULLS LAST,j.created_at ASC,j.journey_id ASC
OFFSET %s LIMIT %s"""
    params=("owner-target","member-target","%target%","%target%",120,21)
    started=time.time()
    with psycopg.connect(url) as cx:
      with cx.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{schema}"');cur.execute(f'SET search_path TO "{schema}"')
        cur.execute("CREATE TABLE go_journey(journey_id text PRIMARY KEY,account_id text NOT NULL,title text NOT NULL,destination_summary text,starts_at timestamptz,created_at timestamptz NOT NULL)")
        cur.execute("CREATE TABLE consumer_trip_member(trip_member_id text PRIMARY KEY,journey_id text NOT NULL,user_id text NOT NULL,status text NOT NULL)")
        cur.execute("CREATE INDEX ix_journey_account_order ON go_journey(account_id,starts_at,created_at,journey_id)")
        cur.execute("CREATE INDEX ix_member_user_status_journey ON consumer_trip_member(user_id,status,journey_id)")
        cur.execute("""INSERT INTO go_journey
 SELECT 'j'||g, CASE WHEN g%40=0 THEN 'owner-target' ELSE 'owner-'||(g%200)::text END,
 CASE WHEN g%25=0 THEN 'Target Journey '||g ELSE 'Journey '||g END,
 CASE WHEN g%33=0 THEN 'target destination' ELSE 'destination '||(g%100)::text END,
 now()+(g||' minutes')::interval,now()-(g||' seconds')::interval
 FROM generate_series(1,20000) g""")
        cur.execute("""INSERT INTO consumer_trip_member
 SELECT 'm'||g,'j'||(g*20),'member-target','ACTIVE' FROM generate_series(1,500) g""")
        cur.execute("ANALYZE go_journey");cur.execute("ANALYZE consumer_trip_member")
        cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "+query,params);plan=cur.fetchone()[0][0]
        cur.execute(query,params);rows=cur.fetchall()
        cur.execute("SELECT count(*) FROM go_journey");journeys=cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM consumer_trip_member");members=cur.fetchone()[0]
        cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
    raw={"task_id":"V70-R3-C10-PG-01","source_commit":os.environ["GO_C10_SOURCE_COMMIT"],"application_tree":os.environ["GO_C10_APPLICATION_TREE"],"postgresql":"18.4","scale":{"journeys":journeys,"members":members},"query":query,"parameters":params,"returned_rows":len(rows),"plan":plan,"elapsed_seconds":time.time()-started,"boundary":"evidence only; no product change"}
    p=out/"explain_analyze_buffers.json";p.write_text(json.dumps(raw,indent=2,default=str)+"\n")
    sums={p.name:hashlib.sha256(p.read_bytes()).hexdigest()};(out/"SHA256SUMS.json").write_text(json.dumps(sums,indent=2)+"\n")
    print(json.dumps({"status":"EVIDENCE_READY","rows":len(rows),"sha256":sums[p.name]}))
if __name__=="__main__":main()
