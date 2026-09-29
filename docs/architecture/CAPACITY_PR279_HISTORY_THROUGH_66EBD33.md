# PR 279 evidence history through 66ebd33

Archived from the PR body before the source-history lookup change on 2026-09-29.
This is historical evidence, not acceptance of a later candidate or authority to deploy.

## Verified head 66ebd33 — transaction correctness passes; 100-actor capacity still fails

Payment success now combines two conflict probes into one EXISTS statement and reads the optional fact binding/existing fulfillment together. Its read count falls from **6 SELECTs to 4**. Original attempt/intent locks, error precedence, commit boundaries, callback validation, receipt identity and missing-binding fallback remain intact. Query shapes are reused, never payment facts. The preceding commit also closes two idempotency read/write races through conditional atomic UPDATE/DELETE operations. No schema, pool, actor definition or threshold changes.

**Current-head verification**

- Exact local regression list: **146 PASS, 1 PostgreSQL-only migration case skipped**. Cloud PostgreSQL: **147 PASS**, zero failures/errors/skips, **522.103 s**, including signed callback and duplicate-success/receipt regressions.
- Normal and diagnostic runs each passed all **13 independent-process correctness scenarios**.
- Official staircase: **20 actors P95/P99 2466.239/2468.410 ms PASS**; **100 actors 8344.302/8423.566 ms FAIL**. Both tiers had zero unexpected errors and SQL ledger PASS. Stopped at the first failed tier; **250/500/1,000 NOT RUN**.
- Diagnostic 100 actors: P95/P99 **8684.625/8703.930 ms**, zero errors, SQL PASS. Each 50-actor process executed **5700 SQL** and acquired **1050 connections**: **114 SQL / 21 acquisitions per complete actor**, versus 116/21 at 645a8da and 117/21 before both changes. Payment success itself fell from 500 to 400 SQL statements per 50-actor process.
- Current application tree: `e4c71a2e1bdb20f5d742c1290b687624dce01bdb`. Cold-import check: 563 registered mappers, **0 configured at import**; no hidden warmup.
- Capacity foundation, ticket, rental/attraction and monitor companion workflows passed. The pool comparison skipped unchanged experiment definitions; its green status is not capacity evidence.

**Same-runner ABBA comparison — no demonstrated latency improvement**

Both versions used the identical uninstrumented harness, dependencies, pool settings and runner, with fresh schemas/processes for each round.

| Round | Version | 100-actor P95 ms | P99 ms |
|---|---|---:|---:|
| 1 | baseline 645a8da | 10374.336 | 10389.432 |
| 2 | candidate 66ebd33 | 9685.155 | 9712.425 |
| 3 | candidate 66ebd33 | 10210.029 | 10388.375 |
| 4 | baseline 645a8da | 9134.466 | 9364.919 |

Median P95: baseline **9754.401 ms**, candidate **9947.592 ms** (observed **1.98% higher**, overlapping ranges, only two repetitions per version). All rounds passed correctness and SQL checks with zero unexpected errors; all failed the 100-actor P95 gate. The measured reduction in SQL statements is **not a demonstrated speedup**, and separate-run official timings are not causal evidence.

**Decision and remaining bottleneck**

Keep the race fixes and verified query reduction in this Draft; do not accept capacity or claim a latency gain. The dominant remaining work is in order creation, money movement, payment creation and fulfillment. At diagnostic 100, the two processes accumulated **34.83/35.79 s connection hold** across each 5-connection pool and **11.43 CPU s** combined on the 2-CPU runner. Connection queues reached **5.50/6.49 s**. Concurrent sums are not elapsed actor time; whole-batch resource bounds are not P95 predictions. Further progress needs materially less work/connection occupancy per transaction and measured scaling on explicit resource budgets, rather than another unproven pool increase.

**Evidence**

- [PostgreSQL + normal + diagnostic run 36502880644](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36502880644).
- [Same-runner ABBA run 36502880472](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36502880472).
- Normal artifact **11006197025**, ZIP SHA256 `d1776893cfe22b294c745cc5836ac7c8c172a657faecc8239adda30ad5d93f31`.
- Combined artifact **11007105494**, ZIP SHA256 `44c1021f0376b88091f6f9c32f4140626b41755366b1e5b3b94792ad5124a65d`.
- ABBA artifact **11007016042**, ZIP SHA256 `fed0b8662d61e3e704255adb57cab5df29bbd452d96f6cefd24eb8acdd96af5d`.
- All **230 normal / 466 combined / 1845 ABBA** nested manifest entries, source bindings, JUnit and raw nearest-rank percentiles verified. Archived source matches all four authored application source/test files from this work session.

Scope: **Draft only, unmerged/undeployed**; no real supplier/PSP execution. Full synthetic transaction actors on two isolated service processes are not HTTP users or concurrent online users. Final independent C13/C14 reviews, HTTP/multi-host validation and million-online capacity remain outstanding.

<details>
<summary>Prior verified iterations (historical heads; not acceptance of the current head)</summary>

### Verified preceding head 645a8da — atomic idempotency ownership/state writes

Completion and release previously read a claim and later mutated it by primary key. Two local competing-connection regressions reproduced overwriting a replacement request hash and deleting a completed receipt. Completion now performs a conditional UPDATE on operation/key/request hash, requiring exactly one match; release performs a conditional DELETE with the additional response_code=102 predicate. Same-payload explicit reconciliation remains allowed. This does not introduce a generation/lease fence.

Local targeted tests: 85 PASS. [PostgreSQL run 36501116337](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36501116337): **106 PASS**, zero failures/errors/skips (339.470 s); all 13 independent-process correctness scenarios PASS. Official 20 actor P95/P99 **2557.364/2601.621 ms PASS**; 100 actor **8390.811/8445.171 ms FAIL**, zero unexpected errors, SQL ledger PASS; stopped before 250/500/1,000. Diagnostic 100 **8723.496/8774.260 ms FAIL**, correctness/SQL PASS. Measured **116 SQL and 21 connection acquisitions per actor**, versus 117/21 previously. Both 50-actor processes executed 5800 SQL; completion itself fell from 100 to 50 statements per process.

[Same-runner ABBA 36501116304](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36501116304), baseline 55a5be2 → candidate 645a8da → candidate → baseline: 100-actor P95 **8690.138 / 8695.657 / 8718.871 / 8802.222 ms**. Baseline median **8746.180**, candidate median **8707.264 ms** (~0.45% observed decrease, overlapping ranges; no demonstrated latency improvement). Every round correctness/SQL PASS and zero unexpected errors; every 100-actor round failed P95.

Evidence ZIP SHA256:
- Normal artifact **11005127969**: `8462b64f421a2897061479979ed05ea96d2a10837bfa9fcae21f85565296ecee`.
- Combined artifact **11005748394**: `e2b5c350a7b09679072bd7beabba4a3d58c338a3bf21b6586a1aebec435f3f64`.
- ABBA artifact **11005494186**: `981602dd356e6ab098aa884ec632f881be23af9a79ba4edc5eac9c0b28b15567`.
All 230 normal, 466 combined and 1845 ABBA nested manifest entries verified, along with source bindings, JUnit and raw nearest-rank percentiles. Application tree `9b44ff6d73a4c241dbe5ef76430a49e819078792`. Companion workflows passed; pool comparison was skipped by its definition guard and is not capacity acceptance.


## Current head 55a5be2 — SQL attribution verified; 100 actor P95 gate fails

