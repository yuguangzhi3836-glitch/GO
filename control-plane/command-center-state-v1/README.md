# GO Command Center — GitHub-native delivery V1

> Status: **Draft candidate, not installed, not running.**
> This directory changes no business source, no Hong Kong runtime, no live
> Command Center state and no Production. It adds a read-only projection layer
> plus the contracts the projection obeys.

## What this directory is for

It closes the single biggest product gap in the GitHub-native Control Plane:
**the Control Plane has Requests, Tasks and Evidence, but no derived STATE.**

Everything needed to answer *"what is happening right now?"* already exists on
the control bus. Nothing derives it. Every question still requires a human to
read dozens of Task files, the Bridge ledger and the agent ledger. ChatGPT is
asked to answer questions it cannot answer, so it guesses.

This directory adds a deterministic, rebuildable, non-authoritative projection:

```
control bus (read-only)            →  CURRENT_CONTROL_STATE.json   (full, with reasons)
  go-control-tasks  tasks/            CONTROL_STATUS_V1.json        (compact read contract)
  go-control-evidence  evidence/      TASK_INDEX.json               (Task → Evidence)
  Request files on control-bus refs   LATEST_EVIDENCE.json          (newest per action)
  GO docs/canonical-baseline/
```

## Verified current architecture

Read from the repository at the base commit of this branch, not from old notes.

| Element | Where it really is | Evidence |
|---|---|---|
| Request → Task Bridge | `control-plane/boss-test-pr-live-integration-v1/command-center/go-boss-request-bridge` (`1.2.0`), `control-plane/boss-deploy-request-v1/go-boss-request-bridge` (`1.4.0-candidate`) | 22 self-tests pass in each |
| Task repository | `chenzhenxi1-sudo/go-control-tasks` → `tasks/<task_id>.json` | 46 historical Tasks present |
| Evidence repository | `chenzhenxi1-sudo/go-control-evidence` → `evidence/<task_id>-<nonce>.json` | 24 historical Evidence files present |
| Request transport | a PR against `main` adding exactly one `requests/<request_id>.json`; the immutable PR head is ingested, the PR is never merged | `read_pr`, `request_path_from_changes`, 13 historical Request files on control-bus refs |
| Hong Kong Agent | `hk-staging/source/agent/hk_agent/transport.py` (`0.5.7-rebuilt`) | allowlist, one-attempt budget, SQLite ledger |
| Narrow Executor | `/usr/local/libexec/go-hk-deployctl` via `deployment_actions.py`; fixed argv list, no shell | `ProductionExecutor` rejects any argv not starting with the fixed path |
| Signing | task = Ed25519 hex, `GO-COMMAND-CENTER`; evidence = Ed25519 base64, Hong Kong key | `verify()` / `verify_evidence()` |
| Human approval | `HK_STAGING_DEPLOY` requires a signed `approval` bound to `plan_sha256` in `control-plane/boss-deploy-request-v1/go_deploy_request.py` | plan + approval + CANARY + VERIFY bundle validation |

### Answers to the required architecture questions

