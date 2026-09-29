# Capacity projection experiment — 2026-09-29

**Final decision: REVERT.** Same-runner app CPU improved 9.07% and full-transaction
P95 improved 7.76%, below the 20%/15% targets. Restore the exact original
application; formal 100-actor P95 is still over 5 seconds. High-concurrency
acceptance is NOT achieved. Full evidence and cold/continued tables follow.

User direction: prioritize the high-concurrency failure. Draft PR #279 remains
the integration candidate. No merge, deployment, live payment or supplier access.

Baseline commit: `059ebec3ab379099ef258effc3ab0a9833d52c35`.
Baseline application tree: `6570b66bc977f89c0311d67bdc6b721cd70d4e09`.
Experimental application tree: `09f45b2db848f406edb72cdf265d2edf108d859e`.

## Hypothesis and scope

Reduce recurring ORM query construction and unused-column loading in the
payment, evidence verification, supplier-money projection and lifecycle paths.
The rejected payment-only query-reuse experiment is included as one component;
its earlier 6.88% CPU improvement does not qualify it for adoption. This combined
candidate requires its own measured decision. Nothing is accepted in advance.

Statement objects retain bind parameters, database reads, FOR UPDATE clauses,
ordering, predicates and existing transaction/commit boundaries. No business
facts, payer identities, clocks, locks or validation decisions are cached.
`load_only` keeps ORM session identity semantics and all fields used by the full
evidence-chain and money-graph checks. All graph nodes and chain links remain
checked; no history truncation or removal of safety/recovery work.

## Local qualification — not PostgreSQL capacity

The 68 existing relevant regressions and four new projection tests passed on
SQLite, plus 31 harness qualification tests. New tests cover unflushed session
tampering, chain validation without deferred-field queries, and money parent
integrity with large unused payloads. Local sequential 100-transaction ABBA CPU:
2.669386359 / 2.545566863 / 2.512696317 / 2.951782511 seconds. The median reduction
is approximately 10.02%, below the 20% goal; this is a discovery result only.
Packages differ from the CI runner (local SQLAlchemy 2.0.54 versus previous CI
2.1.1), so these absolute timings cannot be mixed with the PostgreSQL evidence.

An initial cProfile CPU-clock probe produced invalid thread accounting and is
excluded. The replacement Yappi discovery used native thread CPU accounting;
neither profile is an uninstrumented throughput measurement.

## Required next evidence

Existing same-runner ABBA, identical packages/harness and PostgreSQL 18.4; fresh
schema/processes, two workers, pool5/overflow0, default 5ms switch interval.
Each round retains all 13 money/idempotency/recovery prerequisites followed by
20 then 100 complete actors, plus cold and three continued-operation batches
for full transaction, create, payment and query. Check raw overlap, CPU/PIDs,
P95/P99, SQL facts and artifact digests. CPU and whole-lifetime CPU <=80%, P95
<=85%, P99 <=100%, RSS <=110% remain the screening budget. Failed screening
means restore the exact baseline application tree, retaining this experiment.

Formal capacity still requires 100 complete actors P95 <=5000ms, P99 <=10000ms,
zero unexpected errors and all money/recovery checks. Higher tiers remain
blocked until the original staircase permits them. Three continued bursts are
not a soak test; service-level synthetic actors do not establish HTTP/auth,
network, live supplier/PSP or production capacity.

C14 R9 remains historical evidence for the old candidate. API credit exhaustion
does not prevent this isolated development/measurement work. A changed final
application must receive a fresh whole-candidate C14 and then C13 when usable API
credit is restored. No paid retry is queued by this experiment.

## Qualification repairs, before admissible comparison

The first CI attempt (36583938348) failed test collection before any measurement;
the dedicated test step now runs from application/. The next attempt correctly
refused a changed frozen formal workflow. That workflow is restored byte-for-byte
(SHA256 160720754942621bdff87dbf2a96e90395444567c7c932d3bb799d0622160330);
additional candidate tests run in the separate CPU qualification step.

