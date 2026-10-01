# GO Runtime Host · 2026-10-01 External C1 Runtime Probe Bridge

This document records the bounded bridge change that lets one fixed external action reach
the C1-C14 Runtime on the dedicated Runtime Host. It records observed implementation and
test state only, and it does not decide whether the project should go beyond this scope.

## 1. What this round adds, and what it deliberately does not

Adds exactly one new external action:

```
RUNTIME_C1_PROBE_V1
```

It is fixed in the protocol and in the implementation:

```
owner_c     = C1
runtime kind = RUNTIME_PROBE
parameters  = {}
```

It does **not** add: arbitrary C selection, C2-C14 external dispatch, an arbitrary runtime
kind, an arbitrary payload, shell, commands, a real AI worker, model calls, deployment
actions, Production or HK behaviour.

The original `RUNTIME_HOST_PROBE_V1` behaviour is unchanged, and a registration that
authorizes only that action remains valid, so an already-installed registration survives
the rollout.

## 2. Action vector

`channel.py` now holds a closed action set:

```
HOST_ACTION    = 'RUNTIME_HOST_PROBE_V1'
RUNTIME_ACTION = 'RUNTIME_C1_PROBE_V1'
ACTIONS        = (HOST_ACTION, RUNTIME_ACTION)
ACTION         = HOST_ACTION        # unchanged backward-compatible alias
```

`action_scope()` accepts only a non-empty, duplicate-free subset of `ACTIONS`. An unknown
action, a repeated action, an empty vector or a non-list is refused. Nothing in the
protocol accepts an action outside this set, and the set is not an extension point.

New registrations issued by the rotator carry both actions. The 6-hour rotation interval
and the 24-hour lifetime are unchanged.

## 3. Why the Agent does not touch the Runtime database

The Runtime database belongs to the `go-runtime` account and runs in SQLite WAL mode.
Making the root Management Agent a second direct writer would be a real failure mode, so
the handoff is a fixed local filesystem bridge instead:

```
Management Agent (root)
        ->  /var/lib/go-runtime-bridge/inbox/<external_task_id>.json
runtime_bridge_service.py (User=go-runtime)
        ->  Runtime.enqueue()
        ->  /var/lib/go-runtime-bridge/outbox/<external_task_id>.json
Management Agent (root)
```

No TCP listener, no HTTP listener, no network service, no new repository.

Directory and file ownership:

```
/var/lib/go-runtime-bridge          root:go-runtime        0750
/var/lib/go-runtime-bridge/inbox    root:go-runtime        2750   files root:go-runtime 0640
/var/lib/go-runtime-bridge/outbox   go-runtime:root        2750   files go-runtime:root 0640
```

The set-group-id bit makes group ownership deterministic for newly created files on both
sides, so the documented modes hold without privileged post-processing. The layout is also
expressed as a reproducible `tmpfiles.d` definition
(`systemd/go-runtime-host-bridge.tmpfiles.conf`).

## 4. Bridge request and result schema

Both files are canonical JSON with closed field sets.

Request (`runtime-c1-probe-request`), written by the Agent:

```
version kind external_task_id external_task_sha256 registration_sha256 owner_c runtime_kind
```

`owner_c` is fixed to `C1` and `runtime_kind` is fixed to `RUNTIME_PROBE`; either value
being anything else is refused. There is no payload, no command, no path and no URL field.

Result (`runtime-c1-probe-result`), written by the bridge service:

```
version kind external_task_id external_task_sha256 runtime_task_id runtime_owner_c
runtime_kind runtime_status runtime_event_hash runtime_result_sha256
```

`runtime_event_hash` is the Runtime evidence `event_hash` of the `TASK_COMPLETED` event, and
`runtime_result_sha256` is the canonical digest of the observed worker result object.

Inbox immutability: canonical bytes, temporary file, `fsync`, owner/mode, then `os.replace`.
An existing identical request is reused; an existing different request under the same
external task identity is refused (`bridge_request_conflict`) and never overwritten. The
outbox follows the same rule.

## 5. Runtime side

`runtime_bridge_service.py` scans the inbox once per second (no inotify, no socket, no
daemon framework). For each valid request it calls the installed
`Runtime.enqueue('C1', 'RUNTIME_PROBE', <three-field payload>, idempotency_key='runtime-host:<external_task_id>')`
and then observes the task. The idempotency key is derived from the external task identity,
so the same external task always maps to the same Runtime task and is never enqueued twice.

The service is not a worker. It never claims, executes or completes a task, never replaces
the Supervisor, never calls a model or API, and has no GitHub access, no Evidence key, no
CC signer and no network. Completion stays with the frozen Runtime Supervisor and its
injected worker adapter.

The Runtime module is imported from the installed path `/opt/go/c1-c14-runtime`; no Runtime
logic is copied or forked.

## 6. Agent integration

`poll_once()` dispatches on the signed task action. For the bridge action the Registry
commits the claim first, then drops the fixed request, then binds the observed Runtime
result into the signed Evidence. While no terminal Runtime result exists the pass returns

```
RUNTIME_PENDING
```

and **no Evidence is published**. On later passes the same external task produces the same
inbox bytes and the same Runtime idempotency key, and once the receipt exists it is reused
byte for byte with no re-signing and no second enqueue.

## 7. External Evidence contract

`verify_evidence()` now has two strict branches, dispatched by the signed task action.
The original `RUNTIME_HOST_PROBE_V1` branch keeps its exact old field set
(`status = PROBE_ONLY`, `runtime_acceptance = NOT_RUN`). The new branch additionally
requires:

```
runtime_task_id      rt_<32 hex>
runtime_owner_c      C1
runtime_kind         RUNTIME_PROBE
runtime_event_hash   <64 hex>
runtime_result_sha256 <64 hex>
status               RUNTIME_COMPLETED
runtime_acceptance   SUCCEEDED
```

