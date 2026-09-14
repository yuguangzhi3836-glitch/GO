# Control Plane lifecycle V1

The lifecycle vocabulary is closed. A projection must place every Task in exactly
one of these states and must never collapse them into PASS / FAIL.

## Request lifecycle

| State | Meaning | Observable on the control bus |
|---|---|---|
| `REQUEST_CREATED` | A human intent file exists on a control-bus ref | yes |
| `REQUEST_VALIDATED` | Command Center accepted it and derived a Task | indirectly, via the derived Task existing |
| `REQUEST_REJECTED` | Command Center refused it | **no** — the rejection reason lives in the Bridge ledger on Command Center |

`REQUEST_VALIDATED` and `REQUEST_REJECTED` are therefore only derivable when the
Bridge ledger is readable. The projector reports the Request as `REQUEST_CREATED`
and links it to a Task when one exists; it does not invent an acceptance.

## Task / Evidence lifecycle

```
REQUEST_CREATED
   ↓  (Command Center: validate + derive + sign)
TASK_SIGNED
   ↓  (publish to tasks/<task_id>.json, byte-identical readback)
TASK_PUBLISHED ──────────────► TASK_EXPIRED            (validity window passed, no Evidence)
   ↓  (agent claim; recorded only in the agent-local ledger)
HK_AGENT_PICKED_UP                                     ← not observable from GitHub
   ↓  (Evidence started_at)
EXECUTION_STARTED
   ↓  (Evidence published + pushed)
EVIDENCE_PUBLISHED ──────────► EXECUTION_FAILED        (signed status != SUCCESS, or result mismatch)
   ↓  (signature verified against the pinned HK key)
EVIDENCE_VERIFIED ───────────► COMPLETE
```

Failure branches, each distinct:

| State | Trigger | Detectable from the control bus |
|---|---|---|
| `REQUEST_REJECTED` | Request refused by the Bridge | no (Bridge ledger) |
| `TASK_EXPIRED` | `now >= expires_at` and no Evidence | yes |
| `TASK_NOT_PICKED_UP` | claim never happened | **no** — needs the agent ledger |
| `EXECUTION_FAILED` | Evidence `status != SUCCESS`, or `executor_result` != frozen terminal result | yes, when Evidence exists |
| `EVIDENCE_INVALID` | Evidence signature fails against the pinned HK key, or `started_at > completed_at` | yes |
| `EVIDENCE_TIMEOUT` | `completed_at > expires_at` | yes |
| `REPLAY_REJECTED` | one nonce appears in two Tasks, or one Request id appears twice | yes |
| `POLICY_HOLD` | Task signature fails, or the Task predates the current parameter contract | yes |

## Why this vocabulary matters

The two states an operator most wants — *"did it even get picked up?"* and
*"why was my request refused?"* — are exactly the two the control bus cannot
answer. That is not a modelling choice; it is the current boundary of the
GitHub-native design and it is recorded as a delivery blocker rather than papered
over with a guess.

## Rank rules

`PROVEN` > `OBSERVED` > (`PENDING` / `HOLD` / `FAILED`) > `UNKNOWN`.

* `PROVEN` requires an Ed25519 signature verified against a pinned public key.
* `OBSERVED` means the record was read but its signature was not checked in this run.
* `UNKNOWN` always carries `value = null`. It never means "probably fine".