At every catalog money movement, the credit-source check looks up `catalog_credit_source.payment_intent_id`. The existing table only indexed `credit_id`, allowing a scan as unrelated credit history grows. Revision `0144_credit_source_intent_index` adds the matching index; PostgreSQL uses `CREATE INDEX CONCURRENTLY` in Alembic's autocommit block to avoid a prolonged write block. Downgrade drops only the index. No money check, locking, actor definition, or capacity threshold changes. Locally, 81 targeted money/transaction tests passed; a SQLite upgrade/downgrade preserved existing data and Alembic identified a single head. The current head adds an isolated PostgreSQL migration test that creates a populated source table, exercises concurrent index creation and downgrade, checks the index in pg_indexes and preserves the row. [Latest PostgreSQL run 36437783857](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36437783857): **103 regressions PASS** (zero failures/errors/skips), including the concurrent index upgrade/downgrade. All 13 multi-process correctness scenarios PASS. Official 20 actor P95/P99 **2642.723/2646.026 ms PASS**; 100 actor P95/P99 **8994.209/9071.055 ms FAIL**, zero unexpected errors, SQL ledger PASS, and stopped before 250/500/1,000. Diagnostic 100 P95/P99 **9437.182/9525.109 ms FAIL**, zero errors and SQL PASS; 117 SQL and 21 connection acquisitions per actor. Normal artifact 10977012245 ZIP SHA256 `d385a1e972bb4b376b3fad7058f8297e108d5e4564de61f4acb791986f399bd3`; combined artifact 10977575643 ZIP SHA256 `914f1c949dae9f094e92ab94c359ec8203c980ccf69db20c1ed078b7d274a30d`. All 230 normal and 466 combined nested SHA entries verified; current head/application tree binding and all raw P95/P99 percentiles checked. The index addresses future large-ledger scans; this small synthetic data run does not show a current latency win.

Current head adds only isolated diagnostic SQL counts/time by service; the application tree remains `48923593a2a386ca6ef627afdab63db42fb51681`. [Current-head PostgreSQL run 36478421533](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36478421533): **103 regressions PASS**, 13 independent-process correctness scenarios PASS. Official 20 actor P95/P99 **2802.282/2808.277 ms PASS**; 100 actor **9088.366/9114.941 ms FAIL**, zero unexpected errors and SQL ledger PASS; 250/500/1,000 not run. Diagnostic 100 **9066.394/9184.291 ms FAIL**, zero errors and SQL PASS. Normal artifact 10995612394 ZIP SHA256 `4c5b3c699a358f1676177fdfc34f931dcba7d73abd77b8b1083e2b1d6c881309`; combined 10996726530 ZIP SHA256 `9931724067cfd2112296307bd3450889dddc1544966ce05407cc31ab54698d66`. All 230 normal and 466 combined nested hashes, head/tree bindings, 103-case JUnit and raw P95/P99 percentiles verified.\n\nEach diagnostic 50-actor process executed 5850 SQL and acquired 1050 connections. SQL by service, per process (divide by 50 for per-actor counts): money.create **1000**, ride.fulfill **1000**, ride.create **750**, supplier.record_supplier_fact **650**, payment.create_intent **600**, bridge.checkout_contract **550**. These six account for 4550/5850 statements (**77.78%**) or 91/117 per actor. The remaining 26/actor span payment state transitions, idempotency, source and ancillary reads. Optimization must target several verified duplicate reads without collapsing separate commits or weakening money replay and ledger constraints. [Current-head PostgreSQL run 36443446128](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36443446128): **103 regressions PASS**, all 13 independent-process scenarios PASS. Official 20 actor P95/P99 **2536.714/2578.107 ms PASS**; 100 actor **8362.933/8432.863 ms FAIL**, zero unexpected errors and SQL ledger PASS, stopped before 250/500/1,000. Diagnostic 100 actor **8857.674/8933.289 ms FAIL**, zero errors and SQL PASS; 117 SQL and 21 acquisitions per actor. Normal artifact 10980895169 ZIP SHA256 `1b996e1b48c1ab11ef3bf52e0aa6cb8a180196c74797d15b4a383e2d1750bf9b`; combined artifact 10979717381 ZIP SHA256 `3a55938223f43aff3cdc2669802cf2e05350ddd43a3ee4e1d569973c34404b7c`. All 230 normal and 466 combined nested hashes, source bindings and raw P95/P99 percentiles verified.\n\nAt diagnostic 100, each 50-actor process acquired/returned 1050 connections, executed 5850 successful SQL statements and accumulated **38.05/37.88 seconds of connection hold** across the 5-connection instance pool. The idealized hold-only floor is about 7.6 seconds for that process (38/5), before scheduling/other costs; it is a throughput bound, not a predicted actor percentile. Ownership per 50 actors: money.create 250 acquisitions, 5.91/6.32 s hold, 188.38/211.62 s summed queue wait; ride.create 50 acquisitions, 4.40/4.77 s hold, 127.67/126.86 s summed queue wait; ride.fulfill 100 acquisitions, 5.39/5.40 s hold. Concurrent wait sums overlap and are not elapsed transaction time. The next business change must materially shorten connection holding across several stages while retaining commits, locks, replay and ledger checks; a single missing index is not enough for the 5 s target. The official pool stays 5 after two same-runner ABBA comparisons.\n\n**Previous diagnostic head a2bd08b** (same application tree): 103 PostgreSQL regressions PASS, 13 correctness scenarios PASS. Official 20 actor P95/P99 **2665.133/2695.435 ms PASS**; 100 actor **9079.975/9165.508 ms FAIL**, zero errors and SQL ledger PASS, stopped before 250/500/1,000. Diagnostic 100 **9241.217/9276.067 ms FAIL**, 117 SQL and 21 acquisitions/actor, correctness/SQL PASS. Across two 50-actor processes, native ride order creation consumed 172.557/187.510 summed concurrent wall seconds for 50 calls, while idempotency claims consumed 6.675/4.282 seconds for 100 calls and completions 0.972/0.991 seconds for 50 calls. Money create consumed 240.322/224.376 seconds for 250 calls; these overlapping concurrent sums are not elapsed time or exclusive attribution. [Run 36441147647](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36441147647): normal artifact 10979676278 SHA256 `8250fbee4988c0e121520ecc48549cf6e69f0d21bb1a361e2510de221928030e`; combined 10979417792 SHA256 `69654a2e9a955fae591ed60828b43851d577d2c4f4644f15713a5e0347e14a3f`; all 230 normal and 466 combined nested SHA entries, bindings and raw percentiles verified.\n\n**Same-head pool ABBA** 5→10→10→5 at 100 actors: P95 **9870.125/9753.121/9681.652/8911.131 ms**. Pool-5 median **9390.628**, pool-10 **9717.386 ms** (observed 3.48% slower; overlapping variability). All rounds correctness/SQL PASS, zero errors; all failed P95. Pool 10 remains unadopted. [Run 36441147563](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36441147563), artifact 10979318228 ZIP SHA256 `301f140f8ad6a56cc1df6e59e282643716dbe7f995cd14ff1bd9554e39658724`; all 925 outer and 4×230 round manifests, head bindings and raw percentiles verified.\n\nThe passing 1ddb580 migration/correctness results below remain verified for the same application tree, not yet a current-head run.\n\n**Previous head 6de9580, application tree 05a7dcd247805563aaf4d48bf1e331ed57d4f374.** PostgreSQL 102 regressions and all 13 independent-process correctness scenarios passed. Official pool-5 20 actor P95/P99 **2091.285/2096.362 ms PASS**; 100 actor P95/P99 **7944.516/7994.634 ms FAIL**, zero unexpected errors and SQL ledger PASS. First failed tier stopped before 250/500/1,000. Diagnostic 100 P95 **8348.059 ms**, 117 SQL and 21 acquisitions per actor, max pool wait 6.76/6.70 s. [Main run 36433838501](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36433838501): normal artifact 10975451240 ZIP SHA256 `b51453b6e09d7f1904b0bb31fbb6c80ff4d3facfda11cd132164e0f69a058397`; combined artifact 10974584295 ZIP SHA256 `f7f5b2604074c39d5a73bdc2e7c08978ec0f1b2686ae47b3b308b7bb873cd36e`. All 466 combined nested manifest entries and bindings/raw percentiles verified.