Standalone journey run 36585228759 then refused COLD_MAPPERS_ALREADY_CONFIGURED:
constructing load_only options at module import configured the mapper registry.
Artifact 11041565901 SHA256 c9d0bf2c18eeebaf4496d421f444fa6224c4844b124e01d8a94f611a0c672ac8
preserves this invalid attempt. No result on application b4a998a is admissible
for adoption. Query options now initialize on the first actual service call;
only immutable statement shapes are cached afterward. The original cold mapper
check is unchanged and the first-use cost remains inside the operation. A fresh
subprocess regression verifies importing the services does not configure mappers.
All nine candidate-specific local tests pass (SQLite); existing 68 regressions
and 31 harness tests were previously qualified. Fresh PostgreSQL and ABBA runs
are required on application 09f45b2; no partial result is carried forward.

## Verified standalone normal-operation measurement

Run [36585892125](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36585892125),
head aa10337c0a874cdd302c1cccb37fa552223d35f8 / application 09f45b2.
Artifact 11041946812 SHA256 b281f135ddf0c3b7b057657d55aeb50e6ef704de30496ec7f6e813a33fc11fe8.
ZIP and every manifest entry, raw percentiles/CPU/actual overlap and all 960 order
ledger/lifecycle facts passed independent download readback. This single-run
measurement is not a baseline/candidate speedup claim or capacity acceptance.

| Concurrent actors | Operation | Mode | P95 ms | P99 ms | App CPU seconds |
|---:|---|---|---:|---:|---:|
| 20 | create_order | Cold first batch | 1040.173 | 1042.138 | 1.829 |
| 20 | create_order | Continued: median of 3 batches | 216.265 | 217.826 | 0.277 |
| 20 | payment_confirm | Cold first batch | 1604.795 | 1606.534 | 2.517 |
| 20 | payment_confirm | Continued: median of 3 batches | 592.037 | 595.843 | 0.658 |
| 20 | order_query | Cold first batch | 905.863 | 906.817 | 1.616 |
| 20 | order_query | Continued: median of 3 batches | 75.563 | 76.631 | 0.098 |
| 20 | full_transaction | Cold first batch | 2393.243 | 2395.634 | 3.315 |
| 20 | full_transaction | Continued: median of 3 batches | 1419.285 | 1456.597 | 1.681 |
| 100 | create_order | Cold first batch | 1908.222 | 1930.594 | 3.029 |
| 100 | create_order | Continued: median of 3 batches | 1151.583 | 1222.177 | 1.488 |
| 100 | payment_confirm | Cold first batch | 3885.317 | 4018.542 | 5.206 |
| 100 | payment_confirm | Continued: median of 3 batches | 2866.589 | 2980.670 | 3.408 |
| 100 | order_query | Cold first batch | 1195.166 | 1228.879 | 1.989 |
| 100 | order_query | Continued: median of 3 batches | 378.618 | 385.578 | 0.481 |
| 100 | full_transaction | Cold first batch | 8810.536 | 8853.590 | 11.045 |
| 100 | full_transaction | Continued: median of 3 batches | 7159.091 | 7331.752 | 8.521 |

100-actor full-transaction P95 remains above 5000 ms in both modes. These phase
percentiles cannot be summed. CPU is the sum of two application worker process
counters and excludes PostgreSQL; continued batches are bursts, not a soak.

## Original formal gate — failed at 100

Run [36585892203](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36585892203)
on the same candidate/application completed all 250 PostgreSQL regressions with
zero skips/failures/errors, followed by all 13 multi-process money, inventory,
idempotency and crash/lease-recovery scenarios. Two AMD EPYC 7763 worker cores,
two service processes, pool5/overflow0; PostgreSQL 18.4. The original frozen
formal workload and thresholds are unchanged.

| Full concurrent actors | P95 ms | P99 ms | Errors | SQL reconciliation | Gate |
|---:|---:|---:|---:|---|---|
| 20 | 2570.909 | 2576.029 | 0 | PASS | PASS |
| 100 | 8476.875 | 8546.444 | 0 | PASS | FAIL: P95 > 5000 ms |

