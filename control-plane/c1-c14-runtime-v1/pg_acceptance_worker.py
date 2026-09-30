"""Bounded worker for the disposable PostgreSQL acceptance database only."""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path

import psycopg
from postgres_runtime import PostgresRuntimeRepository, claim_batch

DOMAINS = [f"C{i}" for i in range(1, 13)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dsn", required=True)
    p.add_argument("--c", default="ALL")
    p.add_argument("--worker", required=True)
    p.add_argument("--limit", type=int, default=10000)
    p.add_argument("--batch", type=int, default=25)
    p.add_argument("--lease-seconds", type=int, default=30)
    p.add_argument("--hold-after-claim", type=Path)
    a = p.parse_args()
    domains = DOMAINS if a.c == "ALL" else [a.c]
    claims = []
    with psycopg.connect(a.dsn, autocommit=True, connect_timeout=5,
                         application_name=f"runtime-worker:{a.worker}",
                         options="-c statement_timeout=15000 -c lock_timeout=5000") as conn:
        repo = PostgresRuntimeRepository(conn)
        while len(claims) < a.limit:
            rows = claim_batch(conn, domains, a.worker,
                               limit=min(a.batch, a.limit - len(claims)),
                               lease_s=a.lease_seconds)
            if not rows:
                break
            if a.hold_after_claim:
                # Parent sends a real SIGKILL only after the claim is committed.
                a.hold_after_claim.write_text(json.dumps(rows, default=str))
                time.sleep(60)
                raise RuntimeError("parent failed to kill paused worker")
            with conn.transaction():
                for row in rows:
                    task_id, owner_c, _, _, attempt, _ = row
                    if not repo.complete(task_id=task_id, owner_c=owner_c,
                                         worker_id=a.worker, expected_attempt=attempt,
                                         success=True):
                        raise RuntimeError(f"completion fencing rejected {task_id}")
                    if not repo.record_effect_once(effect_key=f"effect:{task_id}",
                                                   task_id=task_id, effect_type="TEST",
                                                   body={"worker": a.worker, "attempt": attempt}):
                        raise RuntimeError(f"duplicate effect for {task_id}")
            claims.extend([[r[0], r[4]] for r in rows])
    print(json.dumps({"worker": a.worker, "done": len(claims), "claims": claims}), flush=True)


if __name__ == "__main__":
    main()