**Isolated same-runner pool ABBA at 6de9580:** four fresh schema/process rounds at 20 and 100 actors, pool 5→10→10→5. At 100 actors, P95 **8861.831 / 9584.739 / 9513.635 / 9409.186 ms** respectively. Pool-5 median **9135.509**, pool-10 median **9549.187 ms** (observed 4.528% slower, overlapping run variability). All 20 rounds passed the gate; all 100 rounds failed P95, while all 13 correctness scenarios/SQL ledgers passed and errors were zero in every round. Pool 10 is **not adopted**. [Run 36433838412](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36433838412), artifact 10976015240 ZIP SHA256 `86bc45f9ce2f770343c5b1281f536d49d5bc4ad14b6c6550ae925729f82e4139`; all 1845 manifest entries, source/head bindings and raw percentiles verified. The experiment workflow now checks whether its harness changed and does not rerun four rounds for an index-only commit; its green skipped job is not capacity evidence.

**Earlier same-runner code ABBA** at f9d2961c compared c3aa5fb9 against the application tree carried through 6de9580: 100 P95 baseline 9281.163/8756.586 ms, candidate 8805.973/8802.191 ms. Medians 9018.875→8804.082 ms, observed 2.38% lower with overlapping ranges; both failed 5 s. [Run 36431381140](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36431381140), artifact 10974113841 ZIP SHA256 `39f702d5fa6510dec59ee36ad3685bc0601cdb9f6707df332e16e5892aaa619b`, all 1845 manifest entries verified.

These are synthetic two-process RIDE service transactions on 2 CPU, not HTTP/auth or production proof. The million-online goal remains unproven. Draft only; unmerged/undeployed, current-head independent C13/C14 review outstanding.

<details><summary>Earlier verified iterations</summary>

## Verified current head c3aa5fb9: one fewer connection, 100-actor latency still fails

Head `c3aa5fb93726daebf591b81c71a2927922f41531`; application tree `53f71a998916326304dc264f9991422510dfea31`.

RIDE checkout now reads the source decision through `latest_in` using its already-acquired order/payer/deadline guard connection. The standalone source API delegates to the same read. Missing sources still use the original fallback, and payment transitions keep their independent commit boundaries. No cached source facts, removed financial checks, pool changes or gate changes.

Validation:
- 98 local targeted regressions PASS.
- 98 isolated PostgreSQL tests PASS (328.029 s; zero failures/errors/skips), including source-present/source-missing checkout and caller rollback coverage.
- Normal and diagnostic rounds each passed all 13 independent-process correctness scenarios.
- Normal staircase: 20 full synthetic actors P95 **2596.070792 ms**, P99 **2601.510821 ms** PASS; 100 actors P95 **8741.658635 ms**, P99 **8830.737995 ms** FAIL. Both tiers: zero unexpected errors and SQL ledger checks PASS. Peak executing/inflight actors: 20/100 respectively.
- First failed tier stopped the run; **250/500/1000 not run**.
- Diagnostic 100-actor P95 9142.231316 ms, P99 9180.612040 ms, zero errors, SQL PASS.
- Each diagnostic 50-actor process used **1050 connection acquisitions / 5950 successful SQL events**, confirming **21 acquisitions and 119 SQL per actor**. Previous a554f6f7 diagnostic was 22 acquisitions / 119 SQL per actor. This is a measured reduction in connection churn, not a demonstrated latency percentage improvement.
- Diagnostic maximum single pool waits: 6.6717 / 6.4756 seconds. Process CPU user+system: 6.0539 / 6.0474 seconds. Concurrent wait totals overlap and must not be interpreted as elapsed time.
- Local connection call-path audit: create/idempotency 5, checkout/payment 10, capture replay/conflict checks 3, supplier confirmation 1, fulfillment 2 = 21.
- The same-runner ABBA workflow did **not** rerun comparison rounds on this commit (definition unchanged); its green status is not performance acceptance. No causal latency improvement claim is made from separate-run timings.
- Capacity foundation, ticket, rental/attraction and monitor companion workflows are green; they do not override the transaction gate.

Evidence: [run 36424287358](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36424287358).
- Early normal artifact 10971432211; ZIP SHA256 `0774e072584a9f7d230c25529d7c8a1061ba9af44f07cdeaca72510c96963693`.
- Combined artifact 10970758637; ZIP SHA256 `c1868bd2d7dc4489f33c8e87901a481550e2b2a85daad30e89c8580173491417`.
- ZIP hashes, all 466 combined nested manifest entries, source bindings, 13-scenario counts and raw actor P95/P99 calculations verified.

Next bottleneck: the one-connection reduction leaves the 119-SQL workload intact. Review query/CPU work in order creation and payment before attempting further transaction consolidation; recovery, locks and replay protection remain mandatory. No million-online or HTTP capacity claim: two isolated service processes on 2 CPU, synthetic payment/supplier facts only. Draft remains unmerged/undeployed; current-head C13/C14 independent review is still outstanding.


<details><summary>Prior verified iterations</summary>

## Verified current head: a554f6f7 — query shape reuse, capacity still blocked

Application tree: `13bb6f0db529fdb728cfd3d79b67324481a50374`. Parent/baseline: `0a8efaf785e384a0a0e8a2c267e73eb1de1066c9`.

This iteration reuses immutable bound SELECT shapes for money row locks, evidence reads and database-clock expressions. Request parameters, rows and database time are read afresh; no financial checks, row locks, transaction boundaries or capacity gates were removed. Cold-import checks on baseline and candidate each found 563 registered mappers and zero configured mappers: no hidden ORM warmup was added.

Validation:
- Local targeted regressions: 95 passed.
- Isolated PostgreSQL regressions: 95 passed, no failures/errors/skips.
- Current-head normal and diagnostic runs each passed all 13 independent-process correctness scenarios, including replay, inventory races and crash/refund recovery.
- Normal staircase on 2 CPU / 2 service processes / pool 5 each: 20 actors P95 3001.102421 ms, P99 3007.752665 ms PASS; 100 actors P95 9651.795780 ms, P99 9751.582349 ms FAIL. Both tiers had zero unexpected errors and SQL ledger verification PASS.
- No 250/500/1000 tier ran; the existing first-failed-tier stop remains enforced.
- Diagnostic 100 actor P95 9406.671732 ms, zero errors, SQL PASS. One 50-actor process recorded 5950 successful SQL events and 1100 connection acquisitions (119 SQL / 22 acquisitions per actor), with 375.606 seconds summed concurrent queue wait; this sum is NOT elapsed time. Query-shape reuse has not removed the connection churn.
- Ticket, capacity, rental/attraction and monitor companion workflows are green at this head. This does not substitute for the failing transaction capacity gate or independent C13/C14 review.

Same-runner uninstrumented ABBA comparison (baseline/candidate/candidate/baseline), fresh schemas and service processes, identical harness/dependencies/pools:
| Round | Application | 100 actor P95 ms | P99 ms |
|---|---|---:|---:|
| 1 | baseline 0a8efaf | 9231.037685 | 9315.484060 |
| 2 | candidate a554f6f | 8687.365051 | 8801.074114 |
| 3 | candidate a554f6f | 8743.644919 | 8857.241179 |
| 4 | baseline 0a8efaf | 8866.798726 | 8937.560495 |

100 actor median P95: 9048.9182055 → 8715.504985 ms, an observed 3.6846% reduction. Only two repetitions per version: not a general performance guarantee. All four rounds passed correctness and SQL checks with zero unexpected transaction errors, but all failed the 5000 ms P95 gate. Separate-run standalone timings are not used as causal improvement evidence.

