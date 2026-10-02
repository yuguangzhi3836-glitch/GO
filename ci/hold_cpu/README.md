# Connection-held CPU attribution — diagnostic candidate

Change class: TEST_ONLY + DOCUMENTATION. No application, pool size, transaction,
commit boundary, schema, workload, acceptance threshold or runtime change.

## Why this next step

PR317 R3 completed the fixed 4x4 ABBA and was rejected: formal 100-actor P95
5581.143 -> 6192.738 ms; application CPU 11.751204 -> 11.531660 seconds
(-1.87%). It must not be adopted. Earlier across-commit connection reuse was
also rejected; do not extend leases or retry those candidates without new evidence.

The immutable R3 raw ZIP at evidence commit
`3173cd94e0a1377c6dcde5442d27f56517d51c65`, path
`ci/ride_query/evidence/afb6c469d518/raw.zip`, has SHA256
`1be3458c68a141050454bd1708878efa9d4921f364f1e58c1e8c57aa1e2ba5cb`.
`recompute_r3.py` checks that digest and reads four worker profiles per round
without extracting the archive. `R3_CPU_ATTRIBUTION.json` is its actual output.

Historical baseline median, 100 completed transactions, four processes:

- ride.create exclusive tracked-service CPU: 3.822 seconds.
- money.create plus create_in_session exclusive CPU: 1.525 seconds.
- first ORM configuration CPU: 2.801 seconds, overlapping the above services.

The mapper records lack service/lease identity. They do **not** prove all mapper
cost happened in ride.create or while a connection was held. Likewise 238.879
seconds of summed concurrent money pool waiting is not 238.879 CPU seconds.
R3 used a historical application; these readings are not PR320 performance.

## What this patch measures

`HoldCPU` records calling-thread CPU and monotonic wall time only while that
thread holds at least one SQLAlchemy pool lease. Nested phase buckets are
exclusive: dbapi.execute, commit, rollback, ORM configure, tracked service body,
and other_while_held. Checkout/checkin and phase transitions split intervals;
work before checkout, including initial queue waiting, is excluded. Two leases
on one thread count its CPU once. Cross-thread returns, unbalanced leases or
unfinished phases invalidate the report. Failed SQL unwinds its phase while
preserving the original exception. It records no SQL, arguments or row values.

The observer includes its own overhead and is for synchronous isolated workers.
Do not use it on production, asynchronous tasks sharing one thread, or alongside
another consumer of the same mutable service methods. Call snapshot only after
workers have joined; close removes its own event listeners/method wrappers.
The existing Metrics collector has its own lifetime and cleanup semantics.

## Integration into the existing isolated diagnostic worker

Use the fixed R3 harness (`afb6c469d518bd2386846fe3c9c7a2d6548f9aca`) or a
separately verified compatible harness, binding the chosen application SHA/tree.
This PR deliberately does not copy the rejected application candidate into main.
Before its worker invokes the original `base.child(jobpath)`, opt in explicitly:

```python
# Add this checked-out ci/hold_cpu directory to sys.path in the wrapper only.
import profiling
from adapter import with_hold_cpu
original = profiling.Metrics
profiling.Metrics = with_hold_cpu(original)
try:
    base.child(jobpath)
finally:
    profiling.Metrics = original
```

Existing Metrics.track labels ride.create, money.create, create_in_session and
nested services; the adapter retains their measurements and adds `held_cpu` to
snapshot. It never imports/prewarms application models. It starts when existing
Metrics is created, **after service imports**. Capture import CPU separately,
as R3 already does; do not claim this probe measured or reduced import CPU.
No guard function is individually labelled yet; money CPU minus its nested DBAPI
phases still includes Python validation, ORM construction/flush and observer work.

Run only a separate diagnostic round, preserving the existing isolated database
checks, correctness prerequisites, actual concurrency validation, 20 -> 100 stop
rules and 4 processes x pool 4 / overflow 0. Do not put its instrumented latencies
into uninstrumented ABBA. Record exact harness/application/observer SHA256s and
software versions with raw output. The adapter raises on invalid attribution.

## Selection rule after measurement

If mapper configuration occupies leases, investigate separating mapper work from
the lease with an honest whole-process/cold-start budget, or reducing mapper work;
merely moving initialization outside the timer is disallowed. If money body CPU
or SQL dominates, profile that phase before selecting a business-code change.
Preserve row locks, idempotency checks, AUTH/CAPTURE durable boundaries, rollback
and recovery. Do not remove credit/reservation checks based only on business type.
Any candidate still needs correctness and uninstrumented ABBA CPU -20%, P95 -15%,
100-actor P95 <=5000ms. No improvement or C13/C14 PASS is claimed here.

## Validation and remaining work

Local Python/SQLAlchemy 2.1.2: 8 behavioral tests PASS (real SQLite QueuePool,
threads, nested leases, failed SQL, method exception/restore, mapper events and
adapter). R3 used SQLAlchemy 2.1.1; isolated PostgreSQL 18.4 + that exact version
and real-workload integration have **not** run for this new observer.

```sh
python -m unittest discover -s ci/hold_cpu -p 'test_*.py' -v
python ci/hold_cpu/recompute_r3.py /path/to/R3/raw.zip
```

Command Center baseline reconciliation and #240 signed-receipt readback remain a
separate live prerequisite. This source-only diagnostic does not reconcile the
baseline, create a Task, merge, install or deploy anything.
