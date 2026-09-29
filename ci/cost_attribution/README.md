# Same-window cost attribution (diagnostic only)

This entry point reuses the exact complete RIDE actor and the 13 multi-process
correctness scenarios from `ci/multi_instance`. It does not change or replace the
formal 20/100/250/500/1000 staircase. Each of four fresh-schema rounds runs the
correctness prerequisites, then 20 and (only after 20 passes) 100. Diagnostics stop
at the original P95 5,000ms/P99 10,000ms limits. A green diagnostic workflow means
observations are complete, never that capacity passed.

Control/observed/observed/control on one runner estimates added observation cost.
Every round uses the same two fresh service processes, pool 5, overflow 0, original
thread switch interval and original full actor including concurrent money replays.
The sampler (100ms target interval) and client cursor/commit/hold/queue events are
only enabled in observed rounds. Boundary process counters and server statement
statistics are collected in both. `pg_stat_statements` and I/O timing are enabled
only in the disposable diagnostic Postgres container; worker statement planning
tracking is enabled in both modes. The formal gate's database settings are untouched.
Consequently this ABBA estimates added observer cost under that diagnostic server
configuration; it does not measure all extension overhead versus the formal gate.

Workers import services before readiness, as in the original harness. After all
threads are ready, the coordinator samples application PIDs, Postgres container CPU
counters, host CPU, and server statement counters, then releases workers. Workers
keep processes and connection pools alive after completing actors. Only after the
shared ending sample are they released to exit. Every actor must fit inside those
recorded host-monotonic bounds; a burst without full actor overlap is invalid.
Raw snapshots retain their read spans. App CPU resolution is host clock ticks;
Postgres container counters include background and observer backend work. Process
snapshots can undercount transient backends, so container CPU is authoritative.

Sampled state/wait class/blocker counts are occupancy observations, not exact wait
seconds or proof of active CPU. App client cursor and commit wall times contain
loopback transport and scheduling. Holds overlap these times and concurrent waits
overlap one another. Do not sum them as CPU or subtract server execution to infer
GIL cost. Server query IDs and numeric counters are retained without SQL text or
parameters; query IDs cannot be compared across different fresh schema object IDs.

A fresh-process probe invokes the actual FastAPI lifespan with expiry background
workers disabled for isolation. It records mapper counts/events before main import
and at readiness on the installed target SQLAlchemy version. This is startup
evidence, not a warm-latency substitute or HTTP capacity result. Existing cold-gate
failures stay valid. Multi-host, real PSP/supplier, sustained traffic, authentication,
HTTP admission, and million-online capacity remain separate acceptance work.

Run contracts: `python -m pytest ci/cost_attribution/test_observe.py -q`.
CI binds source commit/application tree, sanitized loopback-only database, packages,
settings, raw actors/SQL reconciliation, snapshots, events and SHA256 manifests.