Evidence:
- [Normal + diagnostic run 36421238236](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36421238236), artifact 10970282826, ZIP SHA256 `867319b6ad395004ca5de5d3e17f04137acb9d2b772fbe9160a579d8252c837d`.
- [ABBA run 36421238272](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36421238272), artifact 10969913571, ZIP SHA256 `b32fa39e17df2b7dc9e272a836c3f4f8f281c92276cc494bf0f00122d748c3ca`.
- Downloaded ZIP hashes and all nested manifests verified; raw actor durations reproduce P95/P99; source and environment bindings checked.

Decision: retain this bounded improvement in the draft, but do not accept 100-actor capacity. Next optimization must target repeated connection acquisition/transaction work while preserving crash recovery and financial lock semantics. Full synthetic service transactions are not HTTP requests or online users. Production, HTTP/auth, real supplier/PSP and million-online capacity remain unproven. Draft only; no merge/deployment/runtime change. Current-head independent C13/C14 review remains outstanding.


<details><summary>Earlier verified iterations and review history</summary>

## Latest verified head: 0a8efaf785e384a0a0e8a2c267e73eb1de1066c9

Application tree: `681a2704e057f1c47abb803a4beccaeaff0ff768`. **Transaction fixes verified; capacity acceptance still FAILED.**

### What changed and why
1. Native PostgreSQL/SQLite idempotency-key conflicts return an existing claim/receipt on one connection. Normal retries no longer trigger an expected IntegrityError/rollback/reacquisition. Different fingerprints and unrelated integrity errors still fail.
2. Evidence append reads the tail sequence/hash without hydrating the prior JSON payload. Full-chain validation is retained.
3. A reproduced source-write failure left committed native orders in RIDE, RENTAL and ATTRACTION. These creations now persist order/deadline/evidence/source and attraction capacity/prebook consumption in one caller-owned transaction. Failure rolls back all of them before retry. Standalone source decisions retain their transaction. No existing live records were changed.

### Final-head validation
- Run **36402078306**, artifact **10961426523**, SHA256 `828b4d562435f40f316f77e2a77b61a1e3562c74fe9e58c578c652e25d0ee5bb`.
- **93 PostgreSQL regression tests PASS**, zero skipped/failures/errors, including all three source failure/rollback/retry cases.
- **13 independent-process correctness scenarios PASS** in both normal and diagnostic runs: inventory contention, first checkout, idempotency, payment/cancellation boundaries, and OS-exit refund recovery after natural lease expiry.
- Normal 20 concurrent full synthetic journeys: P95 **2944.280716 ms**, P99 **2946.243244 ms**, zero unexpected errors, SQL PASS.
- Normal 100: P95 **10187.646981 ms**, P99 **10231.265834 ms**, zero unexpected errors, SQL PASS. **Both latency gates failed. No 250/500/1000 execution.**
- Diagnostic 100: 119 successful cursor events and **22 connection acquisitions per journey**, versus earlier 24 acquisitions. The successful SQL count includes the duplicate-key INSERT that previously failed and was excluded by after-cursor metrics; it is not evidence of extra business effects.
- Verified artifact ZIP digest, all 230 normal / 236 diagnostic manifest entries, exact source head/tree, 13 scenarios, and raw actor percentile/process counts.
- Final-head ticket preinventory, rental/attraction, and capacity-foundation workflows succeeded. The final-head ABBA workflow skipped its frozen experiment; its green status is not a new capacity result.
- Scope: two independent service processes on shared isolated PostgreSQL, synthetic money/supplier facts. Not HTTP/auth, multi-host, production, or million-online evidence.

### Controlled comparison of the earlier optimization only
Run **36400855020**, artifact **10960948416**, SHA256 `13afff508b9df07673ed121dda1a47d3f6093712f5212292690698b54e8c16de`.
Baseline 7b7ad1e and candidate 10cb72d, identical uninstrumented harness/dependencies/pools, ABBA:
- 100 P95 baseline **9895.244737 / 9374.759939 ms**; candidate **9596.653525 / 9303.955816 ms**.
- Medians **9635.002338 → 9450.3046705 ms**, an observed **1.9169%** reduction. Ranges overlap; two repetitions do not establish a robust performance gain. All four rounds fail capacity, with correctness/SQL PASS and zero unexpected errors.
- This comparison predates the atomic source fix; do not attribute its numbers to the final application tree or compare separate runners as causal speedups.

Draft remains unmerged/undeployed. No live supplier/PSP execution or live-data repair. Current-head independent reviews remain outstanding. Remaining blocker is full-transaction latency; the fixed 20→100→250→500→1000 gates remain intact.

<details>
<summary>Prior evidence and decisions</summary>

## Current repair: 0a8efaf785e384a0a0e8a2c267e73eb1de1066c9

Confirmed bug and fix:
- Injecting a failure just after source INSERT reproduced a committed orphan native order in RIDE, RENTAL and ATTRACTION. RIDE's API released its claim after this failure, allowing retry to create another native order.
- Creation now calls caller-owned `decide_in`: native order, deadline, evidence, source, and attraction capacity/prebook consumption commit or roll back together. Standalone `decide` retains its own transaction.
- Three failure/retry regressions plus affected capacity/read/payment tests: 37 local SQLite tests passed. Final-head PostgreSQL regression and staircase are running.
- Prior replay/evidence optimization at 10cb72d: 90 PostgreSQL tests and 13 independent-process correctness scenarios passed. Normal 20 P95 1646.858105 ms; 100 P95 5779.467849 ms / P99 5814.958987 ms, zero errors, SQL PASS. Still FAILS the unchanged 5-second gate; no 250+ run. Different-runner numbers are not causal speedup evidence.
- Its diagnostic measurement confirms 23 acquisitions per journey (previously 24). With this atomic follow-up, local SQLite observes 22; final PostgreSQL evidence pending.
- Same-runner ABBA remains pinned to baseline 7b7ad1e and candidate 10cb72d. It does NOT validate this newer application tree. Head-specific comparison concurrency preserves that in-flight experiment; unchanged definition skips on the follow-up.
- Artifact 10960666773 / run 36400855266, ZIP SHA256 `356565e481205c5fd8ef5b9b2dcfa554db1220ac6d06ebbf6293be23a8cc39c9`; nested manifests verified.
- Draft only; no merge, deployment, live data repair or supplier/PSP execution. Current-head independent reviews remain outstanding.

<details>
<summary>Earlier candidate and historical evidence</summary>

## Current candidate: 10cb72d418cd41092aafffb99d1e5278a4a34975

Business changes:
- Native PostgreSQL/SQLite INSERT ON CONFLICT handles only the composite idempotency key. A replay reads its fingerprint and receipt on the same connection, without an expected IntegrityError/rollback/reacquisition. Other integrity errors still propagate; commit-before-effect and incomplete-claim behavior remain.
- Evidence append reads only sequence/hash from the latest row. Complete chain validation is unchanged.
- Local SQLite: 90 targeted tests passed, including concurrent sole-claim winner, changed-payload rejection, one-connection replay, unrelated integrity failure, payment recovery, flight command recovery, inventory races and refund consent.
- PostgreSQL regression, two-process staircase and same-runner ABBA are running. No new capacity pass is claimed.
- cProfile experiment at 7b7ad1e is invalid: negative times and cross-worker counts. Removed; do not use its attribution or instrumented latency. Separate uninstrumented result remains valid: 20 passed; 100 P95 8048.292449 ms, zero errors and SQL PASS.
- No merge, deployment or external supplier/PSP execution. PR remains draft; current-head independent reviews remain outstanding.

<details>
<summary>Previous evidence and decisions</summary>

## Current investigation — queue contention confirmed; admission alone does not meet the gate

