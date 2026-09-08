#!/usr/bin/env python3
"""Executable DEPTH10 PostgreSQL lease/ACK crash-recovery gate.

Requires the application DB URL to point to PostgreSQL. This script intentionally
fails on non-PostgreSQL backends because SQLite cannot prove multi-process claim
safety. It records machine-readable evidence to stdout and exits non-zero on HOLD.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from go_hotel.db.session import SessionLocal
from go_hotel.services.chain_task_lease import chain_task_lease_service


def now():
    return datetime.now(timezone.utc).isoformat()


def db_info():
    with SessionLocal() as s:
        dialect = s.get_bind().dialect.name
        if dialect != "postgresql":
            raise RuntimeError("POSTGRES_REQUIRED")
        version = s.execute(text("select version()" )).scalar()
    return {"dialect": dialect, "version": version}


def claimant(worker_id: str, lease_seconds: int, q):
    try:
        task = chain_task_lease_service.claim(worker_id=worker_id, lease_seconds=lease_seconds)
        q.put({"worker": worker_id, "task_id": task.task_id if task else None, "attempt": task.attempt if task else None})
    except Exception as exc:
        q.put({"worker": worker_id, "error": str(exc)})


def main():
    evidence = {"gate": "POSTGRES_CRASH_RECOVERY_GATE", "started_at": now(), "checks": []}
    try:
        evidence["database"] = db_info()
        task_id = "depth10-crash-" + uuid.uuid4().hex
        chain_task_lease_service.enqueue(task_id=task_id, payload={"task": "CHAIN_HOTEL", "probe": True})

        a = chain_task_lease_service.claim(worker_id="worker-A", lease_seconds=15)
        assert a and a.task_id == task_id and a.attempt == 1
        evidence["checks"].append({"name": "worker_A_claim", "pass": True, "attempt": a.attempt})

        before = chain_task_lease_service.claim(worker_id="worker-B", lease_seconds=15)
        assert before is None
        evidence["checks"].append({"name": "no_early_reclaim", "pass": True})

        time.sleep(16)
        b = chain_task_lease_service.claim(worker_id="worker-B", lease_seconds=30)
        assert b and b.task_id == task_id and b.attempt == 2
        evidence["checks"].append({"name": "expired_lease_reclaim", "pass": True, "attempt": b.attempt})

        acked = chain_task_lease_service.ack(task_id=task_id, worker_id="worker-B", result={"probe": "ok"})
        assert acked.state == "ACKED"
        after = chain_task_lease_service.claim(worker_id="worker-C", lease_seconds=15)
        assert after is None
        evidence["checks"].append({"name": "acked_is_terminal", "pass": True})

        race_id = "depth10-race-" + uuid.uuid4().hex
        chain_task_lease_service.enqueue(task_id=race_id, payload={"task": "CHAIN_HOTEL", "race": True})
        q = mp.Queue()
        procs = [mp.Process(target=claimant, args=(f"race-{i}", 30, q)) for i in range(6)]
        for p in procs: p.start()
        for p in procs: p.join(20)
        results = [q.get(timeout=2) for _ in procs]
        winners = [x for x in results if x.get("task_id") == race_id]
        assert len(winners) == 1, results
        evidence["checks"].append({"name": "six_worker_single_owner", "pass": True, "results": results})

        retry_id = "depth10-retry-" + uuid.uuid4().hex
        chain_task_lease_service.enqueue(task_id=retry_id, payload={"task": "CHAIN_HOTEL"})
        r1 = chain_task_lease_service.claim(worker_id="retry-A", lease_seconds=30)
        chain_task_lease_service.fail(task_id=retry_id, worker_id="retry-A", error="transient", retryable=True)
        # Backoff is bounded but non-zero; evidence run waits long enough for first retry.
        time.sleep(6)
        r2 = chain_task_lease_service.claim(worker_id="retry-B", lease_seconds=30)
        assert r2 and r2.task_id == retry_id and r2.attempt == 2
        chain_task_lease_service.ack(task_id=retry_id, worker_id="retry-B")
        evidence["checks"].append({"name": "retry_wait_to_ack", "pass": True})

        dead_id = "depth10-dead-" + uuid.uuid4().hex
        chain_task_lease_service.enqueue(task_id=dead_id, payload={"task": "CHAIN_HOTEL"})
        d = chain_task_lease_service.claim(worker_id="dead-A", lease_seconds=30)
        dead = chain_task_lease_service.fail(task_id=dead_id, worker_id="dead-A", error="identity", retryable=False)
        assert dead.state == "DEAD"
        assert chain_task_lease_service.claim(worker_id="dead-B", lease_seconds=15) is None
        evidence["checks"].append({"name": "dead_is_terminal", "pass": True})

        evidence["status"] = "PASS"
        evidence["finished_at"] = now()
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        evidence["status"] = "HOLD"
        evidence["error"] = repr(exc)
        evidence["finished_at"] = now()
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