```
WHAT_IS_COMMAND_CENTER_NOW=the control-plane validator, policy gate, authority
  boundary, signer, task publisher and evidence verifier. It is not a chat site
  and it is not the primary human interface.

WHAT_ROLE_DOES_GITHUB_PLAY=transport, queue, audit trail, identity binding
  surface, immutable review surface and evidence transport. It is not Execution
  Authority: a PR, a README or a chat message authorizes nothing.

WHAT_ROLE_DOES_CHATGPT_PLAY=the primary human interface. It reads
  CONTROL_STATUS_V1 and it writes Request files. It never holds a key, never
  picks an execution parameter and never touches a shell.

WHAT_ROLE_DOES_HK_AGENT_PLAY=the execution-side entry point. It polls
  tasks/, verifies the signature, enforces the allowlist, expiry, replay and
  one-attempt budget, dispatches to the Narrow Executor, signs Evidence and
  publishes it.

WHAT_ROLE_DOES_EXECUTOR_PLAY=the only process boundary on Hong Kong. Fixed
  path, fixed argv, no shell, fixed eight business services, caddy and redis
  protected and never targeted.

WHAT_IS_EXECUTION_AUTHORITY=exactly one thing: a Signed Task that verifies
  against the pinned Command Center key, inside its validity window, with an
  unseen task_id and nonce, for an allowlisted action, with the frozen parameter
  contract. Nothing else. Not a GitHub PR. Not chat. Not a README.

WHAT_IS_THE_CURRENT_REQUEST_FLOW=human intent -> one requests/<id>.json on a
  control-bus ref -> Bridge validates and derives -> Signed Task.

WHAT_IS_THE_CURRENT_TASK_FLOW=Bridge publishes tasks/<task_id>.json ->
  HK Agent polls, verifies, claims one attempt, dispatches.

WHAT_IS_THE_CURRENT_EVIDENCE_FLOW=Agent signs and pushes
  evidence/<task_id>-<nonce>.json -> Command Center / ChatGPT verify the
  signature and read the frozen terminal result.

WHAT_STATE_WAS_MISSING=the projection. Requests, Tasks and Evidence existed;
  derived CURRENT_CONTROL_STATE, the compact ChatGPT read contract, the
  Task/Evidence index and a liveness representation did not.

WHAT_THIS_PR_ADDS=control-plane/command-center-state-v1: the projection tool,
  the six contracts, the closed lifecycle vocabulary, the ChatGPT read
  contract, an evidence index, a liveness representation that reuses the
  existing CONTROL_PLANE_HEALTH action, and 54 isolated tests.

WHAT_REMAINS_BEFORE_CC_V1_DELIVERY=see REMAINING_CC_V1_BLOCKERS in the PR body
  and in this README's final section.
```

## Web Command Center classification

The old Web Command Center is classified, not removed and not refactored:

```
OLD_WEB_UI_CLASSIFICATION = LEGACY / HISTORICAL_ARCHIVE /
                            OPTIONAL_OPERATOR_SURFACE
```

* The repository copy (`command-center/source/web/`, `command-center/nginx/`,
  `command-center/systemd/go-ai-command-center.service`) is a **2026-09-11
  archive** of an observed live gunicorn application. It is `HISTORICAL`.
* It is **not** the primary interaction path any more, which makes it `LEGACY`.
* It is still a deployed operator surface on Command Center, which makes it
  `OPTIONAL_OPERATOR_SURFACE`. Its live status was **not** re-verified by this
  PR: no live Command Center access was used.

No HTML, CSS, template or service unit was modified. The same systemd unit, the
same nginx config and the same gunicorn bind are untouched.

## Deliverables

| File | Role |
|---|---|
| `state_projection.py` | the projector: read-only, offline, deterministic, fail-closed |
| `contracts/request_v1.schema.json` | what a human / ChatGPT may submit, and what is forbidden |
| `contracts/task_v1.schema.json` | the Execution Authority envelope and the frozen parameter contracts |
| `contracts/evidence_v1.schema.json` | both published Evidence generations, and the terminal-result table |
| `contracts/control_state_v1.schema.json` | the projection format and the rank rules |
| `contracts/control_status_v1.schema.json` | the bounded ChatGPT read contract and the question map |
| `contracts/agent_liveness_v1.schema.json` | how liveness is represented and what it may never claim |
| `LIFECYCLE_V1.md` | the closed lifecycle vocabulary and what the control bus can see |
| `CHATGPT_CONTRACT_V1.md` | how a connector reads status and writes a Request |
| `tests/test_state_projection.py` | 54 tests |
| `run_checks.py` | isolated runner: no network, no subprocess, no runtime paths |
| `evidence/PROJECTION_20260914/` | a real projection of the live control bus at the recorded input SHAs |

## Running it

