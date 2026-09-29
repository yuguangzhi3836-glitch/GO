# Payment query reuse decision — 2026-09-29

## Decision: revert the query-reuse candidate

The P95 median improved 23.39%, but application CPU improved only 6.88% and whole-worker lifetime CPU only 4.09%, both below the required 20%. All 100-actor original-workload samples still exceed 5 seconds. Restore the complete baseline application tree `6570b66bc977f89c0311d67bdc6b721cd70d4e09`, including removal of the experiment-only test; retain the rejected code at commit `667bb17b33b5b71f4ecadbb1f71c8d90f7930d83`, the harness and all raw evidence. This does not revert earlier accepted draft history-scaling or correctness repairs.

Artifact `11026938663`, ZIP SHA-256 `49aa9aedfe8d6bea8b6b0d4b933507366ca487e072313e5812a8da5721a24b42`; all 2,545 manifest entries verified. Runner: two vCPUs, AMD EPYC 9V74, Python 3.12.14, PostgreSQL 18.4. Four isolated PostgreSQL query-reuse safety tests passed. The 31 harness qualification tests passed in CI.

Separate original formal run `36554038879` on the rejected candidate passed 250 PostgreSQL regressions and 13 correctness/recovery scenarios. Cold 20 P95/P99: 2622.210/2661.023 ms. Cold 100: 8957.078/9048.148 ms, zero errors, SQL PASS, latency FAIL. Artifact `11027162715`, SHA-256 `8158a2cb813c917b13ff211a8b65bb1a074c326462ce3df61b8c51749ab3f9a3`; 230 manifest entries, raw percentiles, PIDs and ledger facts verified. Its different runner is not an A/B comparison.

Standalone supplement `36554038827` is not used for adoption: one 100-create continued batch reached only 97 simultaneous executions and therefore fails the strict supplementary concurrency verifier. The four ABBA supplements passed that verifier for every batch. No shortfall was hidden or relaxed.

The final review candidate must retain the full first-parent review boundary from `1960b51e86acefa45d0eacfce22e2b6a6245adcf`, with experimental head `667bb17b33b5b71f4ecadbb1f71c8d90f7930d83` as an additional parent, so C14/C13 see inherited mobile/registration scope plus the full capacity draft instead of only this rollback/report. C14/C13 use the existing main execution backend and Issue #270 lineage. Capacity and unresolved registration legal/operational gates remain HOLD. No merge/deployment is authorized by this measurement.

## Frozen experiment

Baseline: `ae2c3f99c8a455f7f60dab5c967a7af71b75536f`.
Experimental candidate: `667bb17b33b5b71f4ecadbb1f71c8d90f7930d83`.
Application trees: baseline `6570b66bc977f89c0311d67bdc6b721cd70d4e09`; candidate `4b99a7596ce8e509f306e42b7900138e6ce52336`.
Run: https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36554038895

Same runner, dependencies, PostgreSQL, two application processes, pool 5 / overflow 0. Four uninstrumented rounds in baseline/candidate/candidate/baseline order. All raw manifests, percentile calculations, CPU counters, PID/schema bindings and ledger facts independently verified after download.

## Original complete cold transaction workload

| Round | Version | Actors | P95 ms | P99 ms | App CPU s | Lifetime CPU s |
|---:|---|---:|---:|---:|---:|---:|
| 1 | baseline | 20 | 2194.054 | 2203.819 | 2.752894 | 8.778100 |
| 1 | baseline | 100 | 10561.143 | 10601.874 | 8.374202 | 14.412527 |
| 2 | candidate | 20 | 2038.672 | 2050.725 | 2.736184 | 8.737255 |
| 2 | candidate | 100 | 7058.280 | 7097.755 | 8.315546 | 14.498412 |
| 3 | candidate | 20 | 2558.795 | 2573.271 | 2.768718 | 8.830145 |
| 3 | candidate | 100 | 8849.209 | 8869.491 | 8.040040 | 14.147519 |
| 4 | baseline | 20 | 2347.213 | 2355.769 | 2.826294 | 8.916858 |
| 4 | baseline | 100 | 10203.370 | 10442.951 | 9.190470 | 15.455215 |

## Candidate screening, 100 full actors

| Metric | Baseline median | Candidate median | Candidate / baseline | Required maximum |
|---|---:|---:|---:|---:|
| cpu_lifetime_seconds | 14.933871 | 14.322965 | 0.9591 | 0.80 |
| cpu_seconds | 8.782336 | 8.177793 | 0.9312 | 0.80 |
| max_worker_rss_kib | 185772.000000 | 184938.000000 | 0.9955 | 1.10 |
| p95_ms | 10382.256445 | 7953.744505 | 0.7661 | 0.85 |
| p99_ms | 10522.412927 | 7983.622934 | 0.7587 | 1.00 |

