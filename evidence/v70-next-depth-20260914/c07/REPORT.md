# V70-R2-C07-02 — process durability and consent withdrawal

**Status: EVIDENCE_READY, 4/6.** C14 and C13 remain independent stages. Local PostgreSQL is HOLD; the prepared PostgreSQL CI must actually run before any PostgreSQL result can be claimed.

The source anchor is main `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; the inherited candidate is PR73 `a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b`, application tree `740d026e3723f5da015342ead3394969629541df`. Initial C07 product bytes were checked against the independent PR73 snapshot. This task did not create a Git commit, change an external application or operate Hong Kong/Production.

## Actual gap and minimal fix

The first six-process acceptance run returned **5 passed, 1 failed**. It demonstrated a privacy boundary defect: a reader paused after loading an active consent; a separate process withdrew that consent and exited successfully; when resumed, the reader still released one preference from the old grant. The existing SQLite SELECT handling did not retain a transaction that serialized this read against withdrawal. Raw logs, JUnit, PIDs and timestamps remain under `red/`.

Only `application/src/go_hotel/travel_intelligence/preferences.py` changed in product code:

- Preference and graph projections now use the existing `mutation_session`, including SQLite `BEGIN IMMEDIATE`.
- Active grants are locked with `SELECT … FOR UPDATE`, ordered by consent ID. The existing vault withdrawal UPDATE uses that same consent row.
- Current time is taken after the query has acquired its locks, so waiting for a lock does not reuse a pre-wait expiry timestamp.

The protected database transaction is the linearization boundary. If withdrawal commits first, subsequent projection/write cannot use that grant. If the protected transaction acquires its grant first, withdrawal must wait until that transaction finishes. This does not claim to retract bytes already transmitted or retained by a client. PostgreSQL row-lock behavior remains subject to the actual CI run.

## Runtime evidence

| Run | Actual result | Scope |
| --- | --- | --- |
| First process acceptance | 5 PASS / 1 FAIL, 60.42 seconds | The failing read/withdrawal interleaving above. |
| Re-run of that failure after repair | 1 PASS, 11.34 seconds | Same assertion; not weakened. |
| Final affected acceptance | 40 PASS / 0 FAIL / 0 SKIP, 72.01 seconds | Six process tests plus 34 affected explicit-preference tests. |

The six process scenarios prove, in local isolated SQLite:

1. A committed preference remains readable by a fresh OS process after its writer intentionally exits with code 73; withdrawal by another process remains effective on another fresh read.
2. Killing an update process with SIGKILL before transaction commit preserves the original revision; a fresh process can then update that revision correctly. The pause is before commit; this is not a claim that every possible storage-journal crash point was tested.
3. Two separate processes racing to create the same preference produce one winner and one revision conflict.
4. A withdrawal that completes before a waiting writer is released causes that writer to be rejected and fresh reads to remain empty.
5. Withdrawal versus an update paused after consent authorization observes transaction ordering and does not permit an old grant to authorize a post-withdrawal update.
6. Withdrawal versus a read paused after consent authorization observes transaction ordering and does not release an old grant after a completed withdrawal.

Each child records its PID, source hash, operation, start/result timestamps and exit code. `green-processes/*/process-ledger.json` binds raw stdout/stderr to the controller's start/finish records. Distinct PIDs prove these are independent operating-system processes, rather than a SQLAlchemy engine reopen in one process. Tests use normal subprocess workers and `-p no:cacheprovider`, with `PYTHONDONTWRITEBYTECODE=1`.

The original 51-PASS evidence remains unchanged under `evidence/v70-round2-20260914/c07/`. This task repeated only affected preference/graph functionality, not the unrelated previously passed vault, hotel-infrastructure and C09 suites. Two existing TestClient deprecation warnings remain in the final log; dependencies were not changed.

## PostgreSQL CI handoff

The local probe found no postgres, initdb, pg_ctl, psql, Docker or Podman executable, and no standard PostgreSQL installation directory. No dependency was installed and no remote database was accessed. `pg-local-hold/` additionally demonstrates that the new runner returns exit 2/HOLD when no isolated PostgreSQL URL is supplied; this is not a PostgreSQL test result.

The central dispatcher can run this frozen entry point against its dedicated PostgreSQL 18.4 service:

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  GO_C07_RUNTIME_DATABASE_URL='postgresql+psycopg://go_ci:isolated_ci_only@127.0.0.1:5432/go_c07_isolated' \
  GO_C07_SOURCE_COMMIT='<actual candidate full commit>' \
  python ci/next_depth/c07_postgres.py --evidence-dir '<artifact directory>'
```

The credentials in this command are the dispatcher's synthetic CI fixture. The runner accepts only a loopback host and a dedicated database whose name starts with `go_c07_isolated`. Each case creates one random `c07_*` schema, sets that schema as its search path, creates only the five existing traveler/profile/consent/audit/permission tables required for this isolated scope, and drops that schema afterward. It does not run a business migration or write public-schema tables. The PostgreSQL server version, candidate identifier supplied by CI, actual file hashes, raw pytest log, JUnit and child evidence are emitted separately.

Run the six process cases unchanged in that environment. A failed ordering assertion is a real gate failure; do not remove the pause, skip the case or lower the assertion. A successful CI result still requires independent C14/C13 review and does not authorize deployment.

## Frozen source and next action

The four changed/new files and hashes are in `source-manifest.json`. Their canonical file-list SHA256 is:

`8837284c7d2374a2734712c991a9635a6897eab4a5ad87a0329f5a2da2a737f5`.

The narrow product diff is preserved in `c07-runtime-fix.patch`. No models, migrations, dependencies, public routes or C09 truth code changed in this task.

Next action: central integration runs the frozen PostgreSQL CI candidate and returns its raw evidence to C14/C13. C07 remains responsible for fixing any reproduced failure from that run. Local SQLite success must not substitute for the pending PostgreSQL evidence.
