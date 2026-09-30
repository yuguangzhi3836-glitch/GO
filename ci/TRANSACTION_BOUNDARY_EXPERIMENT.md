# Transaction-boundary candidate — rejected; original application restored

## Verified decision — 2026-09-30

Candidate `4048cbe64d0551130618d5d028204f770143aab7` is **NOT ADOPTED**.
Restore exact original application `6570b66bc977f89c0311d67bdc6b721cd70d4e09`.
Keep all three implementation commits and candidate evidence in history. Draft #279 remains open.

[ABBA run 36665715345](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36665715345) is **INVALID_COMPARISON_NOT_EVALUATED**: its fourth baseline continued create-order batch at requested100 achieved actual peak99. The full transaction main measurements did complete all four rounds, at actual20/100 overlap, and fail both screening targets. These complete main measurements are useful rejection evidence, not a valid complete ABBA acceptance. No retry was selected to hide the shortfall.

| Main full transactions, 100 actors; two-round medians | Baseline | Candidate | Reduction |
|---|---:|---:|---:|
| Application CPU seconds | 10.440037 | 9.758867 | 6.52% |
| Whole worker lifetime CPU seconds | 18.027909 | 17.332227 | 3.86% |
| P95 ms | 7895.358639 | 7522.084423 | 4.73% |
| P99 ms | 7964.721595 | 7575.241660 | 4.89% |

Required: application CPU reduction20%, lifetime CPU20%, P95 reduction15%; P99 no regression; RSS<=+10%. Measured RSS ratio1.004701. **Screening goals failed; no adoption.**

Safety: 24 new PostgreSQL tests PASS, zero skips/failures/errors; frozen250 PostgreSQL regressions PASS, zero skips/failures/errors. Every main round passed13 correctness/recovery scenarios. Formal raw230-file manifest and ABBA3256-file manifest verified, plus all three ZIP digests. Four normal rounds were independently recomputed from raw durations, process counters, exact overlap and balanced ledger facts. The supplementary batch shortfall is retained, not corrected or excluded to manufacture a complete comparison.

### Original frozen formal gate

[Run36665714654](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36665714654), 2vCPU AMD EPYC7763, two service workers, pool5/overflow0:

| Concurrent full transactions | P95 ms | P99 ms | Errors | Gate |
|---:|---:|---:|---:|---|
| 20 | 2382.408401 | 2382.657274 | 0 | PASS |
| 100 | 7856.219058 | 7922.968890 | 0 | FAIL |

P95<=5000ms remains mandatory. No250/500/1000 tier ran. 120 final orders each had exactly one attempt, two balanced ledger entries and capture/debit/credit16800. This is service/route synthetic measurement, omitting HTTP/auth/network and real suppliers/PSPs.

### Same-machine cold and continued phase measurements

Below are medians across both rounds per variant; continued uses three subsequent bursts per round, not a soak. Values are P95/P99 milliseconds and application process CPU seconds. These measurements are supplementary to the failed main screening. The entire baseline100-create continued cell is marked INVALID because one of its six batches reached99/100; its value is not silently dropped. Other cells describe verified individual raw batches, not a valid whole-run acceptance. Phase percentiles cannot be added.

| Actors | Operation | Mode | Baseline P95 / P99 / CPU s | Candidate P95 / P99 / CPU s |
|---:|---|---|---:|---:|
| 20 | full_transaction | Cold | 2265.948 / 2275.848 / 3.202 | 2193.573 / 2197.927 / 3.104 |
| 20 | full_transaction | Continued | 1337.849 / 1358.047 / 1.592 | 1221.602 / 1233.568 / 1.428 |
| 20 | create_order | Cold | 1024.957 / 1028.409 / 1.792 | 960.248 / 961.002 / 1.710 |
| 20 | create_order | Continued | 195.837 / 196.838 / 0.247 | 188.915 / 189.991 / 0.235 |
| 20 | payment_confirm | Cold | 1472.325 / 1474.461 / 2.259 | 1528.557 / 1529.222 / 2.135 |
| 20 | payment_confirm | Continued | 590.280 / 594.442 / 0.683 | 528.912 / 532.062 / 0.593 |
| 20 | order_query | Cold | 871.676 / 872.280 / 1.592 | 884.240 / 885.624 / 1.579 |
| 20 | order_query | Continued | 71.680 / 72.140 / 0.091 | 70.822 / 70.999 / 0.090 |
| 100 | full_transaction | Cold | 7977.918 / 8019.130 / 10.097 | 7491.013 / 7556.568 / 9.472 |
| 100 | full_transaction | Continued | 6681.416 / 6773.645 / 8.077 | 6286.624 / 6369.231 / 7.463 |
| 100 | create_order | Cold | 1753.161 / 1807.952 / 2.795 | 1789.751 / 1809.257 / 2.727 |
| 100 | create_order | Continued | INVALID (peak99/100) | 853.014 / 870.876 / 1.238 |
| 100 | payment_confirm | Cold | 3753.974 / 3853.011 / 5.108 | 3516.483 / 3656.812 / 4.699 |
| 100 | payment_confirm | Continued | 2973.805 / 3107.209 / 3.551 | 2712.096 / 2754.635 / 3.086 |
| 100 | order_query | Cold | 1126.562 / 1145.765 / 1.943 | 1152.457 / 1165.098 / 1.971 |
| 100 | order_query | Continued | 342.592 / 355.849 / 0.463 | 338.140 / 355.432 / 0.460 |

