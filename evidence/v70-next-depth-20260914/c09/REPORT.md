# C09 — V70-R2-C09-02

EVIDENCE_READY (4/6 stages), independent C14 then C13 still pending. Whole-domain completion is unknown.

Source anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; inherited candidate: `a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b`.

Same-hotel serialized evidence/judgment/recommendation transaction, exact completed-hook replay, sealed evidence reuse, concurrent first-standard bootstrap. SQLite runtime complete; PostgreSQL executable entry supplied and awaits actual CI evidence.

Uses the existing transaction helper (SQLite BEGIN IMMEDIATE) and a stable hotel SHA256-derived PostgreSQL transaction advisory lock, including first-writer absence, plus existing-row FOR UPDATE. Evidence is read inside that transaction; all prior ACTIVE/unterminated decisions are superseded together. Existing identical sealed evidence is reused; unchanged active decisions are replayed. Completed hooks store and verify their own judgment/package/hotel/source binding. Only hooks captured before the evidence read and represented in the package are completed. Missing or mismatched old bindings require review. Concurrent standard bootstrap double-checks under a transaction lock.

Current targeted result: **34 PASS, 0 failures, 0 errors, 0 skips**. Exact command, unique SQLite DB path, timestamps, source hashes before/after, raw output and JUnit remain alongside this report.

Earlier failures are preserved: red: four business-boundary failures; bootstrap-red: first simultaneous standard initialization unique constraint failure; review-red: invalid persisted-field supplement initialized standard before rejecting; now rejected before bootstrap and rechecked in transaction.

Remaining concrete scopes:

- Actual PostgreSQL 18.4 run is pending root CI; local missing-URL probe is HOLD/exit2, never a PG pass.
- Domain event/outbox appends remain after the core judgment transaction; interruption can leave missing events and replay does not replenish them. Exactly-once event recovery is not claimed.
- External SQL writers and concurrent standard-governance approval are outside this finite service-writer scope; no migration or uniqueness constraint was introduced.
- Legacy completed hooks with no durable binding require review; they do not fall back to hotel latest.

Next executable task for scheduler: `V70-R2-C09-03` — Close post-commit judgment-event/outbox interruption: bind created events atomically or recover missing events without duplicate publication, with process-exit evidence.

PostgreSQL entry: `application/ci/next_depth/c09_postgres.py --evidence-dir <artifact>` with `GO_C09_RUNTIME_DATABASE_URL`, `GO_C09_SOURCE_COMMIT`. It requires PG 18.4, loopback database exactly `go_c09_isolated`, creates a random schema, runs ten same-source acceptance tests, writes results/log/JUnit and drops only that random schema. It does not import application test conftest or alter worker configuration.
