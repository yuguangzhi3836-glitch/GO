"""GO C1-C14 Runtime V1.

Durable coordination kernel for fourteen AI responsibility domains.
Standard-library only. This module deliberately has no deployment, payment,
supplier, shell, signing, or Production integration.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

C_IDS = tuple(f"C{i}" for i in range(1, 15))
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "ESCALATED"}

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS agents (
  c_id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'IDLE',
  heartbeat_at REAL,
  lease_until REAL,
  generation INTEGER NOT NULL DEFAULT 0,
  last_error TEXT
);

CREATE TABLE IF NOT EXISTS agent_state (
  c_id TEXT NOT NULL,
  state_key TEXT NOT NULL,
  value_json TEXT NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY (c_id, state_key),
  FOREIGN KEY (c_id) REFERENCES agents(c_id)
);

CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE,
  owner_c TEXT NOT NULL,
  created_by_c TEXT,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 100,
  status TEXT NOT NULL DEFAULT 'QUEUED',
  available_at REAL NOT NULL,
  lease_owner TEXT,
  lease_until REAL,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5,
  last_error TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY (owner_c) REFERENCES agents(c_id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_claim
ON tasks(owner_c, status, available_at, priority, created_at);

CREATE TABLE IF NOT EXISTS messages (
  message_id TEXT PRIMARY KEY,
  from_c TEXT NOT NULL,
  to_c TEXT NOT NULL,
  topic TEXT NOT NULL,
  body_json TEXT NOT NULL,
  correlation_id TEXT,
  status TEXT NOT NULL DEFAULT 'UNREAD',
  created_at REAL NOT NULL,
  read_at REAL
);

CREATE INDEX IF NOT EXISTS idx_messages_to_c
ON messages(to_c, status, created_at);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  c_id TEXT NOT NULL,
  task_id TEXT,
  event_type TEXT NOT NULL,
  body_json TEXT NOT NULL,
  prev_hash TEXT,
  event_hash TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_task
ON evidence(task_id, created_at);

CREATE TABLE IF NOT EXISTS escalations (
  escalation_id TEXT PRIMARY KEY,
  c_id TEXT NOT NULL,
  task_id TEXT,
  severity TEXT NOT NULL,
  reason TEXT NOT NULL,
  details_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'OPEN',
  requires_human INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  resolved_at REAL
);

CREATE TABLE IF NOT EXISTS permissions (
  c_id TEXT NOT NULL,
  action TEXT NOT NULL,
  decision TEXT NOT NULL,
  PRIMARY KEY (c_id, action)
);
"""

SAFE_ACTIONS = (
    "READ_REPOSITORY",
    "WRITE_CANDIDATE_BRANCH",
    "RUN_ISOLATED_TEST",
    "CREATE_DRAFT_PR",
    "WRITE_EVIDENCE",
    "CROSS_C_MESSAGE",
)
HUMAN_ACTIONS = (
    "MERGE_TO_MAIN",
    "HK_DEPLOY",
    "FINAL_RELEASE",
    "PRODUCTION",
    "REAL_PAYMENT",
    "REAL_SUPPLIER",
    "SIGN_EXECUTION_AUTHORITY",
)
DENIED_ACTIONS = (
    "READ_PRIVATE_KEYS",
    "EXPORT_SECRETS",
    "BYPASS_GATE",
)

@dataclass(frozen=True)
class ClaimedTask:
    task_id: str
    owner_c: str
    kind: str
    payload: dict[str, Any]
    attempts: int
    lease_until: float

class RuntimeErrorInvariant(RuntimeError):
    pass