Head: `18aed09ba4f2f791ee6b698b5c3cd84d1c6751bc`.
Application tree unchanged: `57720ed0d057bdada9e6e702347e13b608afeeb5`.
This iteration is **TEST_ONLY / BUILD / DOCUMENTATION**. It adds direct blocking-pool-queue timing and bounded-active-work experiments; it does not implement or enable production request admission. PR remains Draft.

### Completed same-runner experiment

[Run 36392661545](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36392661545) completed with the normal capacity gate **FAIL**.

All modes use the same application tree, installed packages, PostgreSQL version, 2 allocated CPU cores, ~8 GB host and two service processes, each with pool size 5 / zero overflow. Each round uses a fresh schema and reruns all correctness checks. Normal acceptance is uninstrumented; the separate diagnostic run is not substituted for it.

| Uninstrumented mode, 100 submitted actors | Observed executing peak across both processes | Observed in-flight peak including queued | Full P95 ms, including admission wait | P99 ms | Admission wait P95 ms | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Normal, no admission limit | 100 | 100 | 8956.997 | 9001.446 | 0 | FAIL |
| Experiment: 2 active actors/process | 4 | 100 | 7933.900 | 8194.143 | 7651.172 | FAIL |
| Experiment: 5 active actors/process | 10 | 100 | 8477.947 | 8734.738 | 7791.227 | FAIL |

All three uninstrumented modes passed 20 submitted actors: P95 **2508.695 / 2418.086 / 2510.952 ms** respectively. Every tested tier had zero unexpected errors and SQL invariants PASS.

The 2-active experiment reduced full 100-submission P95 by **11.42%** in this single ordered trial, while allowing only **4 actors to execute simultaneously**, not 100. This is a workload/admission-policy experiment, not a business-code speedup or a 100-active-transaction capacity PASS. Single runs per policy do not establish repeatable superiority.

Normal **250 / 500 / 1000 remain NOT RUN**, blocked by the failed 100 tier. Experiments are explicitly capped at 100 even if a tier passes, and cannot bypass the normal gate. Thresholds unchanged: P95 ≤5000 ms, P99 ≤10000 ms.

### Direct queue evidence

At diagnostic 100, the wrapper around SQLAlchemy QueuePool's blocking queue get measured:
- Queue-get elapsed sum across the two service processes: **649.290 s**, versus **658.565 s** total connection-acquisition elapsed sum: **98.59%**.
- Largest queue-get span **7.247 s**, versus largest acquisition **7.250 s**.
- Largest connection checkout-to-checkin hold **0.313 s**.
- **1195 blocking queue-get calls/process**, **1200 acquisitions/process**, **5900 successful instrumented SQL statements/process** (118/transaction).

These are sums of overlapping calls, not elapsed job duration or CPU time. Queue-get timing includes the blocking queue operation/condition acquisition and excludes connection creation/pre-ping, making its boundary narrower than the previous pool.connect timing. This uses an internal SQLAlchemy queue interface only in diagnostics; the observed version is archived and incompatibility fails the diagnostic. A local controlled QueuePool probe verified both successful blocking and preserved timeout behavior.

Diagnostic P95 at 100 was **9029.965 ms**, SQL PASS, zero errors, latency FAIL. No profiler timings are substituted into the acceptance table.

### Decision and remaining implementation boundary

**Reject admission-only tuning as a sufficient fix for the 5-second gate.** Retain the experiment and queue instrumentation as engineering evidence. Do not promote either experimental limit into production configuration from this result.

The experiment holds a permit across a complete synthetic journey, including replay checks and simulated fulfillment. Real API creation, payment and fulfillment are separate requests; this permit lifetime cannot be copied directly into production. A production design needs bounded admission at actual request/background-task boundaries, queue deadlines/overload behavior, and explicit validation of authentication, incident controls and payment callbacks. It must report active work and queued work separately and include queue time in request latency.

The remaining performance work is to reduce service CPU/connection-holding work and validate admission at those real boundaries; moving waits out of the pool did not by itself deliver sufficient capacity. This evidence does not justify an online-user or million-online claim.

### Correctness and evidence verification

- **21 PostgreSQL regression tests passed**, zero failures/errors/skips.
- The same **13 correctness scenarios passed in each of four rounds** (normal, diagnostic, 2-active and 5-active); these are repeated checks, not 52 distinct scenarios.
- Every raw load actor's start/execution-start/execution-end/end timestamps were verified in order. Full duration equals end minus start; experimental admission wait equals execution-start minus start.
- Per-process executing peaks were independently recomputed from raw timelines and verified against limits 2/5; no queued actor was counted as executing.
- All four bindings match application tree, package versions, host CPU/model, database version, pool budget and thresholds.

Artifact **10956929383** ([workflow](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36392661545)), ZIP SHA256:
`536d095979f9598b8d96f9f86dd3e5122b7c87e2615d50808dd219a05e18a44c`.

Outer digest verified; manifests verified for normal **230 entries**, diagnostic **236**, each admission round **230**, and the admission aggregate **463** (the aggregate overlaps its nested manifests). Source bindings, JUnit and all raw load timelines inspected. Artifact retention is 30 days; code and summarized evidence are versioned in this PR/history.

Current-head companion workflows completed SUCCESS:
- [Capacity foundation 36392661532](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36392661532)
- [Ticket acceptance 36392661526](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36392661526)
- [Rental/attraction 36392661536](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36392661536)

Previous-head rental/attraction run 36389179925 also completed SUCCESS; its earlier pending status below is historical. Frozen ABBA was not rerun on this head. No C13/C14 independent opinion on this head, merge, deployment, live supplier/PSP calls or HK runtime access.

<details>
<summary>Historical controlled comparison and preceding evidence (bound to earlier commits)</summary>

## Current candidate — controlled improvement measured; 100-tier capacity still FAIL

Current harness head: `73534f71637bdc9cae43ee576687dedb828d8fb4`.
Application tree remains `57720ed0d057bdada9e6e702347e13b608afeeb5` (same business code as 2fdea57).
Change classes this iteration: TEST_ONLY / BUILD / DOCUMENTATION. Draft only; no merge/deploy.

The earlier cross-run latency comparison did not control runner conditions. A pinned **baseline → candidate → candidate → baseline** experiment now ran on one machine, one dependency installation and one PostgreSQL server, using identical uninstrumented harness bytes and fresh schemas/processes for every round.

[ABBA run 36387689369](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36387689369), experiment commit `01e523aa756b3e137dec3fbcb820810e75faa52f`:

| Round | Application version | 20 P95 ms | 100 P95 ms | 100 P99 ms | Correctness / SQL | Capacity |
| --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | baseline c1da061 | 2901.214 | 9841.318 | 9909.069 | PASS | FAIL at 100 |
| 2 | candidate 2fdea57 | 2738.660 | 9295.934 | 9397.546 | PASS | FAIL at 100 |
| 3 | candidate 2fdea57 | 2926.007 | 9522.071 | 9635.386 | PASS | FAIL at 100 |
| 4 | baseline c1da061 | 2878.071 | 10359.935 | 10441.577 | PASS | FAIL at 100 |

100-tier median of the two P95 values: baseline **10100.626 ms**, candidate **9409.003 ms**, observed reduction **6.85%**. Both candidate 100-tier runs were faster than both baseline runs in this experiment. Two repetitions per version are limited evidence, not statistical confidence or production capacity. All four rounds passed the same **13 correctness scenarios**, with **zero unexpected load errors and SQL invariants PASS**. 250/500/1000 remain NOT RUN because 100 fails the unchanged P95 ≤5000 ms gate.

**Decision:** retain the read-reduction candidate for further diagnosis; this controlled sample supports a modest improvement, not capacity acceptance. Do not classify the earlier cross-run slowdown as a demonstrated code regression. Keep the PR Draft and capacity gate RED.

