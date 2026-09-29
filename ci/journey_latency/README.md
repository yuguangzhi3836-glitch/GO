# Normal-operation latency supplement

Authorized 2026-09-29: retain the original 5-second baseline; independently measure
normal order creation, internal payment confirmation and order queries, distinguishing
process-cold requests from continued execution.

## Fixed boundaries

- Application tree remains `6570b66bc977f89c0311d67bdc6b721cd70d4e09`.
- `baseline.json` freezes the formal harness, workload and workflow byte hashes.
  Original P95 <= 5,000 ms, P99 <= 10,000 ms, correctness and SQL rules are unchanged.
- Separate diagnostic tiers: 20 and 100 callers, two processes, pool 5 / overflow 0.
  This does not authorize or pass the formal 250/500/1,000 tiers.
- Fresh worker pair for each operation at each tier. Batch 0 retains mapper and
  connection initialization; batches 1/2/3 reuse the exact processes, thread pools
  and engine pools. Every batch is retained; no discarded warmup.
- Process launch through import readiness is reported separately. Workers assert
  zero established pool connections and zero configured mappers before batch 0.
  Database/OS caches are **not cold**; this is not a machine-reboot benchmark.
- Three continued bursts are not a long-duration soak, production capacity or a
  normal traffic mix. Report per-batch distributions, actual observed overlap,
  and burst completions per second; do not call that sustained maximum throughput.

## What is timed

| Operation | Entry | Completion |
| --- | --- | --- |
| Normal create | Existing `mobility.rb` once, including Pydantic body construction and existing idempotency path | PAYMENT_PENDING, valid CNY 16800 order |
| Payment confirm | Existing `checkout_contract` once | Internal simulator payment confirmed, capture and fulfillment ID present, awaiting supplier |
| Order query | Existing `mobility.order` once | Completed order detail with correct identity, amount and currency |

Workers begin timing after the simultaneous-release barrier and before the service
call. All database pool/lock waiting inside that call remains timed. Thread setup,
caller synchronization, prior quote preparation, and fixture creation are outside
individual request timings. This is direct route/service execution: no HTTP,
authentication middleware, browser rendering, client network, real PSP or supplier.

The coordinator obtains the synthetic quote before create measurements. Each batch
creates new unique owners/orders; the same orders feed its payment and query batches.
Database history therefore grows between batches. Supplier confirmation and START /
COMPLETE fixture transitions occur explicitly outside query timing. The frozen full
ledger verifier checks **every** created order, both movements, balanced ledger,
one attempt, one supplier fact and completed Trips. An ownership-denial check runs
outside timing. Query data consists of one completed synthetic order per account;
this does not represent long personal order histories or all product verticals.

No replay/conflict injection belongs to normal operation timings. Those remain in
the original unmodified formal workload. Phase P95 values are not additive and this
supplement does not produce an end-to-end journey P95 or a new release SLO.

Run `python -m pytest ci/journey_latency/test_measure.py -q`, then in an authorized
isolated PostgreSQL CI environment run `python ci/journey_latency/measure.py`.
Evidence includes fixed source/tree identity, raw request start/end times, per-worker
startup/counters, per-batch P50/P95/P99, observed concurrency, ledger facts and hashes.
No application optimization or overall CPU/latency reduction is claimed.