class Runtime:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def tx(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            for c_id in C_IDS:
                conn.execute("INSERT OR IGNORE INTO agents(c_id) VALUES (?)", (c_id,))
                for action in SAFE_ACTIONS:
                    conn.execute(
                        "INSERT OR IGNORE INTO permissions(c_id,action,decision) VALUES (?,?,?)",
                        (c_id, action, "ALLOW"),
                    )
                for action in HUMAN_ACTIONS:
                    conn.execute(
                        "INSERT OR IGNORE INTO permissions(c_id,action,decision) VALUES (?,?,?)",
                        (c_id, action, "REQUIRE_HUMAN"),
                    )
                for action in DENIED_ACTIONS:
                    conn.execute(
                        "INSERT OR IGNORE INTO permissions(c_id,action,decision) VALUES (?,?,?)",
                        (c_id, action, "DENY"),
                    )

    @staticmethod
    def _require_c(c_id: str) -> None:
        if c_id not in C_IDS:
            raise ValueError(f"unknown responsibility domain: {c_id}")

    def heartbeat(self, c_id: str, *, ttl_s: int = 90, status: str = "IDLE") -> None:
        self._require_c(c_id)
        now = time.time()
        with self.tx() as conn:
            conn.execute(
                """UPDATE agents
                   SET status=?, heartbeat_at=?, lease_until=?, generation=generation+1, last_error=NULL
                   WHERE c_id=?""",
                (status, now, now + ttl_s, c_id),
            )

    def set_state(self, c_id: str, key: str, value: Any) -> None:
        self._require_c(c_id)
        now = time.time()
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.tx() as conn:
            conn.execute(
                """INSERT INTO agent_state(c_id,state_key,value_json,updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(c_id,state_key) DO UPDATE SET
                   value_json=excluded.value_json, updated_at=excluded.updated_at""",
                (c_id, key, raw, now),
            )

    def get_state(self, c_id: str, key: str, default: Any = None) -> Any:
        self._require_c(c_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM agent_state WHERE c_id=? AND state_key=?",
                (c_id, key),
            ).fetchone()
        return default if row is None else json.loads(row["value_json"])

    def authorize(self, c_id: str, action: str) -> str:
        self._require_c(c_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT decision FROM permissions WHERE c_id=? AND action=?",
                (c_id, action),
            ).fetchone()
        return "DENY" if row is None else str(row["decision"])

    def set_permission(self, c_id: str, action: str, decision: str) -> None:
        self._require_c(c_id)
        if decision not in {"ALLOW", "REQUIRE_HUMAN", "DENY"}:
            raise ValueError("invalid permission decision")
        with self.tx() as conn:
            conn.execute(
                """INSERT INTO permissions(c_id,action,decision) VALUES (?,?,?)
                   ON CONFLICT(c_id,action) DO UPDATE SET decision=excluded.decision""",
                (c_id, action, decision),
            )

    def enqueue(
        self,
        owner_c: str,
        kind: str,
        payload: dict[str, Any],
        *,
        created_by_c: Optional[str] = None,
        priority: int = 100,
        available_at: Optional[float] = None,
        max_attempts: int = 5,
        idempotency_key: Optional[str] = None,
    ) -> str:
        self._require_c(owner_c)
        if created_by_c is not None:
            self._require_c(created_by_c)
        now = time.time()
        task_id = "rt_" + uuid.uuid4().hex
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.tx() as conn:
            if idempotency_key:
                existing = conn.execute(
                    "SELECT task_id FROM tasks WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    return str(existing["task_id"])
            conn.execute(
                """INSERT INTO tasks(
                     task_id,idempotency_key,owner_c,created_by_c,kind,payload_json,
                     priority,status,available_at,max_attempts,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,'QUEUED',?,?,?,?)""",
                (
                    task_id, idempotency_key, owner_c, created_by_c, kind, raw,
                    priority, available_at if available_at is not None else now,
                    max_attempts, now, now,
                ),
            )
        self.append_evidence(owner_c, task_id, "TASK_ENQUEUED", {
            "kind": kind, "created_by_c": created_by_c, "priority": priority
        })
        return task_id

    def claim(self, c_id: str, *, worker_id: str, lease_s: int = 120) -> Optional[ClaimedTask]:
        self._require_c(c_id)
        now = time.time()
        with self.tx() as conn:
            row = conn.execute(
                """SELECT * FROM tasks
                   WHERE owner_c=? AND status='QUEUED' AND available_at<=?
                   ORDER BY priority ASC, created_at ASC LIMIT 1""",
                (c_id, now),
            ).fetchone()
            if row is None:
                return None
            lease_until = now + lease_s
            changed = conn.execute(
                """UPDATE tasks SET status='RUNNING', lease_owner=?, lease_until=?,
                   attempts=attempts+1, updated_at=?
                   WHERE task_id=? AND status='QUEUED'""",
                (worker_id, lease_until, now, row["task_id"]),
            ).rowcount
            if changed != 1:
                return None
            attempts = int(row["attempts"]) + 1
            task = ClaimedTask(
                task_id=str(row["task_id"]),
                owner_c=c_id,
                kind=str(row["kind"]),
                payload=json.loads(row["payload_json"]),
                attempts=attempts,
                lease_until=lease_until,
            )
        self.heartbeat(c_id, status="BUSY")
        self.append_evidence(c_id, task.task_id, "TASK_CLAIMED", {
            "worker_id": worker_id, "attempt": task.attempts, "lease_until": lease_until
        })
        return task

    def renew_task(self, task_id: str, *, worker_id: str, lease_s: int = 120) -> float:
        now = time.time()
        lease_until = now + lease_s
        with self.tx() as conn:
            changed = conn.execute(
                """UPDATE tasks SET lease_until=?,updated_at=?
                   WHERE task_id=? AND status='RUNNING' AND lease_owner=?""",
                (lease_until, now, task_id, worker_id),
            ).rowcount
            if changed != 1:
                raise RuntimeErrorInvariant("task lease is not owned by worker")
        return lease_until

    def complete(
        self,
        c_id: str,
        task_id: str,
        *,
        worker_id: str,
        success: bool,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        self._require_c(c_id)
        now = time.time()
        status = "SUCCEEDED" if success else "FAILED"
        with self.tx() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row["owner_c"] != c_id or row["status"] != "RUNNING" or row["lease_owner"] != worker_id:
                raise RuntimeErrorInvariant("completion rejected: owner/lease mismatch")
            conn.execute(
                """UPDATE tasks SET status=?,lease_owner=NULL,lease_until=NULL,last_error=?,updated_at=?
                   WHERE task_id=?""",
                (status, error, now, task_id),
            )
        self.append_evidence(c_id, task_id, "TASK_COMPLETED", {
            "status": status, "result": result or {}, "error": error
        })
        self.heartbeat(c_id, status="IDLE")

    def send_message(
        self, from_c: str, to_c: str, topic: str, body: dict[str, Any], *,
        correlation_id: Optional[str] = None
    ) -> str:
        self._require_c(from_c)
        self._require_c(to_c)
        message_id = "msg_" + uuid.uuid4().hex
        now = time.time()
        raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.tx() as conn:
            conn.execute(
                """INSERT INTO messages(message_id,from_c,to_c,topic,body_json,correlation_id,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (message_id, from_c, to_c, topic, raw, correlation_id, now),
            )
        self.append_evidence(from_c, None, "CROSS_C_MESSAGE", {
            "message_id": message_id, "to_c": to_c, "topic": topic,
            "correlation_id": correlation_id
        })
        return message_id

    def inbox(self, c_id: str, *, mark_read: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        self._require_c(c_id)
        now = time.time()
        with self.tx() as conn:
            rows = conn.execute(
                """SELECT * FROM messages WHERE to_c=? AND status='UNREAD'
                   ORDER BY created_at ASC LIMIT ?""",
                (c_id, limit),
            ).fetchall()
            if mark_read and rows:
                conn.executemany(
                    "UPDATE messages SET status='READ',read_at=? WHERE message_id=?",
                    [(now, r["message_id"]) for r in rows],
                )
        return [{**dict(r), "body": json.loads(r["body_json"])} for r in rows]

    def append_evidence(
        self, c_id: str, task_id: Optional[str], event_type: str, body: dict[str, Any]
    ) -> str:
        self._require_c(c_id)
        now = time.time()
        raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        evidence_id = "ev_" + uuid.uuid4().hex
        with self.tx() as conn:
            prev = conn.execute(
                "SELECT event_hash FROM evidence ORDER BY created_at DESC,evidence_id DESC LIMIT 1"
            ).fetchone()
            prev_hash = None if prev is None else str(prev["event_hash"])
            canonical = json.dumps({
                "evidence_id": evidence_id, "c_id": c_id, "task_id": task_id,
                "event_type": event_type, "body": json.loads(raw),
                "prev_hash": prev_hash, "created_at": now,
            }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            event_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            conn.execute(
                """INSERT INTO evidence(
                   evidence_id,c_id,task_id,event_type,body_json,prev_hash,event_hash,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (evidence_id, c_id, task_id, event_type, raw, prev_hash, event_hash, now),
            )
        return evidence_id

    def verify_evidence_chain(self) -> bool:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence ORDER BY created_at ASC,evidence_id ASC"
            ).fetchall()
        previous = None
        for r in rows:
            if r["prev_hash"] != previous:
                return False
            canonical = json.dumps({
                "evidence_id": r["evidence_id"], "c_id": r["c_id"], "task_id": r["task_id"],
                "event_type": r["event_type"], "body": json.loads(r["body_json"]),
                "prev_hash": r["prev_hash"], "created_at": r["created_at"],
            }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != r["event_hash"]:
                return False
            previous = r["event_hash"]
        return True

    def escalate(
        self, c_id: str, reason: str, *, task_id: Optional[str] = None,
        severity: str = "MEDIUM", details: Optional[dict[str, Any]] = None,
        requires_human: bool = False
    ) -> str:
        self._require_c(c_id)
        escalation_id = "esc_" + uuid.uuid4().hex
        now = time.time()
        raw = json.dumps(details or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.tx() as conn:
            conn.execute(
                """INSERT INTO escalations(
                   escalation_id,c_id,task_id,severity,reason,details_json,requires_human,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (escalation_id, c_id, task_id, severity, reason, raw, int(requires_human), now),
            )
            if task_id:
                conn.execute(
                    """UPDATE tasks SET status='ESCALATED',lease_owner=NULL,lease_until=NULL,updated_at=?
                       WHERE task_id=? AND status NOT IN ('SUCCEEDED','CANCELLED')""",
                    (now, task_id),
                )
        self.append_evidence(c_id, task_id, "ESCALATION_OPENED", {
            "escalation_id": escalation_id, "severity": severity,
            "reason": reason, "requires_human": requires_human
        })
        return escalation_id

    def recover_stale(self, *, now: Optional[float] = None) -> dict[str, int]:
        """Recover expired workers/tasks without silently losing work.

        Expired RUNNING tasks are requeued while attempts remain. Exhausted tasks
        become ESCALATED and require review. Agent liveness becomes STALE.
        """
        cutoff = time.time() if now is None else now
        wall_now = time.time()
        requeued = escalated = stale_agents = 0
        exhausted: list[tuple[str, str]] = []
        with self.tx() as conn:
            rows = conn.execute(
                """SELECT task_id,owner_c,attempts,max_attempts FROM tasks
                   WHERE status='RUNNING' AND lease_until IS NOT NULL AND lease_until<?""",
                (cutoff,),
            ).fetchall()
            for row in rows:
                if int(row["attempts"]) < int(row["max_attempts"]):
                    conn.execute(
                        """UPDATE tasks SET status='QUEUED',lease_owner=NULL,lease_until=NULL,
                           available_at=?,last_error='LEASE_EXPIRED',updated_at=? WHERE task_id=?""",
                        (wall_now, wall_now, row["task_id"]),
                    )
                    requeued += 1
                else:
                    conn.execute(
                        """UPDATE tasks SET status='ESCALATED',lease_owner=NULL,lease_until=NULL,
                           last_error='MAX_ATTEMPTS_EXHAUSTED',updated_at=? WHERE task_id=?""",
                        (wall_now, row["task_id"]),
                    )
                    exhausted.append((str(row["owner_c"]), str(row["task_id"])))
                    escalated += 1
            stale_agents = conn.execute(
                """UPDATE agents SET status='STALE'
                   WHERE lease_until IS NOT NULL AND lease_until<? AND status!='STALE'""",
                (cutoff,),
            ).rowcount
        for c_id, task_id in exhausted:
            self.escalate(
                c_id, "MAX_ATTEMPTS_EXHAUSTED", task_id=task_id,
                severity="HIGH", requires_human=True
            )
        return {"requeued": requeued, "escalated": escalated, "stale_agents": stale_agents}

    def wake_candidates(self, *, now: Optional[float] = None) -> list[str]:
        """Return C domains that should be woken by an external supervisor."""
        now = time.time() if now is None else now
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT owner_c FROM tasks
                   WHERE status='QUEUED' AND available_at<=? ORDER BY owner_c""",
                (now,),
            ).fetchall()
        return [str(r["owner_c"]) for r in rows]

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            agents = [dict(r) for r in conn.execute("SELECT * FROM agents ORDER BY c_id")]
            task_counts = {
                r["status"]: r["n"] for r in conn.execute(
                    "SELECT status,COUNT(*) AS n FROM tasks GROUP BY status"
                )
            }
            open_escalations = conn.execute(
                "SELECT COUNT(*) AS n FROM escalations WHERE status='OPEN'"
            ).fetchone()["n"]
        return {
            "agents": agents,
            "task_counts": task_counts,
            "open_escalations": open_escalations,
            "evidence_chain_valid": self.verify_evidence_chain(),
        }