### Separate instrumented database diagnostics (incomplete ABBA)

Only rounds1baseline,2candidate,3candidate reached diagnostics; round4 stopped on the journey shortfall. These are diagnostic observations, **not an ABBA estimate of wait reduction**. Queue/SQL/hold sums overlap across threads and are not end-to-end latency or database-server CPU; SQL wall includes transport and scheduling. Cold/continued phase CPU above is uninstrumented; diagnostic collection covers separately launched cold full transactions.

| Round | Actors | SQL executions | Connection acquisitions | Pool queue sum s | Connection hold sum s | SQL wall sum s |
|---|---:|---:|---:|---:|---:|---:|
| 1 baseline | 20 | 2280 | 420 | 16.954 | 13.402 | 9.832 |
| 1 baseline | 100 | 11400 | 2100 | 637.836 | 69.458 | 50.611 |
| 2 candidate | 20 | 2240 | 360 | 14.975 | 13.835 | 10.223 |
| 2 candidate | 100 | 11200 | 1800 | 576.822 | 66.099 | 49.144 |
| 3 candidate | 20 | 2240 | 360 | 14.317 | 12.800 | 9.293 |
| 3 candidate | 100 | 11200 | 1800 | 582.700 | 67.333 | 49.807 |

Connection acquisitions fell21→18 per actor as designed; measured CPU savings still miss the target. Baseline and candidate retain the dominant service CPU and database-wait work. Do not infer that extending transaction scope further is safe or that merely increasing the pool solves this.

### Hardware step and evidence

The [four-vCPU driver](four_vcpu/README.md) is prepared, with hardware/quota guards and an immutable detached candidate checkout. Its38 combined guard/harness tests passed locally. **4vCPU has not run: execution resource pending.** Repository runner settings on2026-09-30 show no configured self-hosted runners; current capacity workflows use2vCPU. An actual approved isolated4vCPU x86_64 runner label is needed. No label, capacity benefit, cost, purchase, registration or permission grant is invented. Original2vCPU remainsFAIL regardless of future4vCPU results.

- ABBA artifact11077515662: `d310f0ae7d2256202e2a4895c68d76695d4b61f7315c949f7adc8c2782c0fd67`
- Formal artifact11076950329: `7fb35272de968598e6e9bf716df4fd301df5cf70b3cfddeb3f5cac79b908b34c`
- Journey artifact11076003613: `2be563629dbb10ab06a74b8f1da487c3cfd0d4e39662e311e9970bf06b298fca`

Standalone journey36665714685 verified960 orders, but is a different runner and is not used to calculate optimization speedup. C14→C13 remain pending; funding screenshot does not constitute an API probe or review approval.

---


Scope: Draft PR #279 only. No merge, deployment, Hong Kong, supplier or real
payment access. Frozen baseline: 059ebec3ab379099ef258effc3ab0a9833d52c35,
application 6570b66bc977f89c0311d67bdc6b721cd70d4e09.

## Independently revertible implementation commits

1. `6bed2daff5f7e1f1db4d7531d8825cda772de711`: local RIDE order, source,
   evidence and successful API receipt commit together after the independent
   durable claim. Pre-commit rollback can release the claim; ambiguous commit
   and abrupt process death retain it. Generic/Flight recovery is unchanged.
2. `05fe1f2f47850a814e0684c4ff1f5c3da88c012e`: consolidate RIDE order checks,
   payment intent/root creation and deadline confirmation in one local transaction.
   RIDE public intent creation uses the same order-first locking sequence.
   Payment execution, authorization and capture remain independently durable.
3. `0e1506fb95413a12998128080da346b95a1e88a9`: one committed database snapshot
   for confirmed RIDE authorization/capture replay; preserve key/amount/type/parent
   conflicts. No financial result cache. Misses, non-confirmed rows, rental deposit
   scope and caller-owned verified-external transactions retain the locked path.
   First-operation lookup overhead must be included in the measured comparison.

