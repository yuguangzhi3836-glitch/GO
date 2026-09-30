"""Real, bounded acceptance against a disposable local PostgreSQL database.

Every scenario is checkpointed, including exceptions. Monitoring uses a separate
 autocommit session while workers are alive. No marker can prove a DB restart.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import traceback

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.pq import TransactionStatus
from acceptance_harness import REQUIRED
from evidence_projection_pg import project_chain
from postgres_runtime import PostgresRuntimeRepository
from runtime import Runtime

HERE = Path(__file__).resolve().parent


def connect(dsn, name="runtime-acceptance"):
    return psycopg.connect(dsn, autocommit=True, connect_timeout=5,
                           application_name=name,
                           options="-c statement_timeout=15000 -c lock_timeout=5000")


def query(conn, sql, args=()):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def scalar(conn, sql, args=()):
    return query(conn, sql, args)[0][0]


def setup(conn):
    # Autocommit is deliberate: an earlier SELECT must not leave DDL/seed inside
    # an implicit outer transaction that blocks every subsequent worker.
    assert conn.info.transaction_status == TransactionStatus.IDLE
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS c_runtime_evidence_projection, c_runtime_effect, c_runtime_task CASCADE")
            cur.execute((HERE / "postgres_schema.sql").read_text())
    assert conn.info.transaction_status == TransactionStatus.IDLE


def seed(conn, n=1000):
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany("""INSERT INTO c_runtime_task
                (task_id,idempotency_key,owner_c,kind,payload,priority,status,available_at)
                VALUES (%s,%s,%s,'LOAD',%s::jsonb,100,'QUEUED',now())""",
                [(f"task-{i}", f"idem-{i}", f"C{i % 12 + 1}", json.dumps({"i": i})) for i in range(n)])
    assert conn.info.transaction_status == TransactionStatus.IDLE


def sample_waits(conn):
    columns = ("pid", "application_name", "state", "wait_event_type", "wait_event",
               "blocking_pids", "transaction_age_seconds", "query")
    rows = query(conn, """SELECT pid,application_name,state,wait_event_type,wait_event,
         pg_blocking_pids(pid), EXTRACT(epoch FROM clock_timestamp()-xact_start), left(query,500)
         FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
         ORDER BY pid""")
    return {"at": time.time(), "sessions": [dict(zip(columns, r)) for r in rows]}


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise TimeoutError("bounded acceptance wait expired")


def worker_cmd(dsn, worker, *args):
    return [sys.executable, str(HERE / "pg_acceptance_worker.py"),
            "--dsn", dsn, "--worker", worker, *map(str, args)]


def run_workers(dsn, workers, out, monitor, label):
    processes, handles, samples = [], [], []
    started = time.monotonic()
    try:
        for i in range(workers):
            log = (out / f"{label}-worker-{i}.log").open("w")
            handles.append(log)
            processes.append(subprocess.Popen(worker_cmd(dsn, f"{label}-w{i}", "--batch", 100),
                                               stdout=log, stderr=subprocess.STDOUT, text=True))
        deadline = started + 90
        while any(p.poll() is None for p in processes) and time.monotonic() < deadline:
            # Capture blockers BEFORE killing workers, not after all sessions vanish.
            sample = sample_waits(monitor)
            samples.append(sample)
            with (out / "wait-evidence.jsonl").open("a") as f:
                f.write(json.dumps({"phase": label, **sample}, default=str) + "\n")
            time.sleep(0.2)
        timed_out = any(p.poll() is None for p in processes)
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
            p.wait(timeout=5)
        for f in handles:
            f.close()
    reports = []
    for i, p in enumerate(processes):
        text = (out / f"{label}-worker-{i}.log").read_text()
        try:
            report = json.loads(text.splitlines()[-1])
        except (ValueError, IndexError):
            report = {"error": text[-4000:]}
        reports.append({"rc": p.returncode, **report})
    return {"elapsed_seconds": time.monotonic()-started, "timed_out": timed_out,
            "workers": reports, "wait_samples": len(samples)}


def kill_after_claim(dsn, out, name, lease=1):
    ready = out / f"{name}-claimed.json"
    ready.unlink(missing_ok=True)
    with (out / f"{name}.log").open("w") as log:
        p = subprocess.Popen(worker_cmd(dsn, name, "--c", "C1", "--batch", 1,
                                        "--lease-seconds", lease, "--hold-after-claim", ready),
                             stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_until(lambda: ready.exists() or p.poll() is not None)
            if not ready.exists():
                raise RuntimeError("crash worker exited before committed claim")
            rows = json.loads(ready.read_text())
            p.kill()
            rc = p.wait(timeout=5)
            assert rc == -signal.SIGKILL
            return rows[0], rc
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=5)


def wait_expired(conn):
    wait_until(lambda: scalar(conn, "SELECT bool_and(lease_until<clock_timestamp()) FROM c_runtime_task WHERE status='RUNNING'") is True)


def concurrent_clients(dsn, fn, clients=16):
    barrier = threading.Barrier(clients, timeout=10)
    def call(i):
        with connect(dsn, f"runtime-race:{i}") as conn:
            barrier.wait()
            return fn(conn, i)
    with ThreadPoolExecutor(max_workers=clients) as pool:
        return list(pool.map(call, range(clients)))


class Acceptance:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.out).parent
        self.out.mkdir(parents=True, exist_ok=True)
        self.results = []
        self.conn = connect(args.dsn)
        self.monitor = connect(args.dsn, "runtime-monitor")
        self.restart_events = None
        self.flush()

    def flush(self):
        path = Path(self.args.out)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps({"candidate_sha": self.args.candidate_sha,
            "scenarios": self.results}, indent=2, default=str)+"\n")
        temp.replace(path)

    def run(self, name, fn):
        started = time.monotonic()
        try:
            details = fn()
            result = {"name": name, "passed": True, "details": details or {}}
        except Exception as exc:
            result = {"name": name, "passed": False,
                      "details": {"error_type": type(exc).__name__, "error": str(exc),
                                  "traceback": traceback.format_exc()}}
        result["details"]["elapsed_seconds"] = time.monotonic()-started
        self.results.append(result)
        self.flush()
        print(json.dumps(result, default=str), flush=True)

    def contention(self):
        observations = {}
        for wc in (4, 8, 16):
            setup(self.conn)
            seed(self.conn)
            # Regression: SELECT -> setup/seed -> independent process visibility.
            assert scalar(self.conn, "SELECT count(*) FROM c_runtime_task") == 1000
            assert self.conn.info.transaction_status == TransactionStatus.IDLE
            assert scalar(self.monitor, "SELECT count(*) FROM c_runtime_task") == 1000
            obs = run_workers(self.args.dsn, wc, self.out, self.monitor, f"contention-{wc}")
            obs["states"] = query(self.conn, "SELECT status,count(*) FROM c_runtime_task GROUP BY status")
            obs["effects"] = scalar(self.conn, "SELECT count(*) FROM c_runtime_effect")
            claims = [tuple(c) for w in obs["workers"] for c in w.get("claims", [])]
            obs["unique_claims"] = len(set(claims))
            observations[str(wc)] = obs
            (self.out / "contention-progress.json").write_text(json.dumps(observations, indent=2))
            assert not obs["timed_out"] and all(w["rc"] == 0 for w in obs["workers"]), obs
            assert obs["states"] == [("SUCCEEDED", 1000)] and obs["effects"] == 1000, obs
            assert len(claims) == len(set(claims)) == 1000, obs
        return observations

    def duplicate_dispatch(self):
        setup(self.conn)
        def insert(conn, i):
            return query(conn, """INSERT INTO c_runtime_task(task_id,idempotency_key,owner_c,kind,payload,status,available_at)
                VALUES (%s,'same','C1','X','{}','QUEUED',now())
                ON CONFLICT(idempotency_key) DO NOTHING RETURNING task_id""", (f"d{i}",))
        rows = concurrent_clients(self.args.dsn, insert)
        winners = sum(bool(x) for x in rows)
        assert winners == scalar(self.conn, "SELECT count(*) FROM c_runtime_task") == 1
        return {"concurrent_clients": len(rows), "winners": winners}

    def effect_idempotency(self):
        setup(self.conn)
        seed(self.conn, 1)
        rows = concurrent_clients(self.args.dsn, lambda conn, i:
            PostgresRuntimeRepository(conn).record_effect_once(effect_key="same-effect", task_id="task-0",
                                                               effect_type="TEST", body={"i": i}))
        assert sum(rows) == scalar(self.conn, "SELECT count(*) FROM c_runtime_effect") == 1
        return {"concurrent_clients": len(rows), "inserted": sum(rows)}

    def worker_death(self):
        setup(self.conn)
        seed(self.conn, 1)
        row, rc = kill_after_claim(self.args.dsn, self.out, "dead")
        assert scalar(self.conn, "SELECT status FROM c_runtime_task") == "RUNNING"
        wait_expired(self.conn)
        recovered = PostgresRuntimeRepository(self.conn).recover_expired()
        assert recovered == [("task-0", "C1", "QUEUED")]
        obs = run_workers(self.args.dsn, 1, self.out, self.monitor, "replacement")
        assert all(w["rc"] == 0 for w in obs["workers"])
        assert scalar(self.conn, "SELECT status FROM c_runtime_task") == "SUCCEEDED"
        assert scalar(self.conn, "SELECT count(*) FROM c_runtime_effect") == 1
        return {"signal_rc": rc, "attempt": row[4], "recovered": recovered, "replacement": obs}

    def old_worker_fencing(self):
        setup(self.conn)
        seed(self.conn, 1)
        repo = PostgresRuntimeRepository(self.conn)
        old = repo.claim_one("C1", "reused-worker", lease_s=1)
        wait_expired(self.conn)
        expired_rejected = not repo.complete(task_id="task-0", owner_c="C1", worker_id="reused-worker",
                                             expected_attempt=old[4], success=True)
        assert expired_rejected
        assert repo.recover_expired() == [("task-0", "C1", "QUEUED")]
        new = repo.claim_one("C1", "reused-worker", lease_s=30)
        assert new[4] > old[4]
        stale_epoch_rejected = not repo.complete(task_id="task-0", owner_c="C1", worker_id="reused-worker",
                                                 expected_attempt=old[4], success=True)
        assert stale_epoch_rejected
        assert scalar(self.conn, "SELECT status FROM c_runtime_task") == "RUNNING"
        assert repo.complete(task_id="task-0", owner_c="C1", worker_id="reused-worker",
                             expected_attempt=new[4], success=True)
        return {"expired_rejected": expired_rejected, "stale_epoch_rejected": stale_epoch_rejected,
                "old_attempt": old[4], "new_attempt": new[4]}

    def retry_exhaustion(self):
        setup(self.conn)
        seed(self.conn, 1)
        self.conn.execute("UPDATE c_runtime_task SET max_attempts=3")
        repo = PostgresRuntimeRepository(self.conn)
        transitions = []
        for attempt in range(1, 4):
            row, rc = kill_after_claim(self.args.dsn, self.out, f"retry-{attempt}")
            assert row[4] == attempt and rc == -signal.SIGKILL
            wait_expired(self.conn)
            transitions.extend(repo.recover_expired())
        assert [r[2] for r in transitions] == ["QUEUED", "QUEUED", "ESCALATED"]
        assert repo.claim_one("C1", "after-budget") is None
        assert scalar(self.conn, "SELECT count(*) FROM c_runtime_task") == 1
        return {"transitions": transitions, "task_preserved": True}

    def database_restart(self):
        container = self.args.restart_container
        if os.environ.get("GITHUB_ACTIONS") != "true" or not re.fullmatch(r"[0-9a-f]{64}", container or ""):
            raise RuntimeError("real restart requires the disposable GitHub Actions service container ID")
        setup(self.conn)
        seed(self.conn, 1)
        repo = PostgresRuntimeRepository(self.conn)
        running = repo.claim_one("C1", "pre-restart", lease_s=1)
        before_task = query(self.conn, "SELECT * FROM c_runtime_task")
        before_start = scalar(self.conn, "SELECT pg_postmaster_start_time()")
        source = Runtime(self.out / "canonical-evidence.sqlite3")
        for i in range(3):
            source.append_evidence("C1", None, "RESTART_ACCEPTANCE", {"i": i})
        assert source.verify_evidence_chain()
        with source.tx() as db:
            events = [dict(r) for r in db.execute("SELECT * FROM evidence ORDER BY created_at,evidence_id")]
        project_chain(self.conn, projection_key="main", events=events)
        before_projection = query(self.conn, "SELECT last_event_hash,last_event_id,event_count FROM c_runtime_evidence_projection")
        self.conn.close()
        self.monitor.close()
        subprocess.run(["docker", "restart", "--time", "0", container], check=True, timeout=45,
                       stdout=subprocess.DEVNULL)
        # Restart completion is independently checked by a new DB session/start time.
        deadline = time.monotonic() + 30
        while True:
            try:
                self.conn = connect(self.args.dsn)
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        self.monitor = connect(self.args.dsn, "runtime-monitor")
        after_start = scalar(self.conn, "SELECT pg_postmaster_start_time()")
        after_task = query(self.conn, "SELECT * FROM c_runtime_task")
        after_projection = query(self.conn, "SELECT last_event_hash,last_event_id,event_count FROM c_runtime_evidence_projection")
        assert after_start > before_start
        assert before_task == after_task and before_projection == after_projection
        wait_expired(self.conn)
        repo = PostgresRuntimeRepository(self.conn)
        assert repo.recover_expired() == [("task-0", "C1", "QUEUED")]
        replacement = repo.claim_one("C1", "post-restart")
        assert not repo.complete(task_id="task-0", owner_c="C1", worker_id="pre-restart",
                                 expected_attempt=running[4], success=True)
        assert repo.complete(task_id="task-0", owner_c="C1", worker_id="post-restart",
                             expected_attempt=replacement[4], success=True)
        self.restart_events = events
        return {"before_start": before_start, "after_start": after_start,
                "durable_task_equal": True, "durable_projection_equal": True,
                "expired_lease_recovered": True, "old_worker_rejected": True}

    def evidence_projection(self):
        if self.restart_events is None:
            raise RuntimeError("real restart evidence prerequisite missing")
        source = Runtime(self.out / "canonical-evidence.sqlite3")
        assert source.verify_evidence_chain()
        events = self.restart_events
        expected = [(events[-1]["event_hash"], events[-1]["evidence_id"], len(events))]
        for _ in range(2):
            project_chain(self.conn, projection_key="main", events=events)
            assert query(self.conn, "SELECT last_event_hash,last_event_id,event_count FROM c_runtime_evidence_projection") == expected
        return {"canonical_chain_valid": True, "replays": 2, "projection": expected}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dsn", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--restart-container")
    p.add_argument("--candidate-sha", required=True)
    args = p.parse_args()
    dsn = conninfo_to_dict(args.dsn)
    if dsn.get("host") not in ("127.0.0.1", "localhost") or dsn.get("dbname") != "runtime":
        p.error("acceptance is restricted to a disposable local database named runtime")
    acceptance = Acceptance(args)
    try:
        # Restart follows the other destructive scenarios; replay follows restart.
        for name in ("claim_contention", "duplicate_dispatch", "effect_idempotency", "worker_death",
                     "old_worker_fencing", "retry_exhaustion", "database_restart", "evidence_projection"):
            method = acceptance.contention if name == "claim_contention" else getattr(acceptance, name)
            acceptance.run(name, method)
    finally:
        acceptance.conn.close()
        acceptance.monitor.close()
    failed = [r["name"] for r in acceptance.results if r["passed"] is not True]
    assert set(r["name"] for r in acceptance.results) == set(REQUIRED)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
