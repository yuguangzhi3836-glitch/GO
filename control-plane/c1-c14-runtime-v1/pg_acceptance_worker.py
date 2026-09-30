"""Isolated PostgreSQL contention worker used only by CI acceptance."""
from __future__ import annotations
import argparse,json,os,sys,time
try:
    import psycopg
except Exception as exc:
    raise SystemExit(f"psycopg required: {exc}")
from postgres_runtime import PostgresRuntimeRepository

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dsn",required=True); p.add_argument("--c",required=True); p.add_argument("--worker",required=True)
    p.add_argument("--limit",type=int,default=10000); p.add_argument("--crash-after-claim",action="store_true")
    a=p.parse_args()
    conn=psycopg.connect(a.dsn)
    repo=PostgresRuntimeRepository(conn)
    done=0
    while done<a.limit:
        row=repo.claim_one(a.c,a.worker,lease_s=2)
        if row is None: break
        task_id=row[0]
        if a.crash_after_claim:
            os._exit(23)
        ok=repo.record_effect_once(effect_key=f"effect:{task_id}",task_id=task_id,effect_type="TEST",body={"worker":a.worker})
        repo.complete(task_id=task_id,owner_c=a.c,worker_id=a.worker,success=True)
        print(json.dumps({"task_id":task_id,"worker":a.worker,"effect_inserted":ok}),flush=True)
        done+=1
    print(json.dumps({"worker":a.worker,"done":done}),flush=True)
if __name__=="__main__": main()