Artifact **10954704533**, ZIP SHA256 `60be945d68159a36149d7d5ad03ba703124f00479f5a0756b4402af76daa8f10`: outer digest, all **925 top-level manifest entries**, all four nested manifests (230 each), commit/application bindings and scenario counts verified. Harness hashes are separately bound because the same harness is copied into both pinned worktrees; application files remain unchanged.

An additional identical-application repeat [36387689282](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36387689282) at head 01e523a measured uninstrumented 20 P95 2702.373 ms / 100 P95 9214.304 ms; correctness and SQL pass, 100 latency fails. Artifact **10955391844**, ZIP SHA256 `b349e72c12ef1a5e81f09f95ca48df6321d80dd5dce799df3071467fd88756f3`, manifests verified. This separate runner is not substituted into the paired comparison.

### Completed detailed diagnosis on current head

[Run 36389179938](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36389179938) completed at head **73534f71637bdc9cae43ee576687dedb828d8fb4**, application tree **57720ed0d057bdada9e6e702347e13b608afeeb5**.

- **21 PostgreSQL regressions passed**, zero failures/errors/skips.
- **13 correctness scenarios passed** in both uninstrumented and diagnostic rounds.
- Uninstrumented **20**: P95 **3127.058 ms**, P99 **3142.614 ms**, 0 unexpected errors, SQL PASS, gate PASS.
- Uninstrumented **100**: P95 **9001.165 ms**, P99 **9138.092 ms**, 0 unexpected errors, SQL PASS, gate **FAIL**.
- **250 / 500 / 1000 NOT RUN**. Thresholds remain P95 ≤5000 ms / P99 ≤10000 ms.
- Same bounded service-process scope: two processes on a 2-CPU / ~8 GB runner, shared PostgreSQL, synthetic providers/payment. HTTP/auth/multi-host/soak/production/million-online capacity NOT ESTABLISHED. CPU model string is AMD EPYC 9V74 80-Core Processor; allocated logical CPU count is **2**, not 80. Psycopg implementation is binary; complete installed versions are recorded.

Diagnostic 100-tier P95 **9343.598 ms**, not substituted for uninstrumented acceptance. The phase means below come from explicit sequential phase timers across all 100 successful actors; their P95s must not be added.

| Phase | Mean wall ms | Phase P95 ms |
| --- | ---: | ---: |
| Search/create and create replay | 3861.308 | 7267.057 |
| Payment checkout/capture | 395.210 | 667.712 |
| Concurrent capture replay + changed-amount rejection | 3073.084 | 5735.369 |
| Simulated supplier fact | 78.731 | 132.697 |
| Fulfillment START | 64.389 | 107.484 |
| Fulfillment COMPLETE | 74.783 | 173.992 |

Creation and concurrent replay account for **91.88% of mean measured phase wall time**. This is not a claim about real user checkout latency: this stress journey intentionally includes adversarial replay checks and synthetic fulfillment.

Per-process diagnostic observations at 100:
- Successful instrumented SQL statements **5900 each** (118/transaction); connection acquisitions/check-ins **1200 each** (24/transaction).
- Maximum acquisition **5.374 / 6.239 s**, maximum checkout-to-checkin hold **0.416 / 0.341 s**. Acquisition includes waiting, creation and pre-ping; it is not a pure queue-time measurement.
- Mapper configuration **0.768 / 0.732 s wall**, **0.656 / 0.633 s configuring-thread CPU**. First-use initialization alone does not explain the full 100-tier latency.
- Statement cache: **5838 hits/62 misses**, **5840 hits/60 misses**. Broad query-cache misses are not the dominant pattern in these observations.
- Process CPU **5.814 / 5.762 s**, measured windows **9.448 / 9.457 s**. Host busy fraction **92.88%** over the separately defined launch-to-completion window, including PostgreSQL and OS work. This is host utilization, not attribution of all CPU to GO.

**Next concrete bottleneck target:** investigate connection contention and transaction admission/queue scheduling around creation and adversarial capture replay, while also accounting for CPU cost. Fewer checkout SQL statements alone do not address the dominant observed wall-time phases. Any bounded-admission experiment must include queue time, report active versus queued work, keep the same invariants and thresholds, and must not relabel queued actors as simultaneously executing transactions. No such admission change has been implemented or accepted by this PR.

Evidence artifact **10956330960**, ZIP SHA256:
`342353659091c3fcc18360c4ca7c721092df6a56f9296ee36493058b9ba33091`.
Outer digest, all **230 normal + 236 diagnostic manifest entries**, head/tree bindings, scenario counts and JUnit verified locally. Earlier baseline/candidate comparison uses its separately bound identical harness; current diagnostic wrappers are isolated test code. Explicit service timings are inclusive and overlap; calling-thread CPU excludes spawned replay threads. SQL counts exclude driver ping/commit/rollback. No cProfile attribution is used.

Current-head [capacity foundation](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36389179934) and [ticket acceptance](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36389179949) completed SUCCESS. [Rental/attraction](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36389179925) is still running at this update and is not claimed passed. C13/C14 independent review on this head has not run. No merge or deployment.

Frozen ABBA is not rerun automatically unless its experiment definition changes. The current-head ABBA workflow therefore SKIPS the frozen comparison; its green workflow state is not a new capacity PASS. The measured ABBA evidence remains bound to 01e523a.

<details>
<summary>Earlier candidate evidence and investigation history (historical commits)</summary>

## Current candidate — correctness passes; performance NOT accepted (2026-09-28)

Head: `2fdea57fb1a8779ccabd6fbf5da96e3fa6554068`
Application tree: `57720ed0d057bdada9e6e702347e13b608afeeb5`

This iteration investigates the failed 100-concurrent tier. It removes duplicated reads while preserving full evidence-chain verification, ownership/expiry checks and payment state guards:
- Reuse fully verified evidence rows for cancellation-policy lookup; bound append-tail lookup with LIMIT 1.
- Combine RIDE ownership, policy, expiry and existing-intent reads under the native order lock.
- Reuse committed payment-service results with identity/payer/state checks; retain bounded conflict reloads and refusal of ambiguous outcomes.
- Add 4 focused regressions, SQL/acquisition/CPU metrics, and a separate diagnostic run. Normal staircase has instrumentation disabled.

**Acceptance decision: keep this candidate in Draft. Do not merge/deploy or claim improved latency.** Measured operation counts fell, but current uninstrumented latency is worse than the previous uninstrumented run. Separate CI runs do not establish causation; a controlled same-run baseline/candidate comparison is needed before retaining these changes as a performance improvement. Do not loosen thresholds, enlarge resources or skip failed tiers.

### Verified results

[Current run](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36382432147) completed. Workflow FAILURE is the expected enforced latency gate, not a passing capacity result.

- PostgreSQL regression JUnit: **21 passed, 0 failures/errors/skips**.
- **13/13 correctness scenarios passed**, in both normal and diagnostic runs. This includes last-unit contention, concurrent first checkout, idempotency, cancellation/payment races and natural-lease recovery after simulated money commit/process termination.
- Normal run: two service OS processes on the same 2-core, ~8 GB CI host, shared PostgreSQL 18.4; pool 5/process, overflow 0. No HTTP/auth, physical multi-host, real supplier/PSP, sustained-load or production-capacity proof.

| Concurrent transactions | P95 ms | P99 ms | Completed/s | Unexpected errors | SQL invariants | Gate |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 20 | 2865.644 | 2892.477 | 6.901 | 0 | PASS | PASS |
| 100 | 9968.377 | 10054.408 | 9.870 | 0 | PASS | FAIL |
| 250 / 500 / 1000 | — | — | — | — | NOT RUN | BLOCKED |

Unchanged thresholds: P95 ≤5000 ms, P99 ≤10000 ms; first failure stops progression.
Previous uninstrumented c1da061 run: 20 P95 1846.794 ms, 100 P95 6925.523 ms. **No latency improvement demonstrated.**

