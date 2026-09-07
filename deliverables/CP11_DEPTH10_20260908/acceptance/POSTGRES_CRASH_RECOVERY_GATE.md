# DEPTH10 PostgreSQL forced-interruption recovery gate

This gate must run against PostgreSQL. SQLite/local folding tests are not sufficient evidence for production claim safety.

## Required scenario

1. Enqueue one deterministic chain hotel task.
2. Worker A claims it with a short lease and commits the LEASED event.
3. Terminate Worker A without ACK and without calling `fail()`.
4. Before lease expiry, Worker B must not claim the same task.
5. After lease expiry, Worker B must reclaim the same `task_id`; `attempt` must increment exactly once.
6. Worker B ACKs the task.
7. A third worker must never claim the ACKED task.
8. Folded history must show one logical task, no duplicate hotel publication, and monotonic attempts.
9. Run a multi-process contention case where >=6 workers race for one queued task; exactly one live lease owner is allowed.
10. Repeat with a retryable failure and verify RETRY_WAIT -> LEASED -> ACKED, then with a deterministic failure and verify DEAD is terminal.

## Mandatory evidence

Record PostgreSQL version, database URL redacted, test command, UTC timestamps, worker PIDs, task id, event history, attempts, lease expiries, final state and exit code. Preserve the raw test output in the release evidence directory.

## PASS criteria

`POSTGRES_CRASH_RECOVERY_GATE=PASS` only if every assertion above passes on PostgreSQL and the test process exits 0. Any missing evidence, SQLite-only run, duplicate live ownership, early reclaim, lost task, duplicate publication or post-ACK reclaim is HOLD.

Until this gate is PASS:

- legacy regional Redis worker is not cut over;
- 50-hotel concurrency is a target, not an accepted production claim;
- `HOTEL_REPLICATION_GATE=HOLD`;
- `FINAL_RELEASE_GATE=HOLD`.
