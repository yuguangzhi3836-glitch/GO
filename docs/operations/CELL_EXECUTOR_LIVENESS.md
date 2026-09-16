# GO Cell executor liveness contract

## Root cause fixed by this gate

The development ledger records assignments and evidence. It does not start a
remote executor and does not prove that a worker remains alive. In particular,
`ASSIGNED`, an old process receipt, a completed PR, or historical Evidence must
never be presented as current execution.

Work sub-agents are bounded turns, not daemon processes. They normally exit
after their bounded task. Continuous execution therefore requires an external
durable scheduler with a queue, renewable leases, heartbeats, and exit events.

## Required runtime model

1. A task enters a durable queue with Cell, task, source SHA, and attempt ID.
2. A worker atomically acquires a short lease and emits ACK/start.
3. The worker renews its heartbeat before lease expiry.
4. Test, CI, or Evidence failure keeps the same task in
   `FAIL -> DIAGNOSE -> FIX -> RETEST`; it must not become IDLE.
5. Process exit, cancellation, or expired heartbeat releases the lease and
   emits an exit event. The scheduler requeues only unfinished work, preserving
   completed PASS evidence.
6. `BLOCKED_EXTERNAL` is allowed only with evidence and an explicit release
   condition. C06 supplier E2E/provenance may use this state.
7. C14 and C13 remain independent gates and cannot be self-certified by the
   implementation worker.

## Monitoring truth

`ci/runtime_liveness/validate_runtime_liveness.py` consumes an orchestrator
runtime snapshot. A Cell is live only when it has a non-expired lease, a fresh
heartbeat, and task/source binding. Zero live executors while executable work
exists is `SCHEDULER_FAIL / ALL_CELLS_EXITED`.

This gate does not claim product PASS, C14/C13 PASS, Final Release, HK deploy,
or Production readiness. PR #115 remains DO_NOT_MERGE and all deployment gates
remain HOLD.
