# New-write source guard: one index candidate

Decision: GO for review of the index; NO-GO for performance acceptance or rollout.
Base: `05b108cc63b008aad4da732ac97c7e453cf59220` (main rechecked 2026-10-03).
PR #372's rejected history/CTE implementations are not included. The money
service and all three business guards are byte-for-byte main. Changes are one
nonunique model index and migration `0135_credit_source_intent_index`.

## What is actually removable?

For fresh RIDE AUTHORIZATION + full CAPTURE, main executes 9 SELECTs and 5 DML
statements, with AUTH and CAPTURE committed separately. A successful replay
executes 2 SELECTs. The two successful replays plus an amount-conflict replay in
the historical five-call slice therefore still produce 20 SQL statements.

| Read | Fresh AUTH / CAP count | Decision |
| --- | --- | --- |
| Root intent FOR UPDATE | 1 / 1 | Keep as an independent statement: subsequent reads need a post-wait READ COMMITTED snapshot. |
| Global idempotency key FOR UPDATE | 1 / 1 | Keep; one-row hit returns before guards/history and checks root/type/amount/parent. |
| Supplier and cash guards | 0 / 0 for RIDE | Removing Python calls would save no RTT. Other business types still need them. |
| Credit source by payment_intent_id | 1 / 1 | Keep the reservation check; remove its unindexed full-table scan. |
| Locked movement history | 1 / 1 | Keep miss-only history for cumulative and parent budgets. |
| Fulfillment FOR UPDATE | 0 / 1 | Keep full-capture state/event atomicity. |

There is no proven safely removable RTT in this path. Source lookup is an
existence test but changing it to EXISTS without an index still scans the
entire table on the common miss. Skipping it by RIDE business type would weaken
the existing invariant. Combining it with the root statement risks a stale
snapshot after a lock wait. Combining idempotency/history was already rejected.

## PostgreSQL 18.4 local evidence

`results/cost-*.json` retain samples, exact SQL catalogue and EXPLAIN ANALYZE
BUFFERS plans. Synthetic source rows are unrelated to the new RIDE intents;
these sizes do not claim to represent the diagnostic or live database.
Each size uses four serial blocks (unindexed/indexed/indexed/unindexed), each
with 3 warmups + 10 measured pairs. Roots are prepared outside timing. Pair
wall time includes both durable commits. Cursor timing excludes ORM work and
commit latency. No concurrent workload, external database, or pressure test.

Final run medians in milliseconds, unindexed -> indexed:

| Source rows | Two source queries | AUTH + CAP wall | Calling thread CPU | One CAP replay wall |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 0.177 -> 0.230 | 4.820 -> 5.593 | 3.907 -> 4.341 | 0.871 -> 1.026 |
| 1,000 | 0.378 -> 0.227 | 5.359 -> 4.667 | 4.185 -> 3.718 | 0.940 -> 0.855 |
| 100,000 | 11.189 -> 0.268 | 17.197 -> 5.801 | 4.838 -> 4.463 | 1.085 -> 1.059 |

At 100,000 rows, each negative lookup changes Seq Scan (100,000 filtered rows,
1,136 shared-hit buffers) to Index Scan (3 shared-hit buffers). The measured
two-query saving is 10.921 ms per AUTH/CAP pair in this synthetic regime;
100 equivalent pairs would budget about 1.09 seconds of summed cursor time,
not 1.09 seconds of concurrent wall time or queue reduction. At small tables
fixed overhead/noise dominates; no reliable end-to-end benefit is established.
A preliminary run showed the same scale effect (100k pair 16.076 -> 4.921 ms),
but small-table timings varied. No P95, throughput or production PASS is claimed.

Replay keeps two statements, one returned movement row and no source/history
read. Its timings vary in both directions, so this probe does not establish a
replay latency non-regression gate. It establishes unchanged query work. An
index adds storage and source-insert maintenance; source-conversion throughput
was not measured. Neither live source cardinality nor #366's per-statement
source cost was obtained. Do not attribute #366's 9.310s money SQL time to this
scan without that evidence, or extrapolate its 228.727s queue time linearly.

## Safety and migration

34 PostgreSQL tests passed: the existing 16 safety cases in both index modes,
plus migration upgrade/downgrade in both modes. They cover concurrent replay,
different amount/type/root/parent conflicts, global-key insert races with
rollback and connection reuse, parent budgets, overspend/release races, credit
reservation visibility after waiting on root, ledger/fulfillment atomicity,
same-session rollback, backend disconnects and process exit before/after
AUTH/CAP commits. Six existing SQLite finance/parent-budget tests also passed.
The serial probe reports 3 passed/3 intentionally skipped candidate duplicates.

The index changes neither SQL predicates nor application lock order. It is
nonunique: multiple capture sources may share an intent. An alternate scan
order is harmless for this guard because it only tests whether any source
exists; business amounts are not read from the arbitrary first row. MVCC,
post-root-lock visibility, unique-key enforcement, history locking and parent
validation stay intact. No connection is retained across AUTH/CAP commits.
Existing committed AUTH recovery and commit-ack ambiguity/replay behavior
remain; an index does not solve or alter those failure semantics.

Migration uses ordinary transactional CREATE INDEX, which blocks writes to
the source table while building. It must not be automatically applied to a
busy live table. Schedule a maintenance window or separately review an online
index build. Only isolated migration operations were tested, not a full live
upgrade or a full migration-chain replay. Downgrade drops only the index.

## Reproduce

Use an explicitly isolated PostgreSQL 18.4 Unix socket; the fixture rejects TCP
and sockets outside `/tmp/go-money-*`, creates a fresh schema per case, and
drops only that schema afterwards.

```sh
export PYTHONPATH=application/src
export MONEY_READ_TEST_URL='postgresql+psycopg://postgres@/postgres?host=/tmp/go-money-r2-socket&port=55441'
python -m pytest -q ci/money_new_write/test_correctness.py ci/money_new_write/test_migration.py
MONEY_NEW_OUTPUT=ci/money_new_write/results python -m pytest -q -s ci/money_new_write/test_cost.py
cd application
PYTHONPATH=src python -m pytest -q tests/test_depth12_parent_money_budget.py tests/test_unified_money_movement_finance_close.py
```