Screening result: **CANDIDATE_BUDGET_NOT_MET**. Two samples per variant are screening evidence, not a general performance claim. Per-round ranges and both paired comparisons are retained in the raw summary.

## Cold and continued-process supplementary batches

Values below are medians across the two cold batches per version or the six continued batches per version. Raw evidence retains every batch, P95/P99, CPU, RSS, startup time and actual peak overlap. Three continued bursts are not a sustained-load capacity test.

| Actors | Operation | Version | Process state | P95 ms | P99 ms | App CPU s |
|---:|---|---|---|---:|---:|---:|
| 20 | full_transaction | baseline | cold | 2303.190 | 2325.522 | 2.615961 |
| 20 | full_transaction | baseline | continued | 1745.582 | 1783.152 | 1.292610 |
| 20 | full_transaction | candidate | cold | 2681.378 | 2682.185 | 2.603918 |
| 20 | full_transaction | candidate | continued | 1433.603 | 1449.280 | 1.205729 |
| 20 | create_order | baseline | cold | 855.763 | 858.797 | 1.483644 |
| 20 | create_order | baseline | continued | 253.488 | 254.010 | 0.203000 |
| 20 | create_order | candidate | cold | 980.222 | 983.762 | 1.464730 |
| 20 | create_order | candidate | continued | 183.846 | 186.182 | 0.197045 |
| 20 | payment_confirm | baseline | cold | 1703.759 | 1715.709 | 1.895468 |
| 20 | payment_confirm | baseline | continued | 1000.755 | 1001.593 | 0.561686 |
| 20 | payment_confirm | candidate | cold | 1478.803 | 1481.416 | 1.813773 |
| 20 | payment_confirm | candidate | continued | 601.701 | 602.852 | 0.499130 |
| 20 | order_query | baseline | cold | 704.794 | 706.043 | 1.304615 |
| 20 | order_query | baseline | continued | 60.192 | 60.591 | 0.072506 |
| 20 | order_query | candidate | cold | 725.117 | 726.004 | 1.319439 |
| 20 | order_query | candidate | continued | 55.869 | 57.380 | 0.072719 |
| 100 | full_transaction | baseline | cold | 9896.441 | 9976.893 | 8.681375 |
| 100 | full_transaction | baseline | continued | 8511.802 | 8542.221 | 6.730419 |
| 100 | full_transaction | candidate | cold | 7409.730 | 7488.915 | 8.164855 |
| 100 | full_transaction | candidate | continued | 7548.651 | 7614.596 | 6.384578 |
| 100 | create_order | baseline | cold | 1681.267 | 1700.604 | 2.381288 |
| 100 | create_order | baseline | continued | 986.061 | 1021.875 | 1.030581 |
| 100 | create_order | candidate | cold | 1688.475 | 1711.965 | 2.371760 |
| 100 | create_order | candidate | continued | 885.483 | 915.493 | 1.012242 |
| 100 | payment_confirm | baseline | cold | 4707.508 | 4772.110 | 4.361573 |
| 100 | payment_confirm | baseline | continued | 4130.973 | 4177.603 | 3.004838 |
| 100 | payment_confirm | candidate | cold | 3715.255 | 3767.201 | 3.871619 |
| 100 | payment_confirm | candidate | continued | 2713.898 | 2786.291 | 2.567544 |
| 100 | order_query | baseline | cold | 934.457 | 940.055 | 1.602794 |
| 100 | order_query | baseline | continued | 290.568 | 296.313 | 0.367226 |
| 100 | order_query | candidate | cold | 955.595 | 970.323 | 1.642621 |
| 100 | order_query | candidate | continued | 277.363 | 287.761 | 0.364745 |

## Correctness and boundaries

Every ABBA round passed the 13 original money/idempotency/recovery scenarios, with zero unexpected transaction errors, complete ledger checks, and actual full-transaction overlap of 20 and 100. Supplementary batches passed raw timestamp/CPU/PID checks and 960 order reconciliations per round.
Original cold-workload P95 <=5,000 ms and P99 <=10,000 ms remain authoritative. No higher tier, capacity acceptance, merge or deployment is authorized by this report.
Application-process cold does not imply cold database/OS caches. Application CPU excludes PostgreSQL; lifetime CPU includes imports. Supplementary operation timing excludes fixture preparation. Phase percentiles cannot be summed. This is synthetic service-layer RIDE, without HTTP/auth/network or real PSP/supplier calls.
