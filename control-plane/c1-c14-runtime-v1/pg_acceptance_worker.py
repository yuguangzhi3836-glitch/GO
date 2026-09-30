"""Isolated PostgreSQL contention worker used only by CI acceptance."""
from __future__ import annotations
import argparse,json,os
try:
    import psycopg
except Exception as exc:
    raise SystemExit(f"psycopg required: {exc}")
from postgres_runtime import PostgresRuntimeRepository

DOMAINS=tuple(f"C{i}" for i in range(1,13))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dsn",required=True)
    p.add_argument("--c",default="ALL")
    p.add_argument("--worker",required=True)
    p.add_argument("--limit",type=int,default=10000)
    p.add_argument("--crash-after-claim",action="store_true")
    a=p.parse_args()
    conn=psycopg.connect(a.dsn)
    repo=PostgresRuntimeRepository(conn)
    domains=DOMAINS if a.c=="ALL" else (a.c,)
    done=0
    while done<a.limit:
        claimed=None
        for c_id in domains:
            row=repo.claim_one(c_id,a.worker,lease_s=2)
            if row is not None:
                claimed=(c_id,row)
                break
        if claimed is None:
            break
        c_id,row=claimed
        task_id=row[0]
        if a.crash_after_claim:
            os._exit(23)
        ok=repo.record_effect_once(
            effect_key=f"effect:{task_id}",task_id=task_id,effect_type="TEST",
            body={"worker":a.worker,"owner_c":c_id}
        )
        completed=repo.complete(
            task_id=task_id,owner_c=c_id,worker_id=a.worker,success=True
        )
        if not completed:
            raise RuntimeError(f"completion fencing rejected current owner for {task_id}")
        done+=1
    print(json.dumps({"worker":a.worker,"done":done}),flush=True)
if __name__=="__main__":
    main()
