# Process/pool attribution result — 2026-09-30

Source `4c83c1692a1c5ef21dd67503409f3ccdccba467f`; restored application
tree `6570b66bc977f89c0311d67bdc6b721cd70d4e09`. Four vCPU,16GiB,
Python3.12.3, PostgreSQL18.4. The eight uninstrumented rounds used mirror
order A B D C C D B A. Each configuration therefore has two samples.

250 original PostgreSQL regressions and35 harness tests passed with no
failure, error or skip. Every main and diagnostic round passed13 money,
idempotency and recovery scenarios, exact20/100 actor overlap, zero transaction
errors and SQL/ledger checks. The raw archive SHA256 is
`d78709abb6b92045db626bf499bba01228ab2ce61db89a82093dc4eb7ba1dd86`.
Independent readback verified4,757 manifest entries, all8 main rounds and4
diagnostic rounds, raw percentiles, process identities, CPU, RSS and ledgers.

## 100-actor uninstrumented medians

|Processes x pool|Worker connections|P95 ms|P99 ms|Application CPU s|Lifetime CPU s|Sum worker RSS KiB|
|---|---:|---:|---:|---:|---:|---:|
|2x4|8|5417.483|5480.443|9.746|16.244|369096|
|4x2|8|5438.700|5501.940|11.548|29.599|738144|
|2x8|16|5990.962|6018.018|11.340|17.595|368752|
|4x4|16|4889.899|4911.536|11.846|29.992|738656|

Both4x4 samples passed the5-second P95 gate:4929.514ms and4850.284ms.
Both2x4 and2x8 samples failed.4x2 was unstable:5906.061ms FAIL then
4971.340ms PASS. At fixed8 worker connections, moving2x4 to4x2 changes median
P95 by+0.39%, so process count alone is not the solution. At two processes,
doubling the pool from4 to8 worsens P95 by10.59%. Only the4-process,
4-connections-per-process interaction produces a repeatable sub-5-second result.

Relative to2x4,4x4 reduces P95 by9.74% but increases application CPU by21.54%,
whole-child lifetime CPU by84.63%, and aggregate worker RSS by100.13%. This is
a resource/topology capacity candidate, not a CPU optimization. It does not
meet the prior code-candidate CPU/P95 improvement targets.

## Separate diagnostics

Instrumentation is excluded from latency acceptance. At100 actors, observed
overlapping pool-queue sums were452.978s (2x4),398.695s (4x2),480.307s
(2x8), and343.654s (4x4). These sums overlap across actors and are not elapsed
transaction latency. PostgreSQL sampling showed substantial idle and idle-in-
transaction ClientRead observations; WAL waits were secondary. The evidence
supports per-process pool contention plus process/pool interaction, not a claim
that PostgreSQL compute is saturated.

## Decision

Freeze4x4 as the only capacity configuration candidate. Do not modify application
logic, enlarge the pool beyond4, or adopt4x2/2x8. Before configuration adoption,
repeat the full cold/continued journey and a formal100-actor gate on the fixed
4x4 configuration, report its doubled memory and higher CPU requirement, then
continue higher load only if those gates pass. Original2-vCPU and original
2-process configurations remain failed. No merge, deployment, C14/C13, live
PSP/supplier access, or production capacity is authorized by this experiment.
