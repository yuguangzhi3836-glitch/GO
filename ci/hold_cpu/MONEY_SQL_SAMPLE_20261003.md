# Money SQL sampling — 2026-10-03

Diagnostic only. Draft #366 remains HOLD; no merge, deployment, ABBA PASS or performance-win claim. This batch-aware run supersedes the initial timing table; the initial raw run remains archived separately.

## Identity and scope

- Original Codespace: literate-winner-vpqqjgwvpjprcp7gw; PostgreSQL 18.4 (Debian 18.4-1.pgdg13+1).
- Historical application worktree HEAD: 13a08ec261cc1618b7cada5a2b64bd438b848621; application tree: 6570b66bc977f89c0311d67bdc6b721cd70d4e09. Tracked application diff was empty.
- Collector base: 019b6cc8dcaafd87c75ffad477bdc2f0cfe56c2e; runner SHA256: d91f91d02af48c1ce0c9851e119f5951a744706952765ffbf601b6461ef008a9.
- Python 3.12.3, SQLAlchemy 2.1.1, psycopg 3.3.6; 4 CPUs.
- Reconstructed synthetic RIDE_ORDER fixture: 3 warmup pairs (15 calls retained) then 20 measured pairs (100 calls / 400 SQLAlchemy cursor events). Serial; pool size 1, overflow 0.
- Real service.create -> create_in_session, original guards and lock order, independent commit for each successful call. Conflict exits with rollback.
- Valid collector, one complete lease per call, no cursor/transaction errors. Every pair asserts identical replay result, exactly two confirmed movements, two balanced ledger rows, one fulfillment event and expected fulfillment state.

## Per-call cost

All values are milliseconds. SQL is client cursor time, not PostgreSQL execution-only time. Counts (including raw sql_per_call) mean SQLAlchemy cursor events. CAPTURE has 9 events but 10 parameter-set executions: its ledger executemany event contains 2 sets. Across 100 measured calls there are 400 events and 420 parameter sets. These are not measured wire round trips. Transaction includes commit/rollback and pool reset. Lease is checkout through checkin. Wall is entire service.create wrapper.

| Scenario | Calls | Cursor events/call | SQL mean | Transaction mean | Lease mean | Lease p95 | Wall mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| fresh_AUTH | 20 | 5 | 1.9526 | 0.8589 | 4.0912 | 4.4841 | 4.3956 |
| fresh_CAPTURE | 20 | 9 | 3.5120 | 0.9409 | 6.6903 | 7.8858 | 6.9997 |
| replay_AUTH | 20 | 2 | 0.8861 | 0.9011 | 2.3019 | 2.8039 | 2.6095 |
| replay_CAPTURE | 20 | 2 | 0.9163 | 0.8259 | 2.2520 | 2.6648 | 2.5647 |
| conflict | 20 | 2 | 0.8933 | 0.3582 | 1.7140 | 1.8937 | 2.0029 |

## Ordered SQL cost