Actual overlap equals 20/100. No 250/500/1000 tier ran. All 120 completed orders
retain one payment attempt, one capture, two balanced ledger entries and matching
completed native/trips state. Independently verified ZIP, 230-file raw manifest,
source binding, timings, overlap and JUnit records. Normal artifact 11042393390
SHA256 de15c60dba51866d006f0f758159e9f58054744172af0bb16c072f9f0f4ab829.
Formal and standalone journey are separate runners; their timings cannot be
used to calculate an optimization speedup. The later complete ABBA decision is recorded below.

A separate, uncommitted local prototype screened direct append-only evidence and
ledger inserts. SQLite sequential ABBA CPU was 2.743553 / 2.739687 / 2.530108 /
2.558799 seconds (09f45b2 / prototype / prototype / 09f45b2); median improvement
only 0.614%. It is not promoted, not PostgreSQL capacity evidence, and changes no
remote application bytes. Removing postponed annotations was also only a local
startup screen and is not part of any remote candidate.

## Separate diagnostic findings

The instrumented run is excluded from acceptance timings. Its 236-file manifest
and ZIP artifact 11043620003 were independently verified (SHA256
362876243f38f55749c04960fb4636825f19d509a67c5492614cd606cd9f0523).
The two 100-actor process profiles recorded 11,400 SQL executions and 2,100
connection acquisitions. Counts remain 114 statements and 21 acquisitions per
complete actor; query-template reuse has not removed these round trips.

Aggregated pool waiting was concentrated in money.create (402.543 seconds over
500 calls) and ride.create (246.500 seconds over 100 calls). These are sums across
concurrent and nested replay threads, NOT transaction elapsed time or additive
phase percentiles. They indicate where contention is observed; they do not prove
that simply increasing pool size will help. Earlier pool/admission experiments
remain insufficient and are not repeated. A next implementation needs to reduce
redundant database work while proving the original locking, request-conflict,
commit/recovery and money-truth boundaries; no such rewrite is accepted here.

## Final same-runner ABBA decision — REVERT

Run [36585892034](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36585892034)
completed original / candidate / candidate / original on one runner with identical
packages, PostgreSQL and harness, fresh per-round schemas/processes, two workers,
pool5/overflow0, default 5ms thread switch interval and no per-call profiler.
Nine dedicated PostgreSQL tests and all 31 harness qualification tests passed.
Every round passed all 13 correctness scenarios, exact actual 20/100 overlap,
and all supplementary cold/continued batches; 960 supplementary orders per round
reconciled. The ZIP and all 2,545 raw-manifest entries, four original round results,
CPU/lifetime/PID bindings, full raw percentiles, supplementary SQL facts and budget
were independently verified. Artifact 11042319689 SHA256
ead85be0a85f205f9a7f740f55cdbd6f43d068962cc6d60de062ef7c874a08f2.

| Round | Variant | App CPU s | Whole lifetime CPU s | Full 100 P95 ms | P99 ms |
|---:|---|---:|---:|---:|---:|
| 1 | baseline | 11.195695 | 19.959164 | 8653.238 | 8691.357 |
| 2 | candidate | 10.644388 | 19.278179 | 8295.638 | 8364.753 |
| 3 | candidate | 10.787038 | 19.454299 | 8308.230 | 8371.673 |
| 4 | baseline | 12.372269 | 21.361251 | 9347.720 | 9466.285 |

| 100-actor metric (median of two rounds) | Baseline | Candidate | Improvement | Required |
|---|---:|---:|---:|---:|
| App CPU seconds | 11.784 | 10.716 | 9.07% | >=20% |
| Whole worker lifetime CPU seconds | 20.660 | 19.366 | 6.26% | >=20% |
| P95 ms | 9000.479 | 8301.934 | 7.76% | >=15% |
| P99 ms | 9078.821 | 8368.213 | 7.83% | No regression |
| Maximum worker RSS KiB | 185840.000 | 185382.000 | 0.25% | <=10% growth |

Both required user screening targets fail (app CPU 9.07%, P95 7.76%); the lifetime
CPU guard also fails (6.26%). Paired app-CPU improvements were approximately 4.92%
and 12.81%, showing material round variation. No PASS or general speedup claim is
inferred from two samples per variant. The original formal 100 P95 gate also
failed separately at 8476.875 ms.

