# CI PostgreSQL acceptance harness

Candidate only; Draft PR #285; no merge, installation, HK, Production, payment
or supplier access. Change classes for the repair: TEST_ONLY, CONTROL_PLANE,
PRODUCT_FIX, DOCUMENTATION. No schema or live topology change.

Both Runtime workflows check out the exact pull-request head. PostgreSQL runs
only against the disposable local PostgreSQL 18 service. SOURCE_BINDING.json
records candidate SHA, Runtime tree, application tree, run ID and attempt.

## Round 9 defects found in source

- A default psycopg connection leaves SELECT inside an implicit transaction.
  Subsequent transaction() blocks are savepoints, so setup/seed DDL is not
  committed and workers wait on relation locks. Later subprocess.run calls had
  no timeout. This explains a possible indefinite wait; no final verdict or
  live wait evidence was available from round 9 when the repair was prepared.
- Wait snapshots ran after workers had exited or been killed.
- The workflow touched db-restart-ok and the script treated its existence as a
  successful database restart. That was not restart evidence.
- The death test waited 3 seconds for a 30-second worker lease.
- PostgreSQL completion checked only a Worker name, not lease expiry or epoch.
- Duplicate/effect tests were sequential, retry used an UPDATE shortcut, and
  evidence projection read back constants rather than replaying a real chain.
- Failed acceptance skipped aggregation/upload, losing diagnostic artifacts.

## Repair and evidence

The harness uses autocommit connections with explicit short atomic writes,
statement/lock/connect timeouts, bounded workers and an independent live wait
sampler (including blocking PIDs and transaction age). Each result is saved
immediately; exceptions are recorded as FAIL. Missing/malformed results and
non-boolean or duplicate scenario verdicts fail closed. Artifact collection,
JUnit generation and SHA256 manifests run on success and failure.

Required scenarios retain their original thresholds:

1. 1,000 tasks at 4, 8 and 16 independent worker processes; unique task/lease
   claims, exactly 1,000 successful tasks/effects, no lost work. Each batch also
   verifies visibility from another connection after setup/seed/query.
2. 16 concurrent independent connections race the same dispatch key.
3. 16 concurrent connections race the same effect key (recording only).
4. Real SIGKILL after a committed claim, expiry, repository recovery and
   replacement completion/effect.
5. Expired and stale lease-epoch completions are rejected even when a Worker
   name is reused; the current epoch completes.
6. Three real SIGKILL/expiry/recovery cycles exhaust the retry budget while
   preserving the ESCALATED row.
7. A real docker restart of the Actions service ID; changed PostgreSQL start
   time, identical durable task/projection rows, recovery and old-worker denial.
8. Verified canonical Runtime evidence survives the database restart; repeated
   PostgreSQL projection replay matches the final event ID/hash/count.

PostgresRuntimeRepository.complete now requires expected_attempt from the
claim result and checks lease_until against the database wall clock. The
acceptance worker commits completion and effect recording atomically.

Runtime isolated contract PASS is scoped to those tests. PostgreSQL PASS is
scoped to this harness. Neither is C13 or C14, and neither grants installation.
The independent reviewers must still inspect scope and candidate binding.
