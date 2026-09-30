# Isolated PostgreSQL concurrency acceptance plan

This is the mandatory gate before persistent Runtime installation.

## Environment
- isolated PostgreSQL only
- no Production
- no real supplier/payment endpoints
- fixed candidate from Draft PR #285
- at least 4 independent worker processes

## Scenarios

### 1. Claim contention
Seed 1,000 runnable tasks split across C1-C12.
Run 4-16 worker processes concurrently.
Pass only if:
- each task has at most one active lease owner;
- no task is returned by two workers in the same lease epoch;
- final terminal+queued+escalated count equals seeded count.

### 2. Duplicate dispatch / idempotency
Submit the same idempotency key concurrently from multiple clients.
Pass only if exactly one task identity exists.

### 3. Exactly-once-effect boundary
For one logical side effect, concurrently attempt the same effect_key.
Pass only if one row is inserted into c_runtime_effect and every duplicate reports conflict/no-op.
This proves exactly-once recording, not magical exactly-once execution of arbitrary external systems.

### 4. Worker death after claim
SIGKILL workers after claim but before completion.
Pass only if lease expiry returns unfinished work to QUEUED and a replacement worker can claim it.

### 5. Database restart during lease
Restart isolated PostgreSQL with RUNNING tasks.
Pass only if durable task rows survive and expired leases recover after restart.

### 6. Old-worker fencing
After takeover, the previous lease owner attempts completion.
Pass only if the UPDATE returns zero rows.

### 7. Retry exhaustion
Repeatedly kill the same task until max_attempts.
Pass only if it becomes ESCALATED and is not silently dropped.

### 8. Evidence projection consistency
Compare canonical append-only evidence source with c_runtime_evidence_projection.
Pass only if event_count, last_event_id and last_event_hash converge exactly after restart/replay.

## Required evidence
- SQL seed and cleanup scripts
- process launch command
- worker logs
- database server log excerpt around restart
- per-scenario JSON result
- aggregate JUnit/XML
- SHA256 manifest
- C13 independent verdict
- C14 control/runtime verdict

Passing this plan still does not authorize merge or installation.