| Scenario | Order | Statement role | Mean ms | p95 ms |
|---|---:|---|---:|---:|
| fresh_AUTH | 1 | Root intent FOR UPDATE | 0.5410 | 0.5885 |
| fresh_AUTH | 2 | Idempotency key FOR UPDATE | 0.3607 | 0.3973 |
| fresh_AUTH | 3 | Credit source guard | 0.3197 | 0.3514 |
| fresh_AUTH | 4 | Movement history FOR UPDATE | 0.3436 | 0.3786 |
| fresh_AUTH | 5 | Movement INSERT | 0.3878 | 0.4256 |
| fresh_CAPTURE | 1 | Root intent FOR UPDATE | 0.5265 | 0.5674 |
| fresh_CAPTURE | 2 | Idempotency key FOR UPDATE | 0.3508 | 0.3939 |
| fresh_CAPTURE | 3 | Credit source guard | 0.3190 | 0.3666 |
| fresh_CAPTURE | 4 | Movement history FOR UPDATE | 0.3763 | 0.3900 |
| fresh_CAPTURE | 5 | Fulfillment FOR UPDATE | 0.3694 | 0.4015 |
| fresh_CAPTURE | 6 | Ledger INSERT (executemany, 2 parameter sets) | 0.5237 | 0.6933 |
| fresh_CAPTURE | 7 | Movement INSERT | 0.3664 | 0.4412 |
| fresh_CAPTURE | 8 | Fulfillment event INSERT | 0.3127 | 0.3732 |
| fresh_CAPTURE | 9 | Fulfillment UPDATE | 0.3672 | 0.4256 |
| replay_AUTH | 1 | Root intent FOR UPDATE | 0.5265 | 0.5830 |
| replay_AUTH | 2 | Idempotency key FOR UPDATE | 0.3595 | 0.3864 |
| replay_CAPTURE | 1 | Root intent FOR UPDATE | 0.5423 | 0.6424 |
| replay_CAPTURE | 2 | Idempotency key FOR UPDATE | 0.3740 | 0.4427 |
| conflict | 1 | Root intent FOR UPDATE | 0.5327 | 0.5849 |
| conflict | 2 | Idempotency key FOR UPDATE | 0.3606 | 0.4058 |

## Interpretation

The root intent lock is the slowest read in both fresh paths. CAPTURE ledger insertion is also a leading cost. Neither is proven redundant: root serialization protects the money graph, and the two ledger rows use one executemany event with two parameter sets. This does not prove one SQL statement or one network round trip.

See the ordered cost table for credit source guard timing. It is not the dominant measured statement. Its absence check still protects source reservation; no safe elimination was demonstrated. Root/key/history/fulfillment reads retain their original snapshots and locks.

No business SQL was removed. A subsequent optimization needs a semantically safe candidate and comparable data/concurrency evidence; these samples cannot justify deleting a guard, combining locked snapshots, or merging AUTH/CAPTURE commits.

## Dataset and schema limitations

- Final row counts: {"catalog_credit_source": 0, "omnichannel_ledger_entry": 46, "omnichannel_money_movement": 46, "omnichannel_payment_intent": 23, "order_supplier_fulfillment": 23, "order_supplier_fulfillment_event": 23}.
- Six tables were created from historical ORM metadata, not full Alembic migrations. This schema already contains ix_catalog_credit_source_payment_intent_id. It must not be presented as the historical deployed schema or evidence for the separate index candidate.
- The source table is empty. Its post-sampling EXPLAIN uses an Index Scan with zero rows (raw JSON retained). This says nothing about original cardinality, index absence, production distribution, or contention.
- No historical data was restored; this does not reproduce the original 100-actor load. No ABBA comparison or before/after improvement was measured.
- Cursor timing excludes fetch/materialization. It includes instrumentation overhead. Wall and lease include more application/driver work; the remainder must not be labelled CPU without profiling.
- Pool pre-ping runs before checkout and is outside cursor/lease hooks. Pure queue time is not measured and remains null.
- Raw evidence retains all call order/timings, warmups, exact SQL fingerprints, placeholder-only SQL catalog, indexes, EXPLAIN and versions. The SQL catalog omits binds; EXPLAIN contains only a synthetic fixture ID. No real business values or credentials are recorded.

## Reproduce in the same isolated Codespace

Use the existing labelled go-call-sql-pg-20261003 diagnostic container, bound only to 127.0.0.1:55436, and the historical unchanged worktree:

```sh
/workspaces/.go-capacity-venv/bin/python ci/hold_cpu/sample_money_sql.py --app-root /workspaces/GO-held-cpu-20261002 --output /tmp/money-sql-new-run.json
```

The runner checks application tree and tracked diff plus container label/binding, creates a unique schema and retains it for inspection. It does not run against HK or production. Do not overwrite this archived run with later samples.

Raw evidence SHA256: b6071cc197f2c4776b38406f7b3ba3da54993a6db33f8ac117f6d19d878bf6c7.