### Diagnostic evidence and limitations

Profiling baseline `32543ee3e66210b29aa02c801f6c8630f5bb2197` has unchanged c1da061 application tree. It measured 126 SQL statements / 28 connection acquisitions per full synthetic transaction. Current candidate measured **118 / 24**, consistently at both 20 and 100 tiers (6.35% and 14.29% fewer respectively). These counts do not establish faster user requests.

Current diagnostic 100 tier: P95 10425.796 ms / P99 10563.483 ms, 0 unexpected errors, SQL PASS, gate FAIL. Instrumented timings are not substituted for the normal acceptance run. Acquisition timing includes queueing, creation and pre-ping; concurrent wall-time sums are not additive CPU time. Initial baseline cProfile function timings had ambiguous cross-thread attribution and were discarded for bottleneck claims; current profiler omits cProfile. Valid SQL counts, pool acquisition measurements and process resource counters are retained.

Next investigation is controlled baseline/candidate comparison on one runner, followed by attribution of connection holding, CPU and initialization costs; any cold/warm comparison must be explicitly labeled. Keep the full transaction and accounting checks in acceptance measurements.

### Evidence binding

Current artifact ID **10953398262**, retained until 2026-10-28; downloaded ZIP SHA256:
`5c09cfcf5df607f2ed2556b100bdb714d3630c7f5f65e22f8c41c15301379e41`.
Both bindings match the head/application tree above. All **230 normal + 234 diagnostic manifest entries** verified locally; regression JUnit inspected.

Baseline diagnostic [run 36381520559](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36381520559), artifact **10953256947**, ZIP SHA256:
`6e0fd79e1844e101255d650b8ef4a9bf3222b3bb1bf319ff912b150800af1bb9`.
Baseline diagnostic timings are not compared as uninstrumented capacity gains.

Current-head companion workflows completed SUCCESS:
- [Capacity foundation](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36382432182)
- [Ticket preinventory](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36382432146)
- [Rental/attraction](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36382432249)

No merge, main write, deployment, HK shell access, provider credentials or live financial operations. C13/C14 independent review for this head has not run.

<details>
<summary>Historical c1da061 acceptance record and earlier discovery (not current-head results)</summary>

## Current candidate — independent-process transactions (2026-09-28)

Head: `c1da06116a8943a78bb1080b3737232d7eb5e955`  
Application tree: `524c251253847faabdd3ecfe266b91b54c87f321`

**Correctness passes for the tested service-level scenarios. The capacity gate remains RED: the 100-concurrent-transaction tier exceeded its predeclared P95 limit. No higher tier, merge, or deployment was performed.**

### Defect found and fixed

The added first-checkout contention test exposed real failures in the preceding candidate `2c197ea4d28bad4b4f28677ce1825b982d92eff7`: among 20 concurrent RAIL checkouts there were 4 source-decision unique-key errors, 9 payment-root creation conflicts, and 1 premature money-graph failure. Six requests succeeded. The observed money graph had one authorization and one capture, not duplicate charges; nevertheless the correctness gate failed and no load tier ran.

This change:
- Makes identical source decisions reuse the database-enforced decision hash.
- Resumes an already-committed payment root when another worker wins its creation, retaining order/payer binding.
- Reloads committed simulator state before progressing to money movements, resumes the existing simulator attempt, and prevents stale channel selection from resetting an active attempt to READY.
- Retains bounded, fail-closed behavior for unknown/failed payment states and another payer. It adds no external PSP execution or blanket SQL/network retry.

### Verified results on the current head

[Multi-instance run 36379543561](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36379543561):
- 8 PostgreSQL regression tests passed: new committed-attempt recovery / unknown / failed / wrong-payer tests plus existing payment-inventory handoff tests.
- 13 independent-process correctness scenarios passed. Rail and attraction initial checkout each returned 20 successful responses with one successful payment intent and one successful attempt. Hotel/rail/attraction last-unit contests each had one winner and 19 inventory rejections. Same-key creation, capture replay, both sides of payment/cancellation, and refund process-death recovery passed.
- Refund recovery waited for the real persisted 30-second lease; neither the clock nor lease row was edited. One committed refund was retained.
- Hotel room-night rows were reconciled against held reservation nights; rail/attraction capacity against claims; all tested money movements against debit/credit entries.

| Concurrent RIDE transactions | Unexpected failures | P95 | P99 | Observed peak in flight | SQL checks | Gate |
|---|---:|---:|---:|---:|---|---|
| 20 | 0 | 1,846.79 ms | 1,862.45 ms | 20 | PASS | PASS |
| 100 | 0 | 6,925.52 ms | 7,007.06 ms | 100 | PASS | FAIL — P95 > 5,000 ms |
| 250 | — | — | — | — | NOT RUN | BLOCKED |
| 500 | — | — | — | — | NOT RUN | BLOCKED |
| 1,000 | — | — | — | — | NOT RUN | BLOCKED |

The 120 completed load orders reconciled to 2,016,000 minor units on each side of the ledger. Throughput in these bounded bursts was 10.67 and 14.25 completed transactions/second respectively. Latency includes creation, replay checks, payment/capture, synthetic supplier confirmation, and fulfillment. The thresholds were fixed before execution: zero unexpected failures, correct ledgers, P95 <= 5 seconds, P99 <= 10 seconds. They were not relaxed after a failure.

[Capacity foundation run 36379543461](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36379543461) also passed on this head: 13 planning-model tests, 17 pool/bootstrap boundary tests, and 61 shared-role/registration/hotel-business-day tests. These counts are suite executions, not a claim of unique global coverage.

### Reproducible scope and evidence

Environment: 2 CPU cores, approximately 8 GB RAM, PostgreSQL 18.4, Python 3.12.14, two independent service processes each with pool size 5 / zero overflow. Each stage is one bounded burst. Database, source commit/application tree, process IDs, observed overlap, raw successes and failures, SQL facts, installed key package versions, and SHA256 manifest are included.

This is **service-process transaction evidence**, not HTTP/authentication/load-balancer testing, multi-host failover, a soak test, all-vertical capacity, live supplier/PSP testing, or proof of one-million-online capacity. The load journey is RIDE; the other verticals listed above are correctness scenarios. The 100-tier bottleneck still requires CPU/query/pool-wait profiling; no unsupported attribution to Python or PostgreSQL is made.

Downloaded ZIP digests and every internal evidence-manifest entry were independently checked; binding JSON matches the head and application tree above:

- [Current transaction evidence](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36379543561/artifacts/10952073968), artifact `10952073968`, SHA256 `6e9a556589510a6988e9e4782165bdd9dbe51bd6d9ffaede4eb9889bd9220a40`.
- [Current foundation evidence](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36379543461/artifacts/10952078943), artifact `10952078943`, SHA256 `ad3a0c541406843659536a35c21a51445031bc12b0b205cf126db40ff9dc5f53`.
- [Pre-fix first-checkout failure](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36379113900/artifacts/10951744415), SHA256 `2c9b696ffc188d7d3ab5f375269a558b8994b7e824106a479ba6d035e65c96c2`.
- Earlier bounded run `36378736906` / artifact `10952062659`, SHA256 `115f816d48843dcbca8632c9ee555c34848b253e7a13723211084ee1ae7ce2c5`, passed the initial 11 scenarios and stopped at 100 on latency; superseded by the stronger first-checkout gate.
- Initial harness run `36378550418` / artifact `10952131546`, SHA256 `4fd8c64c44db3beaf70f72b22f28a965d9b7bfac5638b41a12134842791edb2d`, rejected an oversized synthetic party before concurrency. The fixture was corrected without relaxing business rules.

