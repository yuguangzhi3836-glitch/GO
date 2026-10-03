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

**NO-GO for the current candidate**, following the PostgreSQL 18.4 replay-cost
retest below. Do not advance it into formal ABBA or adopt/merge/deploy it merely
because correctness passed. Preserve this rejected shape and its evidence for
review; any revised implementation needs fresh correctness and cost evidence.
Any future ABBA needs separate authorization, fixed current-main/candidate
identities and unchanged CPU -20%, P95 -15%, 100-actor P95 <=5s gates.

Rollback is the single candidate commit revert; there is no migration.

## PostgreSQL 18.4 follow-up: correctness passes, replay cost rejects candidate

The exact `f44c3e21f08906569ea404d9f7fcc2d33bbb28d3` application and original
correctness test hashes were preserved. PostgreSQL 18.4 was built from the
official source after SHA256 verification; SQLAlchemy was pinned to 2.1.1.
Python 3.12.14 / psycopg 3.3.6; READ COMMITTED, fsync and synchronous_commit on.
This was a new local socket server, not the historical Codespace or any external
database. Build options and source checksum are in `PG18_REPLAY_RESULT.json`.

All 32 original correctness test instances passed on 18.4. Ten additional
diagnostic instances also completed as expected; these explicitly demonstrate
replay degradation and **are not performance passes**.

Each serial probe has 3 warmups and 30 samples, with 8000 unrelated synthetic
background rows and ANALYZE. Extra root history is FAILED AUTHORIZATION data,
so it does not alter confirmed budgets. Latencies are whole money.create replay
calls including commit; CPU is calling-thread CPU, not server/application-wide
CPU. There is no concurrent load, ABBA, cold-start or P95/P99 result.

| Root history rows | Base replay rows | Candidate replay rows | Base median ms | Candidate median ms | Base/candidate thread CPU ms |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 1 | 2 | 0.681 | 0.855 | 0.576 / 0.642 |
| 20 | 1 | 20 | 0.942 | 0.972 | 0.736 / 0.764 |
| 200 | 1 | 200 | 0.749 | 2.662 | 0.601 / 2.066 |
| 2000 | 1 | 2000 | 0.687 | 18.959 | 0.586 / 15.481 |

Small-history timing differences are not statistically qualified. The decisive
finding is that a same-key replay changes from one-row lookup to whole-history
ORM materialization and locking, although both paths still issue two SELECTs.
EXPLAIN ANALYZE shows base `Index Scan -> LockRows`; candidate uses `BitmapOr ->
Bitmap Heap Scan -> Sort -> LockRows`. At 2000 rows the observed top-level shared
buffer hits are 4 vs 2050, with executor times 0.016 vs 2.258 ms. Full plans and
all timing samples are preserved in the JSON; plans are not inferred from text.

A separate two-session witness locks only the AUTH row, without the root.
Base CAPTURE replay returns in 1.875 ms; candidate hits the configured 150 ms
lock timeout (SQLSTATE 55P03, measured 152.592 ms). After rollback/unlock both
recover correctly. This proves a new row-lock dependency, **not** an observed
production deadlock or evidence that existing root-first writers use this
schedule. The history-cardinality regression alone is sufficient to reject
this candidate's unconditional-OR replay shape.

Reproduce probes after the original suite on an isolated PostgreSQL 18.4 socket:

```sh
MONEY_READ_TEST_URL='postgresql+psycopg://postgres@/postgres?host=/tmp/go-money-pg18-socket&port=55440' \
MONEY_REPLAY_OUTPUT=/tmp/go-money-pg18-probes \
python -m pytest ci/money_locked_reads/test_correctness.py ci/money_locked_reads/test_replay_cost.py -q -s
```

A follow-up design must preserve the one-row idempotent replay path, including
conflicts, and only load history on a genuinely new movement. It must retain
the independent root statement, global key semantics and all guards. No revised
business implementation is included in this evidence-only follow-up.
