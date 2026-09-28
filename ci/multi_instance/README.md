# Independent-process transaction gate

Run `python ci/multi_instance/run.py` only in the disposable CI environment
defined in `.github/workflows/multi-instance-transactions.yml`.

The normal gate has no profiling hooks. A separate `--diagnostic --out DIR` run
records successful SQL counts/times, connection-acquisition wall times and process
CPU/RSS after rechecking correctness. Concurrent summed times are not additive;
connection acquisition includes pre-ping/creation as well as queueing. Diagnostic
latencies are not substituted for the uninstrumented capacity gate. No statement
parameters or SQL text are stored, only statement hashes and operation types.
SQL counts cover successful SQLAlchemy cursor events, excluding driver-level
ping/commit/rollback; cursor time excludes statement compilation.

Extended diagnostics also record connection checkout-to-checkin duration,
statement-cache outcomes, mapper-configuration event duration, transaction phase
wall/actor-thread CPU times, and host CPU counters. Actor-thread CPU excludes
the nested replay threads; process CPU is retained separately. Host counters
include PostgreSQL and OS work and are not attribution to the application alone.
Selected synchronous service calls also record inclusive wall/calling-thread CPU
durations with thread-safe counters. Nested service times overlap and must not be
added; these explicit wrappers replace the discarded cProfile attribution.
Each tier starts fresh service processes, so first-use ORM/statement setup is
inside transaction latency; startup is not silently warmed out of acceptance.

`ci/transaction_comparison.py` runs pinned baseline/candidate/candidate/baseline
versions sequentially on one runner with identical dependency installation and
the same uninstrumented harness. Each round uses a fresh schema and repeats all
correctness gates. Its manifest binds the copied harness separately from each
unchanged application tree. A failed latency tier allows the next comparison
round but never a higher tier in that round; correctness/errors stop comparison.
Two repetitions per version are an initial control, not statistical confidence
or a substitute for sustained production-like capacity testing.

This exercises actual GO transaction services with two separate Python processes
and independent SQLAlchemy pools sharing PostgreSQL 18.4. It is **not** an HTTP,
authentication, load-balancer, distributed-host, real PSP, or real supplier test.
Do not translate these transaction counts into online users or production SLA.

Correctness runs first:

- 20 distinct requests for the last available rail seat, attraction admission,
  and hotel room-night; verify one winner and capacity accounting.
- Same-key ride creation across processes, receipt replay and changed-payload
  rejection; 20 capture replays must all resolve to the same money movement.
- 20 initial checkouts for the same rail/attraction order, then replay from both
  processes; exactly one successful intent and one successful attempt may exist.
- Rail and attraction payment/cancellation on both sides of payment-root commit.
  The losing action must fail without releasing paid inventory or charging a
  cancelled order.
- An OS process exits after actual simulated refund-money commit and before order
  completion. Another process must refuse premature takeover, wait for the real
  30-second database lease to expire, and finish without another refund. Neither
  the persisted lease nor the system clock is edited.

Only after correctness passes do 20, 100, 250, 500, and 1,000 concurrent RIDE
transaction actors run, split across two processes. Each tier is one bounded
burst, **not a soak test**. Each transaction creates an order, replays creation,
checks out, replays capture concurrently, rejects altered capture amounts,
records a synthetic supplier fact, starts and completes fulfillment. SQL checks
cover all persisted load orders, including partial effects from failed requests.

The fixed diagnostic gates are zero unexpected failures, valid inventory and
money ledgers, full-transaction P95 <= 5 seconds and P99 <= 10 seconds. These
latencies include replay checks and pool waiting. A failed gate blocks higher
tiers. PIDs, observed transaction overlap, all outcomes, ledger facts, hardware,
  database identity, source commit/tree, and artifact hashes are retained.

Each child pool has size 5 and zero overflow; coordinator pool size is also 5.
The orchestration connection is separate. Provider credentials are not inherited;
Python socket audit hooks deny non-loopback connections in all test processes.
Schema names are random and cleanup targets only that run's schema. Fault
injection is local to test processes and does not alter production source.

Coverage remains bounded: it does not establish every vertical's full lifecycle,
HTTP admission control, callback authentication, long-duration memory behavior,
multi-host failover, or the million-online planning target. Those require later
gates, not extrapolation from this evidence.