Artifacts currently expire on 2026-10-28. Harness, regression tests, workflow, and fixes are versioned in this PR. [Ticket workflow 36379543504](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36379543504) has all six jobs successful on this head (core, shared, resolution, coupons, browser, native-source). In [rental/attraction workflow 36379543460](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36379543460), rental, recovery, independent, and browser jobs passed; attraction was still running at this update and is not represented as passed. C13/C14 on this final candidate have not run. PR remains draft.

Next capacity gate: profile the 100-tier latency on a specified resource budget, address the measured bottleneck, then rerun from 20. Do not skip to higher tiers or infer production capacity from this runner.

<details>
<summary>Historical capacity-foundation baseline and evidence (superseded head 1923d3c)</summary>

## Purpose
Continue useful development while the independent review API is unavailable. Integrate main 2b486354 with frozen product candidate #273 cb96de65 without moving either input. Three-way tree comparison found no conflicting files; retain all 44 main-only changes and all candidate changes. First parent is main, second parent is #273. PR comparison base is #273 for focused review; it is not a production merge target.

## Changes
- Explicit finite PostgreSQL pool size, overflow, wait and recycle settings; preserve previous defaults and SQLite semantics. No implicit transaction retry.
- Offline million-online workload calculator and aggregate database connection budget checker including all seven background workers, maximum replicas, process count and rollout surge.
- Isolated PostgreSQL pool exhaustion/recovery plus integrated hotel business-day, registration/privacy and six-vertical three-role regression CI. Existing ticket/rental/attraction CI is also applicable.
- Architecture assumptions, phased capacity gates and remaining business/operational gaps in docs/architecture/MILLION_ONLINE_20260928.md.

## Validation
Local: capacity model 13 passed; pool/bootstrap 13 passed, 4 PostgreSQL cases skipped locally. Concurrent first-start bootstrap was reproduced failing on original implementation (username unique violation), then fixed without overwriting existing credentials/roles; unrelated integrity failures still propagate. These are foundation checks, NOT throughput evidence. All four exact-head CIs completed SUCCESS: capacity 36374013044; tickets 36374013020; rental/attraction 36374013014; monitor 36374013018. Earlier 166d749 runs are superseded, not acceptance of this head. Current candidate 1923d3ce336e1e7bb9d610539bce7b15f6811feb; application tree dbed2afc103986821749e15e859d0bc95140a666. First parent main, additional parent preserves the initial integration and #273 ancestry. All 11 new/modified blobs read back exactly; entire resulting tree matches the conflict-free three-way assembly plus these changes. Prior CI/C13/C14 results do not transfer.

## Classification and limits
New changes: PRODUCT_FIX, TEST_ONLY, BUILD (CI), DOCUMENTATION. Retained integration includes original PRODUCT_FEATURE/MIGRATION/INFRASTRUCTURE and main control-plane/governance changes; full-scope independent review must use first-parent diff to main, not only this PR diff. No new runtime topology enabled; no new schema in foundation changes.
No merge, deployment, live supplier/PSP, email, credentials or paid review API calls. C14 remains externally blocked in its last verified run, C13 not executed for this candidate. Full business-depth matrix, physical devices, multi-instance transactions and million-online load test remain incomplete.

## Final raw-evidence verification — 2026-09-28
All downloaded ZIP digests match GitHub artifact SHA256. Internal SHA256 manifests match archived files where present; source bindings match candidate 1923d3ce336e1e7bb9d610539bce7b15f6811feb / application dbed2afc103986821749e15e859d0bc95140a666. Complete repository tree readback matches the three-way assembly and all 11 authored changes.

| Suite | Passed | Failures/errors/skips |
|---|---:|---|
| Capacity arithmetic |13|0/0/0|
| Pool and bootstrap boundary checks |17|0/0/0|
| Existing three-role facts, privacy and hotel business day |61|0/0/0|
| Ticket core/resolution/shared/coupons |74+96+49+54 = 273|0/0/0|
| Rental/attraction/recovery/independent regression |120+168+70+43 = 401|0/0/0|
| Isolated Chromium flight journey |7 steps|0 errors|
| Isolated Chromium rental/attraction journey |29 steps|0 errors|

Counts across suites overlap and are NOT a unique-scenario completeness total. PostgreSQL 18.4 used by database jobs; dedicated SQLite compatibility cases remain SQLite, browser runtime is isolated SQLite with synthetic suppliers and outbound denial. Native type/contract checks passed; physical devices NOT RUN. No throughput or million-online capacity claim. This is developer verification, NOT a new C13/C14 opinion.

## Immutable artifact index
- 10950387773 — capacity-foundation-1923d3ce336e1e7bb9d610539bce7b15f6811feb: `sha256:89fea0e454663222b11738852f0db964fc5f9569fa2cb99da89e540fbcf6b77a`
- 10950795095 — ticket-native-source-1923d3ce336e1e7bb9d610539bce7b15f6811feb: `sha256:89f0ef72b66aa6418f09ca655e1ead8e667260fea324d39f85d8ded00f5e805a`
- 10950112588 — ticket-preinventory-1923d3ce336e1e7bb9d610539bce7b15f6811feb-shared: `sha256:a1f0c9e681cd16fcfaba593699daf142b434319e8b13d8e6ea2e40377528141a`
- 10949933195 — ticket-preinventory-1923d3ce336e1e7bb9d610539bce7b15f6811feb-coupons: `sha256:3b0fde260a4774dfebfd399ebf1629c4cea97aa39da3bac6559843212b602e15`
- 10949688528 — rental-attraction-preinventory-1923d3ce336e1e7bb9d610539bce7b15f6811feb-independent: `sha256:7dfe118177169067ec9898624641e40262ebb75cd7f597b66ba4d228e8bb4a47`
- 10950875049 — ticket-preinventory-1923d3ce336e1e7bb9d610539bce7b15f6811feb-core: `sha256:f2b8ee47f8c1d233dc06a74ae3ff20554e43b3db0631450b8176b5b7db5203c8`
- 10950407874 — ticket-preinventory-1923d3ce336e1e7bb9d610539bce7b15f6811feb-resolution: `sha256:0e70ba5920c0f4de2bf6b739703e804f3d2f11392d17c4200bee55f88c7661c3`
- 10950616352 — rental-attraction-preinventory-1923d3ce336e1e7bb9d610539bce7b15f6811feb-recovery: `sha256:b47f971e7934041276d289f9967536ada0f65987dbead9f0a43b971ce2cf64cf`
- 10950756279 — rental-attraction-preinventory-1923d3ce336e1e7bb9d610539bce7b15f6811feb-rental: `sha256:2462a3d4784f537d588d3aaf714bd3c0b5ddb1af581001d9eb1ff32cb12970ff`
- 10949788738 — rental-attraction-preinventory-1923d3ce336e1e7bb9d610539bce7b15f6811feb-attraction: `sha256:963b9201f51f5f8cddafbcfc8adbc9256f502d4fd51bc52e1b786f18052e9804`
- 10950377422 — ticket-browser.zip: `sha256:35603e9f8da7f9c7053e4fc60ddba5aa4304158b0f1e84cae809b72f3e9e09d9`
- 10949694890 — rental-browser.zip: `sha256:afcbccfa24dfe4e2e42ff4ef1cd16722327c61fa696da8c9646fc590bfc87674`

## Remaining work
- Full vertical business-depth denominators remain incomplete: operational SLA/dispatch/takeover/recheck, complete role/exception matrix, attraction policy consumption, full rail browser flow and native-device acceptance.
- Capacity foundation is implemented; horizontal multi-instance transaction tests, traffic shaping, provider isolation and staged load tests (up to the one-million-online model) remain to be implemented/executed.
- C14 API restoration, independent C14/C13 on the final candidate, and unresolved approved legal/operational/age-policy evidence remain separate gates. No merge/deployment performed.


</details>


</details>


</details>


</details>


</details>

</details>

</details>
</details>

</details>
</details>
</details>

