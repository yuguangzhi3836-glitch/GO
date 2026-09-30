"""PostgreSQL runtime repository adapter.

Requires a DB-API 2.0 compatible PostgreSQL connection (psycopg/psycopg2 style).
No connection creation occurs here; callers inject an already-authorized isolated DB connection.
"""
from __future__ import annotations
import json
from typing import Any

CLAIM_SQL = """
WITH next_task AS (
  SELECT task_id
  FROM c_runtime_task
  WHERE owner_c=%s
    AND status='QUEUED'
    AND available_at<=now()
  ORDER BY priority ASC, created_at ASC
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
UPDATE c_runtime_task t
SET status='RUNNING',
    lease_owner=%s,
    lease_until=now() + (%s || ' seconds')::interval,
    attempts=attempts+1,
    updated_at=now()
FROM next_task
WHERE t.task_id=next_task.task_id
RETURNING t.task_id,t.owner_c,t.kind,t.payload,t.attempts,t.lease_until;
"""

COMPLETE_SQL = """
UPDATE c_runtime_task
SET status=%s, lease_owner=NULL, lease_until=NULL, last_error=%s, updated_at=now()
WHERE task_id=%s AND owner_c=%s AND status='RUNNING' AND lease_owner=%s
RETURNING task_id;
"""

RECOVER_SQL = """
UPDATE c_runtime_task
SET status=CASE WHEN attempts < max_attempts THEN 'QUEUED' ELSE 'ESCALATED' END,
    lease_owner=NULL,
    lease_until=NULL,
    available_at=CASE WHEN attempts < max_attempts THEN now() ELSE available_at END,
    last_error=CASE WHEN attempts < max_attempts THEN 'LEASE_EXPIRED' ELSE 'MAX_ATTEMPTS_EXHAUSTED' END,
    updated_at=now()
WHERE status='RUNNING' AND lease_until < now()
RETURNING task_id,owner_c,status;
"""

INSERT_EFFECT_SQL = """
INSERT INTO c_runtime_effect(effect_key,task_id,effect_type,body)
VALUES (%s,%s,%s,%s::jsonb)
ON CONFLICT(effect_key) DO NOTHING
RETURNING effect_key;
"""

class PostgresRuntimeRepository:
    def __init__(self, conn):
        self.conn=conn

    def claim_one(self, owner_c: str, worker_id: str, lease_s: int=120):
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute(CLAIM_SQL,(owner_c,worker_id,lease_s))
                row=cur.fetchone()
        return row

    def complete(self, *, task_id: str, owner_c: str, worker_id: str, success: bool, error: str|None=None) -> bool:
        status="SUCCEEDED" if success else "FAILED"
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute(COMPLETE_SQL,(status,error,task_id,owner_c,worker_id))
                row=cur.fetchone()
        return row is not None

    def recover_expired(self):
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute(RECOVER_SQL)
                return cur.fetchall()

    def record_effect_once(self, *, effect_key: str, task_id: str, effect_type: str, body: dict[str,Any]) -> bool:
        raw=json.dumps(body,sort_keys=True,separators=(",",":"))
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute(INSERT_EFFECT_SQL,(effect_key,task_id,effect_type,raw))
                row=cur.fetchone()
        return row is not None
