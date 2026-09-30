"""Isolated PostgreSQL contention worker used only by CI acceptance."""
from __future__ import annotations
import argparse,json,os
import psycopg
from postgres_runtime import claim_batch

DOMAINS=[f"C{i}" for i in range(1,13)]

def main():
 p=argparse.ArgumentParser()
 p.add_argument("--dsn",required=True)
 p.add_argument("--c",default="ALL")
 p.add_argument("--worker",required=True)
 p.add_argument("--limit",type=int,default=10000)
 p.add_argument("--batch",type=int,default=25)
 p.add_argument("--crash-after-claim",action="store_true")
 a=p.parse_args()
 domains=DOMAINS if a.c=="ALL" else [a.c]
 conn=psycopg.connect(a.dsn)
 done=0
 while done<a.limit:
  rows=claim_batch(conn,domains,a.worker,limit=min(a.batch,a.limit-done),lease_s=30)
  if not rows:
   break
  if a.crash_after_claim:
   os._exit(23)
  with conn.transaction():
   with conn.cursor() as cur:
    for row in rows:
     task_id,owner_c=row[0],row[1]
     cur.execute("""INSERT INTO c_runtime_effect(effect_key,task_id,effect_type,body)
                    VALUES (%s,%s,'TEST',%s::jsonb)
                    ON CONFLICT(effect_key) DO NOTHING RETURNING effect_key""",
                 (f"effect:{task_id}",task_id,json.dumps({"worker":a.worker,"owner_c":owner_c})))
     if cur.fetchone() is None:
      raise RuntimeError(f"duplicate effect for {task_id}")
     cur.execute("""UPDATE c_runtime_task
                    SET status='SUCCEEDED',lease_owner=NULL,lease_until=NULL,updated_at=now()
                    WHERE task_id=%s AND owner_c=%s AND status='RUNNING' AND lease_owner=%s
                    RETURNING task_id""",(task_id,owner_c,a.worker))
     if cur.fetchone() is None:
      raise RuntimeError(f"completion fencing rejected current owner for {task_id}")
  done += len(rows)
 print(json.dumps({"worker":a.worker,"done":done}),flush=True)

if __name__=="__main__":
 main()
