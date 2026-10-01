# GO Runtime Host · 2026-10-01 Expired Task Objects Are Inert

This document records the stability fix that stops one stale external task object from
forcing the resident Management Agent into a restart loop. It records observed
implementation and test state only.

## 1. The defect

`poll_once()` reaches `Registry.bridge_probe()` for a completed-unknown external task, and
`bridge_probe()` applies the 300-second delivery window. If the immutable task object was
already past `expires_at`, `Reject('expired_or_future')` escaped the pass, the Agent exited,
systemd restarted it, and the same object failed the next pass the same way. One stale object
was therefore permanent.

Observed in the first live bridge E2E: an undelivered probe expired in the repository and
every later pass refused.

## 2. The lifecycle rule

The delivery window gates **admission of a new external task**. It is never re-applied to a
task that was already admitted and completed.

| Local state | Window state | Result |
|---|---|---|
| no row | `ACTIVE` | process as before |
| no row | `FUTURE` | `NOT_YET_VALID`, nothing durable |
| no row | `EXPIRED` | `EXPIRED_IGNORED`, nothing durable |
| `BRIDGE_PENDING` | `ACTIVE` | continue the bridge flow |
| `BRIDGE_PENDING` | `EXPIRED` | `BRIDGE_EXPIRED`, no Evidence |
| `BRIDGE_PENDING` | `FUTURE` | fail closed (`admitted_task_in_future`) |
| `BRIDGE_EXPIRED` | any | `BRIDGE_EXPIRED`, inert |
| `COMPLETE` | any | exact stored receipt reused |
| `CLAIMED` | any | `UNCERTAIN` (unchanged) |

Nothing here deletes a GitHub object, touches the Runtime, or terminates the pass.

## 3. What changed

`channel.py` gains one explicit classifier and one narrow transition, and `flow.py` gains the
ordering that uses them.

```
task_temporal_state(task, now) -> ACTIVE | FUTURE | EXPIRED
```

It validates `issued_at`/`expires_at` types and the `0 < expires_at - issued_at <= 300`
lifetime; a malformed timestamp is `Reject('time_type')` and an out-of-contract lifetime is
`Reject('lifetime')`. Neither is ever reported as "expired", so a structurally bad task can
never be silently swallowed.

```
Registry.expire_bridge_pending(task_id, task_digest)
```

`BEGIN IMMEDIATE`, requires the row, requires the digest to match, requires the state to be
exactly `BRIDGE_PENDING`, and moves it to `BRIDGE_EXPIRED` with `evidence` left `NULL`.
Idempotent once already expired, `Reject` on a different digest, and it can never touch a
`COMPLETE` row.

In `poll_once()` the local Registry row is read **before** the window is classified, so a
completed task keeps replaying its receipt no matter what the clock says. Only a task with no
local row, or a row still in `BRIDGE_PENDING`, is classified.

`channel.py` also exposes `BRIDGE_EXPIRED`, `TASK_ACTIVE`, `TASK_FUTURE` and `TASK_EXPIRED`.
The registration lifetime (86400) and the 300-second probe contract are unchanged.

## 4. What deliberately did not change

Integrity failures keep failing closed even when the object is expired: a bad signature, a
rebound task id, a path-binding conflict and an Evidence byte conflict all still `Reject`.
Covered by dedicated tests. This is not a general "ignore bad task" patch.

The original completed host probe keeps its exact receipt, and the successful C1 probe keeps
its Registry row, its Runtime task and its signed Evidence.

## 5. Tests

```
baseline (PR294 + PR295 component suites)  156 OK
new (test_expired_task.py)                  19 OK
whole component, discover                   175 OK
```

Covered: unknown expired host probe; unknown expired C1 probe never reaching the bridge;
a future task held back and then processed once its window opens; a completed host probe and
a completed C1 probe replaying their exact receipts past expiry; `BRIDGE_PENDING` crossing
expiry into `BRIDGE_EXPIRED` with no Evidence; repeated passes after expiry staying inert;
the classifier's boundaries and its structural refusals; the narrow transition's own
guards; and a mixed pass where an expired object, a future object and a completed object
coexist without disturbing each other.

The Runtime-backed cases run against the real frozen `Runtime`, `Supervisor` and `NoopWorker`
(`GO_C1_C14_RUNTIME_SRC`). Nothing in the tests touches the network or shared state.

## 6. Executor digest

`channel.py` and `flow.py` are part of the Management Agent bundle, so the digest moves.

```
bundle                    8 files, canonical manifest 657 bytes, no CR
previous executor_sha256  fcafe90af4a993ddbc1e0404c682389604e5786b00bc0498dc0e2736768ad519
NEW executor_sha256       df8dd2bd80dbb008c2632bcdd1a8411887ee37aacb0bc4bd330ca803e3c68f3f
```

`adapter.py`, `agent_service.py`, `git_transport.py`, `registration_sync.py`,
`runtime_bridge.py`, `runtime_bridge_service.py` and all systemd units are byte-unchanged.

## 7. Live regression fixture

The object withdrawn during the previous round is restored to
`runtime-host-v1/tasks/` with its original bytes and timestamps. It is expired and stays
expired, which makes it a permanent live fixture proving that a historical expired object
is inert: every pass must classify it `EXPIRED_IGNORED` with no Registry row, no inbox file,
no Runtime task and no Evidence.
