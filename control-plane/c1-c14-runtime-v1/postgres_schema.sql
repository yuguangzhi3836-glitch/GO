-- PostgreSQL target schema for C1-C14 Runtime V1.
-- Candidate only. Do not install without explicit Command Center authorization.

CREATE TABLE IF NOT EXISTS c_runtime_task (
  task_id text PRIMARY KEY,
  idempotency_key text UNIQUE,
  owner_c text NOT NULL CHECK (owner_c ~ '^C([1-9]|1[0-4])$'),
  created_by_c text,
  kind text NOT NULL,
  payload jsonb NOT NULL,
  priority integer NOT NULL DEFAULT 100,
  status text NOT NULL CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','ESCALATED','CANCELLED')),
  available_at timestamptz NOT NULL,
  lease_owner text,
  lease_until timestamptz,
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 5,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS c_runtime_task_claim_idx
ON c_runtime_task(owner_c,status,available_at,priority,created_at);

CREATE TABLE IF NOT EXISTS c_runtime_effect (
  effect_key text PRIMARY KEY,
  task_id text NOT NULL REFERENCES c_runtime_task(task_id),
  effect_type text NOT NULL,
  body jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS c_runtime_evidence_projection (
  projection_key text PRIMARY KEY,
  last_event_hash text,
  last_event_id text,
  event_count bigint NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);