```sh
python control-plane/command-center-state-v1/state_projection.py \
  --tasks-repo    <local checkout of go-control-tasks> \
  --evidence-repo <local checkout of go-control-evidence> \
  --requests-dir  <collected Request files, optional> \
  --go-repo       <local checkout of GO, optional> \
  --task-verify-key <pinned Command Center task public key, optional> \
  --now           2026-09-14T12:00:00Z \
  --out           <output directory>

python control-plane/command-center-state-v1/run_checks.py /tmp/go-cc-state-checks
```

Pass `--now` to make the byte output reproducible. Without `--task-verify-key`
the projection honestly caps at `OBSERVED`.

## Agent liveness

The capability already exists and needs no new Hong Kong code:
`CONTROL_PLANE_HEALTH` is in the agent allowlist, its executor path is read-only
(`uname` nodename, `/proc/meminfo`, disk free), and its result is published as
ordinary signed Evidence. Nine historical `CONTROL_PLANE_HEALTH` Tasks exist.

What was missing is the **representation**, and it is now explicit:
`answers.hk_agent_online` is `PROVEN` only from a signature-verified liveness
Evidence inside the window, and `UNKNOWN` otherwise — with `last_seen` attached.
A successful VERIFY task is never accepted as liveness.

What is still missing is the **producer**: nothing drives
`CONTROL_PLANE_HEALTH` on a timer, so the control bus currently carries no fresh
liveness Evidence and the answer reads `UNKNOWN` even when the agent is healthy.
That is recorded as a delivery blocker rather than hidden behind a guess.

## Boundaries

```
APPLICATION_BUSINESS_CODE_CHANGE   = NO   (application/ untouched)
LIVE_HK_DEPLOYMENT                 = NO
PRODUCTION_ACTION                  = NO
MIGRATION                          = NO
SIGNING_KEY_CHANGE                 = NO
AUTHORITY_MODEL_WEAKENING          = NO
ARBITRARY_COMMAND_EXECUTION        = NO
DIRECT_CHAT_TO_SHELL               = NO
WEB_UI_REWRITE                     = NO
```

The projector is read-only: it opens directories, verifies signatures with an
optional public key, and writes only to `--out`. It holds no private key, no
token and no GitHub credential. It cannot publish a Task, cannot approve a plan
and cannot reach Hong Kong.

## REMAINING_CC_V1_BLOCKERS

1. **No verifier public key is published.** `command-center/audit/20260911/KEY_FINGERPRINTS.txt`
   archives fingerprints only, so any projection off the Control Plane caps at
   `OBSERVED`. Importing `PROVEN` control state into ChatGPT needs the public
   verifier keys to be distributed read-only with the state.
2. **A failed execution publishes no Evidence.** `transport.py` records a
   rejection in the agent-local SQLite ledger and never publishes signed
   Evidence, so `EXECUTION_FAILED` and `TASK_NOT_PICKED_UP` are unobservable
   from GitHub. The failure half of the lifecycle is only half closed.
3. **No liveness producer.** The `CONTROL_PLANE_HEALTH` action exists but nothing
   schedules it, so `hk_agent_online` is honest and useless.
4. **No publication target for the derived state.** The projector writes files;
   nothing yet pushes them where ChatGPT reads. Until Command Center publishes
   the state on the control bus, the contract exists but no reader sees it.
5. **Bridge ledger facts are not on the control bus.** Request rejection reasons,
   duplicate-request detection, ambiguity holds and plan/approval consumption
   live only in `/var/lib/go-command-center/boss-request-bridge-v1/ledger.json`.
   `REQUEST_REJECTED` and `REPLAY_REJECTED` at the Request layer stay invisible.

## Not proven by this PR

* Real HK-STAGING execution. All tests use ephemeral synthetic keys and fixtures.
* Deployment. `APPLICATION_HEALTH_PROVEN=false`, `DEPLOYMENT_PERFORMED=false`.
* Any claim about the current live Command Center switch, plan store, runtime
  processes or agent liveness. Those are Control Plane state, not control-bus
  state, and this projection explicitly reports them as `UNKNOWN`.