The following qualification/binding commit adds real driver disconnect probes
and a PostgreSQL-only full concurrent-checkout test; it is separate from runtime
changes. Final application: `b77840d31f0e31b046d8f3359c35630c75b8a02d`.

## Local evidence (not PostgreSQL capacity proof)

- Existing frozen regression selection: 248 passed, 2 PostgreSQL-specific skips.
- New tests: 22 passed, 2 PostgreSQL-only concurrency tests pending remotely.
- Harness tests: 34 passed.
- Real subprocess exits on both sides of order and payment-root commits.
- Real DBAPI connection closure before/after order commit, plus ambiguous-ack
  injection. Before-commit loss leaves no order and a retained claim; after-commit
  loss leaves one order plus a replayable success receipt.
- SQLite full payment-transition concurrency exposed a fulfillment uniqueness
  race: SQLite does not implement the existing FOR UPDATE semantics. It is not
  accepted as concurrent-payment proof. The new root-preparation concurrency test
  passes locally; the full checkout test is mandatory, with zero skips, on PostgreSQL.
- Cold import inspection: zero configured ORM mappers and zero pool connections.

## Measurement and decision

Run original/candidate/candidate/original on one runner with fresh per-round
schemas/processes, unchanged 2 workers, pool5/overflow0 and 5ms switch interval.
Keep 20 then 100 concurrent full actors, cold plus all continued journey batches.
Run separate instrumented 20/100 diagnostics after each uninstrumented round on
the same machine. Diagnostic phase timings, SQL and pool waits are not acceptance
latencies or additive percentiles. Diagnostic adapter adds labels for the new
session-owned entry points; no frozen formal harness file is edited.

Adoption requires app CPU -20%, lifetime CPU -20%, P95 -15%, no P99 regression,
RSS growth <=10%, all correctness/regression tests, then the original formal
100-actor P95<=5000ms/P99<=10000ms gate. No higher load before that formal gate.
Planned connection-acquisition reduction 21->18 is a design estimate, not a
measured result. Hardware expansion is a separate 4-vCPU comparison, only if the
original configuration fails; it cannot re-label the original gate as passed.

Frozen SHA256:
- run.py: e274bc3cb2b114cd2ed9e024c30a5ebb71d1b3a4e26ba27a5c521b7d56889a5c
- ride_workload.py: b5a97b55cd6815534b1844c99ba9073dafe1c534be57d00d2e10d0520e665d32
- formal workflow: 160720754942621bdff87dbf2a96e90395444567c7c932d3bb799d0622160330

## Review-provider funding update

User-provided email screenshot dated 2026-09-30 11:32 Asia/Shanghai reports a
USD 113 charge to fund GOAI OpenAI API credits. This is funding evidence only;
the configured review environment has not yet been probed successfully. Do not
retain "credit exhausted" as a freshly verified current fact, or infer C14 PASS.
C14 and C13 remain pending the fixed final candidate and their own actual results.

## Measurement-tool follow-up — 2026-09-30

Restoration run36668874513 independently verified:250 PostgreSQL regressions PASS,
13 scenarios PASS,20P95/P99=1896.006680/1900.873421ms,100P95/P99=6348.505668/6384.859837ms,
zero errors and balanced money facts. Original configuration still FAIL; this is
a different runner and cannot be compared with rejected-candidate7.86s as speedup.
Normal artifact11076823798 SHA2563ff81145defec1074d9ec3ff70ca53a01101076be7dec36e468006cf15a701fd.

The supplementary journey harness previously made every actor poll a filesystem
release marker, with different markers for the two processes. Replace these with
one shared marker watched once per process and a local Event broadcast after all
threads are ready. This reduces release skew and harness polling overhead; it does
not guarantee real100 overlap for fast operations. Actual overlap remains strictly
verified from each request's unchanged start/end clock around its operation. No
completion hold, pre-admission timestamp, discarded batch, automatic retry or
relaxed concurrency threshold is introduced. Failed coordinator release invokes
no application operation.

Standalone journey workflow now calls the existing strict raw-evidence verifier:
a99/100 batch fails the workflow, even if measurement collection itself succeeded.
All40 local harness/guard tests pass. Fresh PostgreSQL journey validation is required;
no historical invalid comparison is repaired retroactively. The4-vCPU driver copies
this identical harness into its fixed candidate checkout, so both baseline and
candidate use the same new measurement definition. Frozen formal harness, baseline
application and5-second gate remain unchanged. Four-vCPU run36668874486 is SKIPPED
because the required runner configuration is absent; no hardware result exists.
