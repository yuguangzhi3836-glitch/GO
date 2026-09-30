-- PostgreSQL target contract for C1-C14 Runtime V1.
-- Candidate schema only; no migration is installed by this PR.
CREATE TABLE c_runtime_task (
  task_id text PRIMARY KEY,
  idempotency_key text UNIQUE,
  owner_c text NOT NULL CHECK (owner_c ~ '^C([1-9]|1[0-4])$'),
  created_by_c text,
  kind text NOT NULL,
  payload jsonb NOT NULL,
  priority integer NOT NULL DEFAULT 100,
  status text NOT NULL,
  available_at timestamptz NOT NULL,
  lease_owner text,
  lease_until timestamptz,
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 5,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX c_runtime_task_claim_idx
ON c_runtime_task(owner_c,status,available_at,priority,created_at);

-- Atomic multi-worker claim pattern:
-- SELECT task_id FROM c_runtime_task
-- WHERE owner_c=$1 AND status='QUEUED' AND available_at<=now()
-- ORDER BY priority,created_at
-- FOR UPDATE SKIP LOCKED LIMIT 1;
