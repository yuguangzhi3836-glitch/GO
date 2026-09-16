#!/usr/bin/env python3
"""Durable GO Cell task queue, lease state machine, and authenticated snapshot API."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import ssl
import threading
from typing import Any, Callable
from urllib import parse
from uuid import uuid4

CELL_IDS = {f"C{i:02d}" for i in range(1, 15)}
ACTIVE = {"ACKED", "RUNNING", "DIAGNOSE", "FIX", "RETEST"}
TERMINAL = {"DONE_SCOPED", "BLOCKED_EXTERNAL", "BLOCKED_WITH_EVIDENCE"}
SOURCE_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
EVIDENCE_RE = re.compile(r"[0-9a-f]{64}\Z")


class OrchestratorError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise OrchestratorError("timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class DurableOrchestrator:
    """SQLite-backed queue; every mutating decision uses BEGIN IMMEDIATE."""

    def __init__(self, database: Path | str, *, orchestrator_id: str | None = None):
        self.database = str(database)
        self._initialize(orchestrator_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self, orchestrator_id: str | None) -> None:
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    cell_id TEXT NOT NULL,
                    source_sha TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_id TEXT,
                    lease_id TEXT,
                    worker_id TEXT,
                    heartbeat_at TEXT,
                    lease_expires_at TEXT,
                    last_error TEXT,
                    evidence_sha256 TEXT,
                    release_condition TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tasks_claimable
                    ON tasks(status, cell_id, created_at, task_id);
            """)
            existing = connection.execute(
                "SELECT value FROM metadata WHERE key = 'orchestrator_id'"
            ).fetchone()
            identity = orchestrator_id or f"go-orchestrator-{uuid4()}"
            if existing and orchestrator_id and existing[0] != orchestrator_id:
                raise OrchestratorError("orchestrator identity conflicts with durable state")
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES('orchestrator_id', ?)",
                (identity,),
            )
            connection.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES('sequence', '0')")

    @staticmethod
    def _validate_task(task_id: str, cell_id: str, source_sha: str) -> None:
        if not isinstance(task_id, str) or not task_id.strip():
            raise OrchestratorError("task_id is required")
        if cell_id not in CELL_IDS:
            raise OrchestratorError("invalid cell_id")
        if not isinstance(source_sha, str) or not SOURCE_RE.fullmatch(source_sha):
            raise OrchestratorError("source_sha must be canonical lowercase Git identity")

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        value["payload"] = json.loads(value.pop("payload_json"))
        return value

    def enqueue(self, task_id: str, cell_id: str, source_sha: str,
                payload: dict[str, Any] | None = None, *, now: datetime | None = None) -> dict[str, Any]:
        self._validate_task(task_id, cell_id, source_sha)
        if payload is not None and not isinstance(payload, dict):
            raise OrchestratorError("payload must be an object")
        moment = stamp(now or utc_now())
        encoded = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if existing:
                if (existing["cell_id"], existing["source_sha"], existing["payload_json"]) != (
                        cell_id, source_sha, encoded):
                    connection.rollback()
                    raise OrchestratorError("task identity or payload conflict")
                connection.commit()
                return self._row(existing)  # type: ignore[return-value]
            connection.execute(
                """INSERT INTO tasks(task_id, cell_id, source_sha, payload_json, status,
                                      created_at, updated_at)
                   VALUES(?, ?, ?, ?, 'QUEUED', ?, ?)""",
                (task_id, cell_id, source_sha, encoded, moment, moment),
            )
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            connection.commit()
            return self._row(row)  # type: ignore[return-value]

    @staticmethod
    def _requeue_expired(connection: sqlite3.Connection, now: datetime) -> int:
        moment = stamp(now)
        placeholders = ",".join("?" for _ in ACTIVE)
        cursor = connection.execute(
            f"""UPDATE tasks
                   SET status = 'QUEUED', attempt_id = NULL, lease_id = NULL, worker_id = NULL,
                       heartbeat_at = NULL, lease_expires_at = NULL, updated_at = ?
                 WHERE status IN ({placeholders}) AND lease_expires_at <= ?""",
            (moment, *sorted(ACTIVE), moment),
        )
        return cursor.rowcount

    def reap_expired(self, *, now: datetime | None = None) -> int:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = self._requeue_expired(connection, now or utc_now())
            connection.commit()
            return count

    def claim(self, worker_id: str, *, cell_id: str | None = None,
              lease_seconds: int = 90, now: datetime | None = None) -> dict[str, Any] | None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise OrchestratorError("worker_id is required")
        if cell_id is not None and cell_id not in CELL_IDS:
            raise OrchestratorError("invalid cell_id")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds < 10:
            raise OrchestratorError("lease_seconds must be an integer >= 10")
        observed = now or utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._requeue_expired(connection, observed)
            parameters: list[Any] = [*sorted(ACTIVE)]
            cell_filter = ""
            if cell_id:
                cell_filter = "AND queued.cell_id = ?"
                parameters.append(cell_id)
            row = connection.execute(
                f"""SELECT queued.* FROM tasks AS queued
                     WHERE queued.status = 'QUEUED' {cell_filter}
                       AND NOT EXISTS (
                         SELECT 1 FROM tasks AS active
                          WHERE active.cell_id = queued.cell_id
                            AND active.status IN ({','.join('?' for _ in ACTIVE)})
                       )
                     ORDER BY queued.created_at, queued.task_id LIMIT 1""",
                (*parameters[-1:], *parameters[:-1]) if cell_id else tuple(parameters),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            attempt_id, lease_id = f"attempt-{uuid4()}", f"lease-{uuid4()}"
            heartbeat = stamp(observed)
            expires = stamp(observed + timedelta(seconds=lease_seconds))
            connection.execute(
                """UPDATE tasks SET status = 'ACKED', attempt_id = ?, lease_id = ?, worker_id = ?,
                                      heartbeat_at = ?, lease_expires_at = ?, updated_at = ?
                    WHERE task_id = ? AND status = 'QUEUED'""",
                (attempt_id, lease_id, worker_id, heartbeat, expires, heartbeat, row["task_id"]),
            )
            claimed = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (row["task_id"],)).fetchone()
            connection.commit()
            return self._row(claimed)

    @staticmethod
    def _bound_task(connection: sqlite3.Connection, task_id: str, worker_id: str,
                    attempt_id: str, lease_id: str, now: datetime) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise OrchestratorError("unknown task")
        if row["status"] not in ACTIVE:
            raise OrchestratorError("task has no active lease")
        if (row["worker_id"], row["attempt_id"], row["lease_id"]) != (worker_id, attempt_id, lease_id):
            raise OrchestratorError("lease binding mismatch")
        if instant(row["lease_expires_at"]) <= now:
            raise OrchestratorError("lease expired")
        return row

    def heartbeat(self, task_id: str, worker_id: str, attempt_id: str, lease_id: str,
                  *, stage: str = "RUNNING", lease_seconds: int = 90,
                  now: datetime | None = None) -> dict[str, Any]:
        if stage not in ACTIVE:
            raise OrchestratorError("invalid active stage")
        observed = now or utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._bound_task(connection, task_id, worker_id, attempt_id, lease_id, observed)
            moment, expires = stamp(observed), stamp(observed + timedelta(seconds=lease_seconds))
            connection.execute(
                "UPDATE tasks SET status = ?, heartbeat_at = ?, lease_expires_at = ?, updated_at = ? WHERE task_id = ?",
                (stage, moment, expires, moment, task_id),
            )
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            connection.commit()
            return self._row(row)  # type: ignore[return-value]

    def fail(self, task_id: str, worker_id: str, attempt_id: str, lease_id: str,
             error: str, *, lease_seconds: int = 90, now: datetime | None = None) -> dict[str, Any]:
        if not isinstance(error, str) or not error.strip():
            raise OrchestratorError("failure evidence is required")
        task = self.heartbeat(task_id, worker_id, attempt_id, lease_id, stage="DIAGNOSE",
                              lease_seconds=lease_seconds, now=now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE tasks SET last_error = ? WHERE task_id = ?", (error, task_id))
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            connection.commit()
            return self._row(row)  # type: ignore[return-value]

    def advance_recovery(self, task_id: str, worker_id: str, attempt_id: str, lease_id: str,
                         *, now: datetime | None = None) -> dict[str, Any]:
        observed = now or utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._bound_task(connection, task_id, worker_id, attempt_id, lease_id, observed)
            next_stage = {"DIAGNOSE": "FIX", "FIX": "RETEST", "RETEST": "RUNNING"}.get(row["status"])
            if next_stage is None:
                connection.rollback()
                raise OrchestratorError("task is not in the failure recovery chain")
            moment = stamp(observed)
            connection.execute("UPDATE tasks SET status = ?, heartbeat_at = ?, updated_at = ? WHERE task_id = ?",
                               (next_stage, moment, moment, task_id))
            updated = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            connection.commit()
            return self._row(updated)  # type: ignore[return-value]

    def complete(self, task_id: str, worker_id: str, attempt_id: str, lease_id: str,
                 evidence_sha256: str, *, now: datetime | None = None,
                 auto_claim_next: bool = True) -> dict[str, Any]:
        if not isinstance(evidence_sha256, str) or not EVIDENCE_RE.fullmatch(evidence_sha256):
            raise OrchestratorError("evidence_sha256 must be 64 lowercase hex characters")
        observed = now or utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._bound_task(connection, task_id, worker_id, attempt_id, lease_id, observed)
            moment = stamp(observed)
            connection.execute(
                """UPDATE tasks SET status = 'DONE_SCOPED', evidence_sha256 = ?,
                                    heartbeat_at = NULL, lease_expires_at = NULL, updated_at = ?
                    WHERE task_id = ?""",
                (evidence_sha256, moment, task_id),
            )
            finished = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            cell_id = row["cell_id"]
            connection.commit()
        result = {"completed": self._row(finished), "next_task": None}
        if auto_claim_next:
            result["next_task"] = self.claim(worker_id, cell_id=cell_id, now=observed)
        return result

    def block_external(self, task_id: str, evidence_sha256: str, release_condition: str,
                       *, now: datetime | None = None) -> dict[str, Any]:
        if not EVIDENCE_RE.fullmatch(evidence_sha256 or "") or not release_condition.strip():
            raise OrchestratorError("external block requires evidence SHA256 and release condition")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None or row["status"] == "DONE_SCOPED":
                connection.rollback()
                raise OrchestratorError("unknown or completed task")
            moment = stamp(now or utc_now())
            connection.execute(
                """UPDATE tasks SET status = 'BLOCKED_EXTERNAL', evidence_sha256 = ?, release_condition = ?,
                                    heartbeat_at = NULL, lease_expires_at = NULL, updated_at = ?
                    WHERE task_id = ?""",
                (evidence_sha256, release_condition, moment, task_id),
            )
            updated = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            connection.commit()
            return self._row(updated)  # type: ignore[return-value]

    def snapshot(self, challenge: str, *, now: datetime | None = None) -> dict[str, Any]:
        if not isinstance(challenge, str) or len(challenge) < 16:
            raise OrchestratorError("fresh challenge is required")
        observed = now or utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._requeue_expired(connection, observed)
            identity = connection.execute("SELECT value FROM metadata WHERE key = 'orchestrator_id'").fetchone()[0]
            sequence = int(connection.execute("SELECT value FROM metadata WHERE key = 'sequence'").fetchone()[0]) + 1
            connection.execute("UPDATE metadata SET value = ? WHERE key = 'sequence'", (str(sequence),))
            rows = connection.execute("SELECT * FROM tasks ORDER BY cell_id, created_at, task_id").fetchall()
            connection.commit()
        expected = sorted({row["cell_id"] for row in rows if row["status"] not in TERMINAL})
        executors = [{key: row[key] for key in (
            "cell_id", "status", "task_id", "source_sha", "attempt_id", "lease_id",
            "heartbeat_at", "lease_expires_at")}
            for row in rows if row["status"] in ACTIVE]
        return {"schema": "go.cell-orchestrator-snapshot.v1", "orchestrator_id": identity,
                "snapshot_id": f"snapshot-{uuid4()}", "sequence": sequence,
                "challenge": challenge, "generated_at": stamp(observed),
                "expected_executable_cells": expected, "executors": executors}

    def readiness(self) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                identity = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'orchestrator_id'"
                ).fetchone()
                connection.execute("SELECT COUNT(*) FROM tasks").fetchone()
        except (OSError, sqlite3.Error) as error:
            return {"status": "not_ready", "database": "unavailable", "error": str(error)}
        return {"status": "ready", "database": "available",
                "orchestrator_id": identity[0] if identity else None}


