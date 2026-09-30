# Process versus pool attribution

User-authorized isolated follow-up to the unsuccessful four-vCPU experiment.
Fixed restored application tree6570b66b, same4-vCPU Codespace and existing
Python3.12 environment. No application, formal harness or workflow change.

Configurations A=2 processes x4 connections, B=4x2, C=2x8, D=4x4.
Run A B D C C D B A,20 then100 each; every round reruns13 money/recovery
scenarios. No overflow, admission throttling or higher tier. Compare A/B and
C/D for process parallelism at fixed total8/16 worker connections; A/C and
B/D for pool effect at fixed process count. Coordinator pool stays5.

Four additional diagnostic runs are separate from latency acceptance and sample
PostgreSQL backend state/wait events, connection-pool queue time and per-service
costs. Sampling counts are observations, not precise accumulated server wait
durations. Queue sums overlap across actors and are not elapsed latency.
Application process CPU excludes PostgreSQL; whole-child lifetime CPU includes
imports. Record aggregate worker RSS so4-process memory costs remain visible.

This is cold-process causal screening, not production or formal capacity proof.
Even a result under5s does not authorize adoption: repeat cold/continued journeys,
regressions, the original formal gate and fixed-candidate C14→C13 first.
Changes to actual deployment topology are outside this experiment.
