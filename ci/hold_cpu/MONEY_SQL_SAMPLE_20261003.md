# Money SQL sampling — 2026-10-03

Diagnostic only. Draft #366 remains HOLD; no merge, deployment, ABBA PASS or performance-win claim.

## Identity and scope

- Original Codespace: literate-winner-vpqqjgwvpjprcp7gw; PostgreSQL 18.4 (Debian 18.4-1.pgdg13+1).
- Historical application worktree HEAD: 13a08ec261cc1618b7cada5a2b64bd438b848621; application tree: 6570b66bc977f89c0311d67bdc6b721cd70d4e09. Tracked application diff was empty.
- Collector base: bbe7be96bcb1f0a1c14f950a34efdce102114cb7; runner SHA256: baccb6e45205b2b3fcb8eb455d5c1beb667b1c58d6754c499b5684bfb99e74df.
- Python 3.12.3, SQLAlchemy 2.1.1, psycopg 3.3.6; 4 CPUs.
- Reconstructed synthetic RIDE_ORDER fixture: 3 warmup pairs (15 calls retained) then 20 measured pairs (100 calls / 400 SQL cursor executions). Serial; pool size 1, overflow 0.
- Real service.create -> create_in_session, original guards and lock order, independent commit for each successful call. Conflict exits with rollback.
- Valid collector, one complete lease per call, no cursor/transaction errors. Every pair asserts identical replay result, exactly two confirmed movements, two balanced ledger rows, one fulfillment event and expected fulfillment state.

## Per-call cost

All values are milliseconds. SQL is client cursor time, not PostgreSQL execution-only time. Transaction includes commit/rollback and pool reset. Lease is checkout through checkin. Wall is entire service.create wrapper.

| Scenario | Calls | SQL/call | SQL mean | Transaction mean | Lease mean | Lease p95 | Wall mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| fresh_AUTH | 20 | 5 | 1.9583 | 0.8661 | 4.0928 | 4.4493 | 4.3923 |
| fresh_CAPTURE | 20 | 9 | 3.4344 | 0.9634 | 6.6437 | 7.5620 | 6.9434 |
| replay_AUTH | 20 | 2 | 0.8785 | 0.8238 | 2.2069 | 2.3685 | 2.5137 |
| replay_CAPTURE | 20 | 2 | 0.8662 | 0.8223 | 2.1677 | 2.2931 | 2.4616 |
| conflict | 20 | 2 | 0.8527 | 0.3950 | 1.6929 | 1.7979 | 1.9798 |

## Ordered SQL cost

| Scenario | Order | Statement role | Mean ms | p95 ms |
|---|---:|---|---:|---:|
| fresh_AUTH | 1 | Root intent FOR UPDATE | 0.5721 | 0.5741 |
| fresh_AUTH | 2 | Idempotency key FOR UPDATE | 0.3513 | 0.4011 |
| fresh_AUTH | 3 | Credit source guard | 0.3111 | 0.3499 |
| fresh_AUTH | 4 | Movement history FOR UPDATE | 0.3381 | 0.3778 |
| fresh_AUTH | 5 | Movement INSERT | 0.3857 | 0.4275 |
| fresh_CAPTURE | 1 | Root intent FOR UPDATE | 0.5244 | 0.5613 |
| fresh_CAPTURE | 2 | Idempotency key FOR UPDATE | 0.3439 | 0.3808 |
| fresh_CAPTURE | 3 | Credit source guard | 0.2993 | 0.3190 |
| fresh_CAPTURE | 4 | Movement history FOR UPDATE | 0.3476 | 0.3751 |
| fresh_CAPTURE | 5 | Fulfillment FOR UPDATE | 0.3580 | 0.4036 |
| fresh_CAPTURE | 6 | Ledger INSERT (2 rows, one cursor execution) | 0.5405 | 0.6763 |
| fresh_CAPTURE | 7 | Movement INSERT | 0.3655 | 0.4029 |
| fresh_CAPTURE | 8 | Fulfillment event INSERT | 0.2943 | 0.3277 |
| fresh_CAPTURE | 9 | Fulfillment UPDATE | 0.3610 | 0.3975 |
| replay_AUTH | 1 | Root intent FOR UPDATE | 0.5231 | 0.5650 |
| replay_AUTH | 2 | Idempotency key FOR UPDATE | 0.3554 | 0.4000 |
| replay_CAPTURE | 1 | Root intent FOR UPDATE | 0.5131 | 0.5498 |
| replay_CAPTURE | 2 | Idempotency key FOR UPDATE | 0.3530 | 0.3783 |
| conflict | 1 | Root intent FOR UPDATE | 0.5021 | 0.5436 |
| conflict | 2 | Idempotency key FOR UPDATE | 0.3506 | 0.3727 |

## Interpretation

The root intent lock is the slowest read in both fresh paths. CAPTURE ledger insertion is also a leading cost. Neither is proven redundant: root serialization protects the money graph, and the two ledger rows already use a single cursor execution.

The credit source guard is about 0.31 ms for fresh AUTH and 0.29 ms for fresh CAPTURE in this fixture. It is not the dominant measured statement. Its absence check still protects source reservation; no safe elimination was demonstrated. Root/key/history/fulfillment reads retain their original snapshots and locks.

No business SQL was removed. A subsequent optimization needs a semantically safe candidate and comparable data/concurrency evidence; these samples cannot justify deleting a guard, combining locked snapshots, or merging AUTH/CAPTURE commits.

## Dataset and schema limitations

- Final row counts: {"catalog_credit_source": 0, "omnichannel_ledger_entry": 46, "omnichannel_money_movement": 46, "omnichannel_payment_intent": 23, "order_supplier_fulfillment": 23, "order_supplier_fulfillment_event": 23}.
- Six tables were created from historical ORM metadata, not full Alembic migrations. This schema already contains ix_catalog_credit_source_payment_intent_id. It must not be presented as the historical deployed schema or evidence for the separate index candidate.
- The source table is empty. Its post-sampling EXPLAIN uses an Index Scan with zero rows (raw JSON retained). This says nothing about original cardinality, index absence, production distribution, or contention.
- No historical data was restored; this does not reproduce the original 100-actor load. No ABBA comparison or before/after improvement was measured.
- Cursor timing excludes fetch/materialization. It includes instrumentation overhead. Wall and lease include more application/driver work; the remainder must not be labelled CPU without profiling.
- Pool pre-ping runs before checkout and is outside cursor/lease hooks. Pure queue time is not measured and remains null.
- Raw evidence retains all call order/timings, warmups, exact SQL fingerprints, placeholder-only SQL catalog, indexes, EXPLAIN and versions. No bind values or credentials are recorded.

## Reproduce in the same isolated Codespace

Use the existing labelled go-call-sql-pg-20261003 diagnostic container, bound only to 127.0.0.1:55436, and the historical unchanged worktree:

```sh
/workspaces/.go-capacity-venv/bin/python ci/hold_cpu/sample_money_sql.py --app-root /workspaces/GO-held-cpu-20261002 --output /tmp/money-sql-new-run.json
```

The runner checks application tree and tracked diff plus container label/binding, creates a unique schema and retains it for inspection. It does not run against HK or production. Do not overwrite this archived run with later samples.

Raw evidence SHA256: 40a2279273e2df14cdae33fd704a29a4c08ff3f4d9ca451cd901ac30a2b8ac64.