class LeaseReaper(threading.Thread):
    """Continuously return expired active leases to the durable queue."""

    def __init__(self, store: DurableOrchestrator, *, interval_seconds: float = 5,
                 clock: Callable[[], datetime] = utc_now):
        if interval_seconds <= 0:
            raise OrchestratorError("reaper interval must be positive")
        super().__init__(name="go-cell-lease-reaper", daemon=True)
        self.store = store
        self.interval_seconds = interval_seconds
        self.clock = clock
        self.stopped = threading.Event()
        self.last_error: str | None = None

    def run_once(self) -> int:
        return self.store.reap_expired(now=self.clock())

    def run(self) -> None:
        while not self.stopped.wait(self.interval_seconds):
            try:
                self.run_once()
                self.last_error = None
            except (OSError, sqlite3.Error, OrchestratorError) as error:
                self.last_error = str(error)

    def stop(self) -> None:
        self.stopped.set()


def make_handler(store: DurableOrchestrator, token: str,
                 clock: Callable[[], datetime] = utc_now):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, sort_keys=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            supplied = self.headers.get("Authorization", "")
            if not secrets.compare_digest(supplied, f"Bearer {token}"):
                self._reply(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 2 or length > 1024 * 1024:
                    raise OrchestratorError("invalid request size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise OrchestratorError("request body must be an object")
                path = parse.urlparse(self.path).path
                if path == "/internal/v1/cell-runtime-snapshot":
                    result = store.snapshot(body.get("challenge"), now=clock())
                elif path == "/internal/v1/tasks/enqueue":
                    result = store.enqueue(body.get("task_id"), body.get("cell_id"),
                                           body.get("source_sha"), body.get("payload"))
                elif path == "/internal/v1/tasks/claim":
                    result = store.claim(body.get("worker_id"), cell_id=body.get("cell_id"),
                                         lease_seconds=body.get("lease_seconds", 90)) or {}
                elif path == "/internal/v1/tasks/heartbeat":
                    result = store.heartbeat(body.get("task_id"), body.get("worker_id"),
                                             body.get("attempt_id"), body.get("lease_id"),
                                             stage=body.get("stage", "RUNNING"),
                                             lease_seconds=body.get("lease_seconds", 90))
                elif path == "/internal/v1/tasks/fail":
                    result = store.fail(body.get("task_id"), body.get("worker_id"),
                                        body.get("attempt_id"), body.get("lease_id"), body.get("error"))
                elif path == "/internal/v1/tasks/recovery/advance":
                    result = store.advance_recovery(body.get("task_id"), body.get("worker_id"),
                                                    body.get("attempt_id"), body.get("lease_id"))
                elif path == "/internal/v1/tasks/complete":
                    result = store.complete(body.get("task_id"), body.get("worker_id"),
                                            body.get("attempt_id"), body.get("lease_id"),
                                            body.get("evidence_sha256"))
                elif path == "/internal/v1/tasks/block-external":
                    result = store.block_external(body.get("task_id"), body.get("evidence_sha256"),
                                                  body.get("release_condition"))
                else:
                    self._reply(404, {"error": "not found"})
                    return
                self._reply(200, result)
            except (OrchestratorError, TypeError, ValueError, json.JSONDecodeError) as error:
                self._reply(409, {"error": str(error)})

        def do_GET(self) -> None:
            path = parse.urlparse(self.path).path
            if path == "/healthz":
                self._reply(200, {"status": "ok"})
                return
            if path == "/readyz":
                result = store.readiness()
                self._reply(200 if result["status"] == "ready" else 503, result)
                return
            self._reply(404, {"error": "not found"})

        def log_message(self, *args: Any) -> None:
            pass

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--token-env", default="GO_CELL_ORCHESTRATOR_TOKEN")
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    parser.add_argument("--allow-http-loopback", action="store_true")
    parser.add_argument("--reap-interval-seconds", type=float, default=5)
    args = parser.parse_args()
    token = os.environ.get(args.token_env)
    if not token or len(token) < 32:
        raise SystemExit("orchestrator bearer token must contain at least 32 characters")
    loopback = args.listen in {"127.0.0.1", "::1", "localhost"}
    if not (args.tls_cert and args.tls_key) and not (args.allow_http_loopback and loopback):
        raise SystemExit("TLS certificate/key required outside explicit loopback testing")
    store = DurableOrchestrator(args.database)
    server = ThreadingHTTPServer((args.listen, args.port), make_handler(store, token))
    if args.tls_cert and args.tls_key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.tls_cert, args.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    reaper = LeaseReaper(store, interval_seconds=args.reap_interval_seconds)
    reaper.start()
    try:
        server.serve_forever()
    finally:
        reaper.stop()
        reaper.join(timeout=max(1, args.reap_interval_seconds * 2))
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