Neither branch accepts the other's field set, no field is optional, and nothing claims
`AI_WORK_COMPLETED`: the current Worker is `NoopWorker`.

## 8. CC test tooling

`cc_runtime_probe_test.py` is a separate bounded tool with exactly two verbs:

```
publish-one-c1-probe
collect-c1-probe
```

It uses its own durable outbox (`c1-probe-outbox.db`), separate from the older host-probe
outbox, so the retained first-E2E task is not disturbed. It reads the current published
registration from the registrations namespace, verifies its signature and the deployment
binding, and requires that the registration authorizes `RUNTIME_C1_PROBE_V1`. It then signs
one task with `parameters == {}`, records it durably `PREPARED -> ATTEMPTED -> PUBLISHED`,
requires byte-identical readback, and refuses a second task. The collector fetches the
final Evidence, runs it through `verify_evidence()`, and requires
`runtime_acceptance = SUCCEEDED`.

## 9. Executor digest

The Management Agent bundle is the installed directory `/opt/go/runtime-host-agent`, and
`executor_sha256` is the canonical manifest digest over every `*.py` installed there,
sorted by byte order, LF, no BOM, one `<sha256><two spaces><relative_path>\n` line per file.

```
bundle            8 files
manifest_bytes    657
NEW_EXECUTOR_SHA256  fcafe90af4a993ddbc1e0404c682389604e5786b00bc0498dc0e2736768ad519
previous_executor_sha256  cdba176afb53533be3cf5d23bebe65edbeda2b1c98b4e5e71b0178525bf8dbf4
```

Files: `adapter.py`, `agent_service.py`, `channel.py`, `flow.py`, `git_transport.py`,
`registration_sync.py`, `runtime_bridge.py`, `runtime_bridge_service.py`.
`adapter.py`, `git_transport.py` and `registration_sync.py` are byte-unchanged this round.

## 10. Tests

Run on Linux (`Ubuntu-24.04`) with `GO_C1_C14_RUNTIME_SRC` pointing at the frozen Runtime
source, so the Runtime half of the loop exercises the real `Runtime`, `Supervisor` and
`NoopWorker` rather than a stub.

```
baseline (PR294 component suites)  132 OK
new (test_c1_bridge.py)             24 OK
whole component, discover          156 OK
systemd-analyze verify             6/6 exit=0, no warnings
```

Covered: the closed action vector and its backward compatibility; the bridge request/result
schema including duplicate keys, extra fields, wrong target and path-shaped identifiers;
inbox immutability and symlink refusal; the observed Runtime task (`owner_c=C1`,
`kind=RUNTIME_PROBE`, `status=SUCCEEDED`, `attempts=1`, lease cleared), its
`TASK_ENQUEUED -> TASK_CLAIMED -> TASK_COMPLETED` evidence sequence and a valid evidence
chain; the result binding to the exact Runtime task; exactly one final external Evidence
and its byte-stable reuse on later passes; the retained host probe never consulting the
bridge and never entering the Runtime; and the PR294 single-snapshot-per-repository
behaviour.

No network, no real GitHub, no SSH and no shared state are used by the tests.

## 11. Findings from the live run

Two defects were found only by running the channel against the deployed host, and both are
recorded here rather than glossed over.

**A. The Management Agent unit needed the bridge inbox writable.** Under
`ProtectSystem=strict` the Agent could read the fixed inbox but not create the request file,
so the first live pass failed with `OSError` and the unit entered a restart loop.
`go-runtime-host-agent.service` now lists
`ReadWritePaths=/var/lib/go-runtime-host /var/lib/go-runtime-bridge/inbox`. The unit file is
not part of the `executor_sha256` manifest, so this correction does not change the bundle
digest.

**B. The Agent configuration needed a bridge block.** `agent.json` on the host did not carry
the fixed `inbox` / `outbox` pair, so the Agent refused the bridge action with
`bridge_unavailable` rather than guessing a path. This is the intended fail-closed behaviour,
and the fix is configuration only.

**C. An external task that expires before it is delivered is not inert.** `bridge_probe()`
applies the same 300-second task window as the host probe, so a bridge task left in the
repository past its expiry makes every later pass refuse and the Agent exit. The observed
consequence on this round: the first published probe was never delivered (see 12) and, once
expired, would have kept the Agent in a restart loop. The object was withdrawn before that
happened. This is a real product-level gap in how an undelivered task should be retired, and
it is recorded as a known issue rather than fixed in this round.

## 12. Undelivered task of the live run

One `RUNTIME_C1_PROBE_V1` task was published before the two defects above were found, and it
expired without ever being delivered.

```
task_id          rh-c1probe-2cf380ace296b750
task bytes       557, sha256 0f92e6e2746d94da828302fa0e843e847cacdc848c2c35adcd1610f4bf1b9c34
inbox files      0
runtime tasks    0
evidence objects 0
```

It produced no bridge request, no Runtime task and no Evidence. Because an expired task
would have poisoned every later pass (finding C), the object was withdrawn from
`runtime-host-v1/tasks/` and the CC-side outbox record was archived as
`c1-probe-outbox.withdrawn-rh-c1probe-2cf380ace296b750.db` rather than deleted. Exactly one
replacement identity was then published, and that is the task the live end-to-end actually
exercised.

## 13. Boundaries recorded, not changed

`EXTERNAL_TASK_TO_C1_C14_RUNTIME` is now scoped, not general: one fixed `C1` /
`RUNTIME_PROBE` probe crosses the bridge and is completed by the existing `NoopWorker`.
There is no C2-C14 dispatch, no arbitrary kind or payload, and no real AI worker.