**Decision: restore the exact original application tree
6570b66bc977f89c0311d67bdc6b721cd70d4e09 and unarm cpu_candidate.json.**
The tested implementation and nine tests remain reproducible at aa10337c0a874cdd302c1cccb37fa552223d35f8.
This report and the CI qualification repair are retained; no performance patch
is adopted, no higher tier is authorized, and high-concurrency acceptance remains
NOT ACHIEVED. Fresh automatic checks on the restoration commit are not evidence
for the rejected candidate and must not be relabeled as its result.


### Primary complete-actor tier medians

| Actors | Variant | P95 ms | P99 ms | App CPU s |
|---:|---|---:|---:|---:|
| 20 | baseline | 2752.749 | 2762.691 | 3.973 |
| 20 | candidate | 2556.918 | 2559.361 | 3.713 |
| 100 | baseline | 9000.479 | 9078.821 | 11.784 |
| 100 | candidate | 8301.934 | 8368.213 | 10.716 |

### Same-runner cold and continued operation detail

Each cold cell is the median of two first-process batches; each continued cell
is the median of all six continued batches across two rounds. CPU sums both
worker processes and excludes PostgreSQL. P95/P99 are per-batch percentiles,
not a pooled request distribution; the phase percentiles must not be added.

| Actors | Operation | Mode | Baseline P95/P99 ms | Candidate P95/P99 ms | Baseline/candidate app CPU s |
|---:|---|---|---:|---:|---:|
| 20 | create_order | Cold | 1203.991 / 1223.284 | 1182.406 / 1186.761 | 2.058 / 2.090 |
| 20 | create_order | Continued | 232.193 / 235.081 | 217.736 / 218.492 | 0.279 / 0.272 |
| 20 | payment_confirm | Cold | 1669.338 / 1674.630 | 1637.592 / 1639.490 | 2.649 / 2.529 |
| 20 | payment_confirm | Continued | 673.024 / 675.838 | 590.063 / 593.623 | 0.773 / 0.659 |
| 20 | order_query | Cold | 991.919 / 996.506 | 998.934 / 999.514 | 1.857 / 1.860 |
| 20 | order_query | Continued | 75.905 / 77.888 | 75.542 / 75.815 | 0.101 / 0.096 |
| 20 | full_transaction | Cold | 2612.893 / 2626.869 | 2404.213 / 2407.996 | 3.658 / 3.424 |
| 20 | full_transaction | Continued | 1468.839 / 1508.685 | 1324.511 / 1360.465 | 1.747 / 1.510 |
| 100 | create_order | Cold | 2065.042 / 2122.220 | 2014.505 / 2035.783 | 3.281 / 3.197 |
| 100 | create_order | Continued | 1010.110 / 1044.483 | 1097.012 / 1134.770 | 1.415 / 1.484 |
| 100 | payment_confirm | Cold | 4496.261 / 4545.770 | 4161.032 / 4205.429 | 5.636 / 5.297 |
| 100 | payment_confirm | Continued | 3238.565 / 3318.385 | 3107.585 / 3200.332 | 3.810 / 3.464 |
| 100 | order_query | Cold | 1314.844 / 1326.347 | 1342.374 / 1364.934 | 2.268 / 2.287 |
| 100 | order_query | Continued | 378.379 / 396.709 | 373.588 / 384.757 | 0.498 / 0.497 |
| 100 | full_transaction | Cold | 8747.864 / 8794.539 | 8392.100 / 8500.944 | 11.249 / 10.520 |
| 100 | full_transaction | Continued | 7494.183 / 7613.165 | 7035.571 / 7114.808 | 8.872 / 8.158 |

C14 remains blocked by the actual provider credit refusal established in R9;
no paid retry is queued. User priority remains capacity work. C13 and release
stay gated. Remaining work is an application design that reduces redundant
round trips/connection holding while preserving all money and recovery rules,
then another fixed-candidate, same-runner comparison and original formal gate.
