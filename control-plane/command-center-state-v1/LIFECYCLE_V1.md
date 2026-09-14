# Control Plane lifecycle V1

Scope: `CONTROL_STATE_AND_STATUS_ONLY`. This document describes the lifecycle of
the chains that already exist. It introduces no new execution capability.

The lifecycle vocabulary is closed. A projection must place every Task in exactly
one of these states and must never collapse them into PASS / FAIL.

## Request lifecycle

| State | Meaning | Observable on the control bus |
|---|---|---|
| `REQUEST_CREATED` | A human intent file exists on a control-bus ref | yes |
| `REQUEST_VALIDATED` | Command Center accepted it and derived a Task | indirectly, via the derived Task existing |
| `REQUEST_REJECTED` | Command Center refused it | **no** — the rejection reason lives in the Bridge ledger on Command Center |

The projector therefore reports every Request as `REQUEST_CREATED` and links it to
a Task when one exists. It does not invent an acceptance.

## Task / Evidence lifecycle

```
REQUEST_CREATED
   ↓  (Command Center: validate + derive + sign with the task identity)
TASK_SIGNED
   ↓  (publish to tasks/<task_id>.json, byte-identical readback)
TASK_PUBLISHED ──────────────► TASK_EXPIRED      (validity window passed, no Evidence)
   ↓  (agent claim; recorded only in the agent-local ledger)
HK_AGENT_PICKED_UP                               ← not observable from GitHub
   ↓  (Evidence started_at)
EXECUTION_STARTED
   ↓  (Evidence published + pushed)
EVIDENCE_PUBLISHED ──────────► EXECUTION_FAILED  (signed status != SUCCESS, or result mismatch)
   ↓  (Evidence signature verified against the Hong Kong evidence identity)
EVIDENCE_VERIFIED
   ↓  (Task signature verified against the Command Center task identity)
COMPLETE
```

### Rank discipline at the end of the chain

`COMPLETE` requires **both** identities:

* the Evidence verifies against the Hong Kong evidence key, and
* the Task it answers verifies against the Command Center task key.

If only the Evidence verifies, the strongest honest state is `EVIDENCE_VERIFIED`
with assertion rank `OBSERVED`. If neither key is supplied, the state is
`EVIDENCE_PUBLISHED` with rank `OBSERVED`. Neither may be reported as `PROVEN`.

## Failure branches, each distinct

| State | Trigger | Detectable from the control bus |
|---|---|---|
| `REQUEST_REJECTED` | Request refused by the Bridge | no (Bridge ledger) |
| `TASK_EXPIRED` | `now >= expires_at` and no Evidence | yes |
| `TASK_NOT_PICKED_UP` | claim never happened | **no** — needs the agent ledger |
| `EXECUTION_FAILED` | Evidence `status != SUCCESS`, or a verified `executor_result` differs from the frozen terminal result | yes, when Evidence exists |
| `EVIDENCE_INVALID` | Evidence signature fails, or `started_at > completed_at` | yes |
| `EVIDENCE_TIMEOUT` | `completed_at > expires_at` | yes |
| `REPLAY_REJECTED` | one nonce appears in two Tasks, or one Request id appears twice | yes |
| `POLICY_HOLD` | Task signature fails, or the Task predates the current parameter contract | yes |

## "Is anything stuck right now?"

Three different populations must never be merged into one answer:

| Population | Definition | Used for |
|---|---|---|
| `active_tasks` | published, still inside the validity window | "is something running?" |
| `active_stuck_tasks` | published, still inside the window, older than `stuck_after_seconds` with no Evidence | "is anything stuck **right now**?" — this is the only input to that answer |
| `recent_expired_tasks` | expired inside the recent window | operator triage |
| `historical_expired_tasks` | expired before the recent window | index only; never affects current health |

A history containing 21 expired Tasks does **not** mean 21 things are stuck.

## Why the vocabulary matters

The two states an operator most wants — *"did it even get picked up?"* and
*"why was my request refused?"* — are exactly the two the control bus cannot
answer. That is the current boundary of the GitHub-native design, recorded here
and in the delivery blockers rather than papered over with a guess.

## Rank rules

`PROVEN` > `OBSERVED` > (`PENDING` / `HOLD` / `FAILED`) > `UNKNOWN`.

* `PROVEN` requires the artifact's own Ed25519 signature to verify against a
  pinned public key of the correct identity.
* `OBSERVED` means the record was read but its signature was not checked in this run.
* `UNKNOWN` always carries `value = null`. It never means "probably fine".
