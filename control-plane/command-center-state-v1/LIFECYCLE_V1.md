# Control Plane lifecycle V1

Scope: `CONTROL_STATE_AND_STATUS_ONLY`. This document describes the lifecycle of
the chains that already exist. It introduces no new execution capability.

The lifecycle vocabulary is closed. A projection must place every Task in exactly
one of these states and must never collapse them into PASS / FAIL.

## Request lifecycle

| State | Meaning | Observable on the control bus |
|---|---|---|
| `REQUEST_CREATED` | A human intent file exists on a control-bus ref | yes |
| `REQUEST_VALIDATED` | Command Center accepted it and derived a **signed** Task | via the fact, corroborated by the Task |
| `REQUEST_REJECTED` | Command Center refused it | via the fact, with the reason |
| `REQUEST_DUPLICATE` | A distinct submission reused a consumed `request_id` | via the fact |
| `REQUEST_REPLAY_REJECTED` | A consumed submission identity was presented again | via the fact |
| `UNKNOWN` | The Bridge spoke about it but its Request file is not on the bus | via the fact |

CC V1-05 moved what the Bridge did with a Request onto the control bus. The
Bridge's durable ledger keeps the **accepted** half and the `ignored` reasons;
every refusal is raised as a `Reject` and printed to stdout, and was kept in no
file at all — so before this, a refusal reason existed only in the Bridge's
process output and was lost when the poll ended. The read-only exporter in
`control-plane/command-center-request-visibility-v1` now reads the ledger, the
operator's journalled copy of that stdout, and the collected Request files, and
emits one Request fact per Request identity.

Three rules follow, and the projection enforces all three:

* **An acceptance needs proof.** `REQUEST_VALIDATED` is the only positive fact
  and it declares `proof_required`. The projection reports it only when the named
  Task is on the control bus, its `task_id` carries `sha256(request_id)[:12]`,
  its claimed digest describes the Task as stored, its signature verifies, and
  the verifier is bound to the published Command Center identity. Anything less
  leaves the Request at `REQUEST_CREATED` with a `REQUEST_BINDING_UNPROVEN`
  anomaly and the failed claim still visible. A Request file existing is never
  evidence that it was accepted.
* **A reason is never dropped.** The Bridge's own token is carried through
  verbatim; a token the contract does not classify is `UNCLASSIFIED_REJECT`, not
  a blank. A submission whose Request identity cannot be established produces no
  fact — a fact binds a `request_id` — and is recorded at submission level in the
  export index with its reason intact.
* **A duplicate or a replay is never a success.** Each has its own lifecycle and
  each carries `counted_as_success = false`.

A fact is an observation of the Bridge, never a permission: it authorizes no
retry, no replay and no action, and the projection refuses any fact that claims
otherwise. Until an approved change wires the export to a timer and publishes its
output, `request_visibility.facts_collected` is 0 and every Request honestly
reads `REQUEST_CREATED`.

## Task / Evidence lifecycle

```
REQUEST_CREATED
   ↓  (Command Center: validate + derive + sign with the task identity)
TASK_SIGNED
   ↓  (publish to tasks/<task_id>.json, byte-identical readback)
TASK_PUBLISHED ──────────────► TASK_EXPIRED      (validity window passed, no Evidence)
   ↓  (agent claim; recorded durably in the agent-local ledger)
HK_AGENT_PICKED_UP                               ← visible only through a failure record (CC V1-02)
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
| `REQUEST_REJECTED` | Request refused by the Bridge | yes, via a published Request fact (CC V1-05) |
| `TASK_EXPIRED` | `now >= expires_at` and no Evidence | yes |
| `TASK_NOT_PICKED_UP` | claim never happened | **no** — needs the agent ledger. CC V1-02 narrows this to "no claim", for Tasks published after the capability exists |
| `EXECUTION_FAILED` | Evidence `status != SUCCESS`, or a verified `executor_result` differs from the frozen terminal result | yes, when Evidence exists |
| `EVIDENCE_INVALID` | Evidence signature fails, or `started_at > completed_at` | yes |
| `EVIDENCE_TIMEOUT` | a claimed success with `completed_at > expires_at` | yes |
| `REPLAY_REJECTED` | one nonce appears in two Tasks, or one Request id appears twice | yes |
| `POLICY_HOLD` | Task signature fails, or the Task predates the current parameter contract | yes |

`EXECUTION_FAILED` is decided by the signed `status` and is evaluated **before**
the validity window. A failure is recorded when the attempt stopped, which may
legitimately be after `expires_at`; only a claimed success can time out. A record
with two distinct Evidence copies for one Task identity fails closed and is capped
at `EVIDENCE_VERIFIED` / `OBSERVED`, because one Task identity cannot have two
outcomes.

## Failure records (CC V1-02)

An authenticated Task whose single execution attempt is **claimed** and then fails
publishes a signed `FAILED` record to the same
`evidence/<task_id>-<nonce>.json` path a success would use, signed by the same
Hong Kong evidence identity:

```
task_id / nonce / action_id / environment     the original Task binding, never dropped
status                                       FAILED
failure.kind                                 closed set: HANDOFF_FAILED, EXECUTION_FAILED,
                                             RESULT_REJECT, EVIDENCE_BUILD_FAILED,
                                             EVIDENCE_PUBLISH_FAILED, AGENT_REJECT
failure.stage                                where the attempt stopped, closed vocabulary
failure.reason_code                          closed set; anything else is UNCLASSIFIED_REJECT
failure.attempt_budget_exhausted             true
gate_results                                 PASS / FAIL / NOT_EVALUATED per gate
retry_permitted / replay_authorized          always false
authorizes_any_action                        always false
```

Three rules are load-bearing:

1. **Only a claimed attempt is reported on.** A Task rejected before the claim
   publishes nothing, because a Task whose own signature never verified must never
   be able to cause a write into the control bus.
2. **A failure record authorizes nothing.** It is not a retry permission, not a
   replay permission, and not an action. The one-attempt rule lives in the agent
   ledger. A record that claims otherwise is recorded and given no effect.
3. **A failed publication of a failure record is not a success.** It is reported
   as `EVIDENCE_NOT_PUBLISHED` and does not release the attempt budget.

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

The two states an operator most wants are *"did it even get picked up?"* and
*"why was my request refused?"*.

CC V1-02 closed the first one for the failure half: a claimed attempt that fails
now publishes a signed record, so "picked up and failed" is no longer invisible and
absence of Evidence now indicates no claim.

CC V1-05 closed the second one's mechanism: the Bridge's refusals are exported as
Request facts, so `why_not_a_task` has a closed answer set and the Bridge's own
reason code. What is still missing is the **wiring** — nothing drives the export
on a timer or publishes its output — so on the live bus a Request with no settled
fact still reads `REQUEST_CREATED`. That is recorded as a remaining blocker, and
it is a wiring gap rather than a mechanism gap.

## Rank rules

`PROVEN` > `OBSERVED` > (`PENDING` / `HOLD` / `FAILED`) > `UNKNOWN`.

* `PROVEN` requires the artifact's own Ed25519 signature to verify against a
  pinned public key of the correct identity.
* `OBSERVED` means the record was read but its signature was not checked in this run.
* `UNKNOWN` always carries `value = null`. It never means "probably fine".
