# GO Cell executor liveness contract

## Root cause

The development ledger records assignments and evidence. It does not start a
remote executor and does not prove that a worker remains alive. `ASSIGNED`, an
old process receipt, a completed PR, or historical Evidence must never be
presented as current execution.

Work sub-agents are bounded turns, not daemon processes. Continuous execution
therefore requires an external durable orchestrator with a queue, renewable
leases, heartbeats, and exit events.

## Durable control plane

`ci/runtime_liveness/durable_orchestrator.py` is the executable control-plane
implementation rather than a ledger-only assignment marker. It stores tasks,
attempts, worker bindings, and leases transactionally in SQLite WAL mode. Its
authenticated HTTP API supports idempotent enqueue, atomic claim, heartbeat,
failure admission, `DIAGNOSE -> FIX -> RETEST`, evidence-bound completion,
external blocking, and challenge-bound snapshots.

Expired leases are atomically returned to `QUEUED`; a stale worker cannot renew
an attempt after another worker acquires it. Completion preserves
`DONE_SCOPED` and automatically claims the next queued task for the same Cell,
so accepted PASS work is not redeveloped merely to keep an executor busy.

The source-only `go-cell-orchestrator.service.example` runs the control plane as
a restartable least-privilege service. Activation still requires an authorized
long-running host, TLS material, a bearer token from the host secret store, and
an explicit import of only the Ledger's unfinished tasks. This PR does not
install, enable, seed, or deploy the service.

API paths under `/internal/v1/` are:

- `tasks/enqueue`, `tasks/claim`, `tasks/heartbeat`;
- `tasks/fail`, `tasks/recovery/advance`, `tasks/complete`;
- `tasks/block-external` and `cell-runtime-snapshot`.

## Runtime contract

1. A task enters a durable queue with Cell, task, source SHA, and attempt ID.
2. A worker atomically acquires a unique lease and emits ACK/start.
3. The worker renews its heartbeat before the configured freshness limit and
   before lease expiry.
4. Test, CI, or Evidence failure keeps the same task in
   `FAIL -> DIAGNOSE -> FIX -> RETEST`; it must not become IDLE.
5. Process exit, cancellation, or expired heartbeat releases the lease and
   emits an exit event. Only unfinished work is requeued; completed PASS
   evidence is preserved.
6. `BLOCKED_EXTERNAL` is allowed only with evidence and an explicit release
   condition. C06 supplier E2E/provenance may use this state.
7. C14 and C13 remain independent and cannot be self-certified.

## Active external probe

`ci/runtime_liveness/probe_external_orchestrator.py` performs a fresh HTTPS
POST to the configured orchestrator. It sends a random challenge and accepts a
snapshot only when all of these hold:

- the TLS endpoint is explicitly configured and a bearer token is available;
- the response echoes the fresh challenge;
- `orchestrator_id` remains stable;
- `sequence` increases and `snapshot_id` is not replayed against the durable
  local state file;
- `generated_at` is fresh;
- each live Cell has exact task, source, attempt, and unique lease binding;
- heartbeat age and lease expiry pass against the probe host's current time.

The probe overwrites any remote `observed_at` with its own clock before the
liveness gate runs. A cached response, static `ASSIGNED` ledger, missing token,
network error, malformed JSON, sequence rollback, stale heartbeat, or expired
lease fails closed. If executable Cells exist and none is live, the result is
`SCHEDULER_FAIL / ALL_CELLS_EXITED`.

Example invocation from a long-running scheduler host:

```sh
export GO_CELL_ORCHESTRATOR_URL=https://orchestrator.example/internal/v1/cell-runtime-snapshot
export GO_CELL_ORCHESTRATOR_TOKEN='read from the host secret store'
python ci/runtime_liveness/probe_external_orchestrator.py \
  --state-file /var/lib/go-cell-runtime-liveness/state.json
```

The state directory must be durable and writable only by the probe service.
The example systemd service/timer under `ci/runtime_liveness/systemd/` invokes
this path every 30 seconds. They are source templates only: this PR does not
install or enable them and does not add credentials to GitHub.

## Snapshot response shape

```json
{
  "schema": "go.cell-orchestrator-snapshot.v1",
  "orchestrator_id": "stable-runtime-id",
  "snapshot_id": "unique-snapshot-id",
  "sequence": 42,
  "challenge": "exact request challenge",
  "generated_at": "2026-09-16T13:30:00Z",
  "expected_executable_cells": ["C02"],
  "executors": [{
    "cell_id": "C02",
    "status": "RETEST",
    "task_id": "task-id",
    "source_sha": "40-hex-source-sha",
    "attempt_id": "attempt-id",
    "lease_id": "unique-lease-id",
    "heartbeat_at": "2026-09-16T13:29:30Z",
    "lease_expires_at": "2026-09-16T13:34:30Z"
  }]
}
```

This gate proves only fresh external lease/heartbeat liveness. It does not
claim product PASS, C14/C13 PASS, Final Release, HK deployment, or Production
readiness. PR #115 remains DO_NOT_MERGE and all deployment gates remain HOLD.
