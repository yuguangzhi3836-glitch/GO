"""PostgreSQL repository contract.

This adapter is intentionally dependency-neutral: it documents the exact SQL
required for HA claiming. Production wiring must provide a DB-API connection.
"""
CLAIM_SQL = """
WITH next_task AS (
  SELECT task_id
  FROM c_runtime_task
  WHERE owner_c=%s AND status='QUEUED' AND available_at<=now()
  ORDER BY priority, created_at
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
RETURNING t.*;
"""

RECOVER_SQL = """
UPDATE c_runtime_task
SET status=CASE WHEN attempts < max_attempts THEN 'QUEUED' ELSE 'ESCALATED' END,
    lease_owner=NULL,
    lease_until=NULL,
    last_error=CASE WHEN attempts < max_attempts THEN 'LEASE_EXPIRED' ELSE 'MAX_ATTEMPTS_EXHAUSTED' END,
    updated_at=now()
WHERE status='RUNNING' AND lease_until < now()
RETURNING task_id, owner_c, status;
"""

def claim_one(conn, owner_c: str, worker_id: str, lease_s: int=120):
    with conn:
        with conn.cursor() as cur:
            cur.execute(CLAIM_SQL,(owner_c,worker_id,lease_s))
            return cur.fetchone()

def recover_expired(conn):
    with conn:
        with conn.cursor() as cur:
            cur.execute(RECOVER_SQL)
            return cur.fetchall()
