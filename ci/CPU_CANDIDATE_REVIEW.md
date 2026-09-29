# CPU candidate screening — 2026-09-29

The three independent AI reviews (Python/CPU, transaction architecture, benchmark evidence) agree: no measured application candidate currently supports both CPU -20% and P95 -15%. This is a screening outcome, not a performance improvement or capacity acceptance. Keep Python and preserve transaction locks, money validation and durable recovery boundaries.

## Evidence

Application tree `fd0122ada33d5351c533fb86152b5b230b45f74b`, verified commit `aea10bea01e0bd2cc6edd71ff25945fbf6ea757f`.

- Formal run [36531184568](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36531184568): 208 PostgreSQL regressions and 13 independent-process correctness scenarios pass. Normal 20 actors P95/P99 2108.618758/2124.688535 ms; 100 actors 7111.184149/7133.234484 ms. Zero errors, SQL PASS. Stop at 100; 250/500/1000 not run.
- Final artifact `11017750990`, SHA256 `44cbee7a2c50fce329e7798637733be668f5b14209f10f0bf9b4dc643964a5b6`: 466 manifest entries, raw percentiles, 280 cumulative SQL facts and 10 source/test/migration files verified.
- CPU discovery [36531184622](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36531184622): AMD EPYC 7763, separate from formal Intel runner. Control 20 CPU 3.771471 s, P95 2621.256184 ms; control 100 CPU 11.327697 s, P95 8670.563729 ms. Full-thread Yappi 20 CPU 14.029806 s, P95 7757.431705 ms. Profile 100 was not run after 20 failed latency. No cross-runner improvement claim.
- Discovery artifact `11016870621`, SHA256 `cce77ffa670ac52078f4210272f26f70087ed2a344af5820dc3c71c2fd086a77`: 1221 manifest entries, 160 cumulative SQL facts, two 31-context profiles and per-context function call totals verified.

## Decisions

| Candidate | Evidence and decision |
|---|---|
| ORM mapper initialization | 563 models per process; Yappi inclusive 6.124 CPU seconds across two workers. Observation overhead is substantial. Moving initialization before timing is cost relocation, not CPU savings. Do not select as the 20% candidate. |
| Output/JSON, ORM row hydration, further compiled SQL caching | Small measured scope or already high cache hit rate. No adequate improvement budget. Reject for this round. |
| Payment orchestration | First investigation target. Inspect same-transaction redundant reads and repeated ORM/driver work. Do not merge durable commits, skip payer/amount/state checks or cache business facts across transactions. No implementation approved yet. |
| Supplier lifecycle repeated read | Potentially one read saved, but lock ordering, absent-row races and recovery must remain intact. Insufficient current budget. |
| Supplier money graph O(n²) validation | Real history-growth candidate: aggregate children by parent once while retaining every validation. Standard workload has only authorization + capture; not evidence of current 20% savings. |
| Language rewrite / registry partition | No evidence of benefit sufficient for the scope and risk. Retain Python. |

A 15% P95 gain from the latest formal 100 result would still leave 6044.506527 ms. Passing the original 5000 ms gate requires approximately 29.69% improvement. Budget screening and formal acceptance are separate.

## Reproducible candidate gate

`cpu_candidate.py` compares baseline `8783807edd131d87af8d598f4edc4b869763ea54` using baseline/candidate/candidate/baseline on one runner. Each round uses identical frozen harness files, fresh schema/processes, two instances, pool 5 / overflow 0, unchanged 5 ms worker interval, 13 correctness scenarios and the original 20/100 stop gates. There is no per-call profiler. CPU is the sum of worker user+system boundary counters for 100 complete cold synthetic RIDE actors, after imports through result serialization; RSS is maximum worker lifetime high water.

A candidate must be explicitly bound by `candidate_application_tree` in `cpu_candidate.json`. It is currently null. Identical application trees, unbound candidates and test/document-only changes produce NOT_EVALUATED with no budget. A green qualification workflow does not mean performance improved.

Before arithmetic, reuse the existing raw-evidence verifier to check manifests, binding, 13 scenarios, exact percentiles, timing, raw SQL ledger facts, PID alignment, exit status, stop rules, pool/interval and separate schemas. Reject nonfinite/nonpositive aggregate metrics and incomplete/reordered ABBA rounds. Report per-round data, ranges and paired direction as well as medians. Require median CPU <= 0.80, P95 <= 0.85, P99 <= 1.00 and max-worker RSS <= 1.10 relative to baseline.

The gate never authorizes adoption. Review startup/import cost relocation, per-round variability and transaction semantics before a new original formal staircase. Two rounds per label are screening evidence, not a statistical stability claim. Any startup-moving candidate needs whole-process CPU evidence before savings can be claimed.

## Next discriminating measurement

Use low-perturbation CPU attribution for complete 100-actor payment orchestration, separating cold configuration and recurring costs. Before implementation, establish a removable cost budget large enough to explain 20% of total measured CPU; inclusive nested functions must not be summed. The previous lighter wrapper's checkout share of roughly 38% is a directional estimate, not transferable to this runner: if reproduced, reducing total CPU by 20% would require roughly 53% reduction in that path. One or two removed queries do not establish that budget.

Full-thread Yappi is retained for discovery only. A follow-up single-thread Yappi mode failed local qualification with invalid CPU values and was discarded; it never entered the branch. The safe diagnostic files were restored exactly to the verified commit. No production code, pool sizes, transaction rules, formal gates, deployment or real supplier/payment access changed in this review.
