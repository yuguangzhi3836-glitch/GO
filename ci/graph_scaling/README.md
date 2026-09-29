# Payment CPU breakdown and bounded history validation

This is the first implementation after the 2026-09-29 expert screening. The application change is confined to `_payment_state` in `order_supplier_fulfillment.py`: validate parent edges as before, accumulate each relevant amount once by parent ID, then check each parent's budget. No query, lock, commit, money truth or recovery boundary changes.

`CAPTURE + RELEASE` remain limited by their own authorization; `REFUND + COMPENSATION` remain limited by their own capture. Global root budgets, binding, payer/payee, currency, positive integer amount, state and parent type validation remain. Payout handling is unchanged. Temporary totals are scoped to this call and never cached across transactions.

## Evidence and acceptance scope

- 58 local tests pass: 24 new pure graph tests, one stored 2,002-movement graph test, 17 existing supplier money projection tests and 16 transaction-read tests. Local database-backed cases use SQLite; PostgreSQL must be verified in isolated CI.
- The new tests join the existing PostgreSQL regression job. The standard formal staircase is unchanged, including complete actors, cold processes, pool 5 / overflow 0, P95 5000 ms, P99 10000 ms, errors 0 and SQL reconciliation.
- Independent transaction architecture review found no equivalence blocker. This is an AI review, not a formal C13/C14 receipt.
- For 4,000 movements, deterministic row visits fall from 16,036,000 to 36,000. For 2,000 rows, 4,018,000 to 18,000. New work is linear in rows. The bounded-work test fails under the old nested scan.
- `graph-component-measurement.json` contains local, same-process component timings using prebuilt plain row objects, four samples per label after both functions have run. Counted-list traversal is measured separately, outside timing. At 4,000 rows the local median CPU is 0.647671 s before and 0.002860 s after; at the ordinary two-row case both are about 0.000029 s. These are **not** transaction P95 or whole-application CPU gains.
- Reproduce the component comparison with `python ci/graph_scaling/measure.py` in an application test environment with the pinned baseline commit available. The generated JSON is a local component result; formal capacity acceptance remains separate.
- `cpu_candidate.json` remains unarmed. There is no evidence this history repair alone reduces full standard RIDE CPU by 20% and P95 by 15%; the full-transaction ABBA must not claim that budget passed.

## Existing granular payment evidence

`payment-cpu-breakdown.json` reuses the verified aea10be artifact 11017750990 (SHA256 `44cbee7a2c50fce329e7798637733be668f5b14209f10f0bf9b4dc643964a5b6`). Two instrumented service processes complete 100 actors with 11,400 successful cursor statements and 10.518006 CPU seconds. This is the existing service-boundary diagnostic, not the highly perturbing full-thread Yappi run. Nested service CPU totals overlap and cannot be summed. SQL counts are attributed to the innermost tracked service; money.create includes checkout calls and concurrent replays outside checkout.

| Scope | Calls | Inclusive calling-thread CPU seconds | Direct cursor statements |
|---|---:|---:|---:|
| checkout_contract | 100 | 4.196803 | 1100 |
| create_intent | 100 | 0.805661 | 1200 |
| select_channel | 100 | 0.179528 | 200 |
| execute | 100 | 0.374949 | 500 |
| simulate_result | 100 | 0.493626 | 800 |
| money.create (including replays) | 500 | 1.661992 | 2000 |
| supplier.record_supplier_fact | 100 | 0.898943 | 1300 |

Money and ride creation also show substantial concurrent pool wait, but these summed wall durations are not CPU. Existing connection/server same-window evidence must be kept distinct from this service breakdown. Removing one supplier query cannot justify a 20% full-application budget from these observations.

The existing diagnostic now separates calling contexts (checkout versus root/replay), records exclusive calling-thread CPU after subtracting nested tracked methods, and records cursor/commit calling-thread CPU separately. Three qualification tests cover nested arithmetic, exception preservation and child-thread attribution. It runs only in the diagnostic step; the normal staircase is unchanged. Observer overhead remains included, and these measurements cannot replace an uninstrumented candidate comparison. The present commit does not widen connection pools or adopt speculative payment/locking rewrites.
