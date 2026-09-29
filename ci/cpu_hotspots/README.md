# CPU hotspot discovery

This diagnostic wrapper leaves the application and formal harness unchanged. It
runs one uninstrumented control then one Yappi 1.7.6 CPU-clock probe on a single
runner. Every fresh schema first runs all 13 multi-process correctness scenarios,
then the original full 20 and 100 actors, stopping on the first original P95/P99
failure. The instrumented 20 tier may stop before 100 because tracing adds cost;
that must be reported, never bypassed. These rounds discover functions, not an
optimization comparison or capacity acceptance.

The existing experiment mode bounds the plan to 20/100 at the unchanged default
5 ms worker interval, pool 5, overflow 0. CPU/RSS process counters are retained in
both rounds. Yappi is installed only in isolated CI, not application dependencies.
It uses native-thread CPU contexts and includes the two money replay threads for
each actor. Exclusive CPU avoids nested double counting; inclusive columns overlap.
The CPU profile starts after service imports and includes thread/barrier setup and
result serialization; profile export occurs after measured work. Function data
contains source/function identities and counters only, no call arguments/locals.

Tests qualify concurrent CPU-vs-sleep accounting, nested and replay call counts,
and exception cleanup. Standard cProfile/profile multi-thread approaches were
rejected locally after interpreter tool conflicts/inconsistent stacks. The pinned
Yappi keyword wrapper ignores ctx_id=0; its supported compatibility filter dict
preserves that context and is covered by per-context call reconciliation.

Adoption remains a separate same-runner, uninstrumented baseline-candidate-
candidate-baseline comparison: app CPU -20%, P95 -15%, P99 no worse, RSS +10% at
most, unchanged pool/semantics and all transaction correctness/SQL checks. A
candidate meeting that budget still needs the unchanged formal staircase.
