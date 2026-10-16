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

## Same-host PostgreSQL readback — 2026-10-02

Executed in the original `literate-winner-vpqqjgwvpjprcp7gw` 4-core/16GB
Codespace, Python 3.12.3, SQLAlchemy 2.1.1 and PostgreSQL 18.4. The eight
observer tests passed there. Application remained the historical baseline
`a6361b9376ab59f05616338b8245ac4e2976dec3`, application tree
`6570b66bc977f89c0311d67bdc6b721cd70d4e09`; R3 harness source was
`afb6c469d518bd2386846fe3c9c7a2d6548f9aca`. No application edits.

Raw evidence and executed wrapper are archived at evidence commit
`13a08ec261cc1618b7cada5a2b64bd438b848621`, directory
`ci/hold_cpu/evidence/same-host-20261002`. Raw ZIP SHA256:
`a720dd9adfbddeb90c19a16ef862a56f156237d4616405e4dbfa893f67cc8c88`.
`SAME_HOST_20261002.json` contains the remote-read-back summary, per-service
breakdown and original harness validation. The ZIP includes the exact executed
wrapper bytes, source hashes, raw worker profiles/results, logs and SQL checks.

Original validator passed evidence hashes, 13 correctness scenarios, all 120
completed orders, actual 20/100 concurrent actors and the 4x4/overflow0 binding.
All eight worker profiles report valid balanced leases: 420/420 at 20 actors,
2100/2100 at 100. The workload stopped at 100's failed latency tier:

| Diagnostic tier | P95 ms | P99 ms | Application CPU s | Lifetime CPU s |
| --- | ---: | ---: | ---: | ---: |
| 20 | 2092.266 | 2113.626 | 5.574459 | 24.656433 |
| 100 | 7845.097 | 7914.882 | 14.610175 | 33.918239 |

These include observer overhead, are not uninstrumented ABBA, and show **no
performance improvement or capacity acceptance**. There was no 250+ run.

At 100 actors, exclusive held-thread buckets total 9.697388 CPU seconds and
87.060809 concurrent wall seconds. DBAPI execute accounts for 2.692967 CPU
seconds and 60.999317 wall seconds (70.1% of held-thread wall). Commit accounts
for 11.499673 wall seconds. These are not database-server CPU measurements;
SQL wall includes transport, scheduling and driver work.

Per-service existing SQL counters locate the largest SQL wall total in
`money.create_in_session`: 2000 statements / 9.309649 seconds, with 14.063154
seconds of lease holds and 228.726702 seconds of summed queue wait. `ride.create`
records 1500 statements / 8.703242 seconds, 13.015083 seconds held and 210.509434
seconds summed queue wait. Queue sums are concurrent waiting, not CPU.

Mapper configuration consumes 2.848120 thread-CPU seconds in the original
collector but has **no held-connection bucket** in this run. It is a cold-start
cost, not the measured lease-occupation hotspot. Largest non-DB held CPU buckets
are supplier.record_supplier_fact (1.187109 s), ride.fulfill (1.145818 s), then
money.create_in_session (0.921249 s); ride.create is 0.683156 s.

The next implementation target is money's database round trips while holding
its transaction, followed by ride's queries. This report does not establish
that a specific query is redundant. Preserve credit-source/reservation guards,
root and movement locks, global idempotency conflicts and durable AUTH/CAPTURE
commits. Combining locked reads needs concurrency/MVCC tests; returning a stale
joined row after waiting for a lock is not an acceptable query-count saving.
An application optimization has **not** yet been implemented or qualified by
this diagnostic. The historical baseline is not current main or deployed #320;
performance numbers must not be transferred to those different application trees.
