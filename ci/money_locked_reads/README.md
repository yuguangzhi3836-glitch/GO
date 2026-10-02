# RIDE money locked-read candidate

Change classes: PRODUCT_FIX (performance candidate), TEST_ONLY, DOCUMENTATION.
Base: `05b108cc63b008aad4da732ac97c7e453cf59220`.

## Scope

Only PostgreSQL RIDE_ORDER AUTHORIZATION/CAPTURE uses the combined movement
read. Root intent FOR UPDATE remains a separate, earlier statement. The next
statement locks rows matching either the current root or the global idempotency
key, in movement-ID order. Global-key conflict checks run before all guards;
only current-root rows enter budget calculations. Supplier, credit-source and
cash guards remain present. SQLite, other verticals and other movement types
retain the original path. No schema, pool, deployment or commit-boundary change.

Do not join the root lock to history in a single statement: a statement snapshot
taken before waiting on the root can miss newly committed movement rows. This
candidate relies on the existing transaction discipline and READ COMMITTED;
it is not certification for REPEATABLE READ or SERIALIZABLE. It does not refresh
pre-existing ORM identity-map objects or change autoflush=False behavior.

History locks move before guards only in the narrow RIDE AUTH/CAPTURE path,
where supplier/cash return without SQL and credit-source checking acquires no
business row lock. Extending this to hotel guards requires a new lock review.
Credit-source checking must not be skipped based on the business type.

## Actual local verification

Python 3.12.14, PostgreSQL 16.2, SQLAlchemy 2.1.2, psycopg 3.3.6.
This is **not** the historical diagnostic's PostgreSQL 18.4 / SQLAlchemy 2.1.1
environment. No external database, pressure test, ABBA, merge or deployment ran.

32 PostgreSQL test instances passed: 16 cases, each run against both the exact
base implementation and candidate, using real models/guards and newly created
schemas on a private local Unix-socket server. Cases cover simultaneous replay,
changed amount/type/parent/root conflicts, global-key insert races and recovery
of a failed Session, parent budgets, concurrent new-key overspend, CAPTURE vs
RELEASE, credit-source protection including a source committed during root lock
wait, post-lock visibility of committed AUTH, same-Session flush/rollback,
backend termination before/after CAPTURE commit, and process exit after AUTH
commit or before/after CAPTURE commit. Ledger balance and fulfillment atomicity
are checked. Backend termination after commit models a discarded response,
not a network fault inside the COMMIT acknowledgement exchange.

Six existing SQLite tests passed in:
`test_depth12_parent_money_budget.py` and
`test_unified_money_movement_finance_close.py`.

| SELECT count | Base | Candidate |
| --- | ---: | ---: |
| First AUTH | 4 | 3 |
| First CAPTURE, full amount with fulfillment | 5 | 4 |
| CAPTURE replay | 2 | 2 |
| Movement rows returned/locked by replay in two-row history | 1 | 2 |

The two saved statements per successful AUTH/CAPTURE pair do not imply a
CPU/P95 improvement. Replays now read and lock the history, including on a
conflicting request. Long-history and contention cost, and the OR query plan,
remain unmeasured. No cached-query or across-commit connection-reuse candidate
from rejected experiments is imported.

## Reproduce local correctness

Install the application's dev dependencies in an isolated environment. Start a
disposable PostgreSQL server listening ONLY on an owned `/tmp/go-money-*` Unix
socket. The suite rejects ordinary TCP/application database URLs and uses a
fresh `money_read_<uuid>` schema per case, dropping only that schema afterward.
The base commit must be present in the local Git object database.

```sh
MONEY_READ_TEST_URL='postgresql+psycopg://postgres@/postgres?host=/tmp/go-money-pgsocket&port=55439' \
  python -m pytest ci/money_locked_reads/test_correctness.py -q -s
cd application
python -m pytest tests/test_depth12_parent_money_budget.py tests/test_unified_money_movement_finance_close.py
```

This test harness has no load-generator entrypoint and does not connect to PSPs.
Child exit tests use the selected source module and same isolated schema.

## Gate

GO: review this small reversible candidate; scoped local correctness passed.
HOLD / NO-GO: formal ABBA admission, performance adoption, merge and deployment.
Before performance admission, repeat correctness on PostgreSQL 18.4 with the
target dependency versions; review the changed lock footprint, long-history
replays, query plan and existing identity-map/isolation assumptions. Any future
ABBA needs separate authorization, fixed current-main/candidate identities and
unchanged CPU -20%, P95 -15%, 100-actor P95 <=5s gates.

Rollback is the single candidate commit revert; there is no migration.
