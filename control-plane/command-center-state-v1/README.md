# Command Center — derived control state and status query V1

> Status: **Draft candidate, not installed, not running.**
> Scope: **`CONTROL_STATE_AND_STATUS_ONLY`**.

This directory changes no business source, no Hong Kong runtime, no live Command
Center state and no Production. It adds a read-only projection layer plus the
contracts the projection obeys.

## What this is, and what it deliberately is not

The Control Plane already has `HK_STAGING_VERIFY` and `HK_STAGING_TEST_PR` proven
end to end, and it already carries Requests, Signed Tasks and Signed Evidence.
Nothing derives **state** from them, so every status question still requires a
human to read dozens of Task files and two ledgers.

This PR closes that gap and nothing else. It is not "complete Command Center V1".

Explicitly out of scope and not attempted here:

```
DEPLOY request enablement          NOT DONE   (capability stays fail-closed)
DEPLOY / image switch E2E          NOT DONE
ROLLBACK Request schema            NOT ADDED
CANARY Request schema              NOT ADDED
Business runtime / application     NOT TOUCHED
Alembic migrations                 NOT TOUCHED
Web Command Center (Flask / HTML)  NOT TOUCHED
Signing authority / key rotation   NOT CHANGED
Executor surface                   NOT WIDENED
```

## Deliverables

| File | Role |
|---|---|
| `state_projection.py` | the projector: read-only, offline, deterministic, fail-closed |
| `contracts/request_v1.schema.json` | what a human / ChatGPT may submit, and what is forbidden |
| `contracts/task_v1.schema.json` | the Execution Authority envelope and the frozen parameter contracts |
| `contracts/evidence_v1.schema.json` | both published Evidence generations, and the terminal-result table |
| `contracts/control_state_v1.schema.json` | the projection format and the rank rules |
| `contracts/control_status_v1.schema.json` | the bounded ChatGPT read contract and the question map |
| `contracts/agent_liveness_v1.schema.json` | how liveness is represented, and what it may never claim |
| `LIFECYCLE_V1.md` | the closed lifecycle vocabulary and what the control bus can see |
| `CHATGPT_CONTRACT_V1.md` | how a connector reads status and writes a Request |
| `tests/test_state_projection.py` | isolated tests, including signer-identity separation |
| `run_checks.py` | isolated runner: no network, no subprocess, no runtime paths |
| `evidence/PROJECTION_20260914/` | a real projection of the live control bus at pinned revisions |

## P0-1 — Control State

`state_projection.py` reads local checkouts and emits four derived documents:

```
CURRENT_CONTROL_STATE.json   # every Request, Task and Evidence, each with state, reason and refs
CONTROL_STATUS_V1.json       # the compact read contract
TASK_INDEX.json              # one row per Task, linked to its Evidence
LATEST_EVIDENCE.json         # newest Evidence per action
```

Properties, all enforced by tests:

* **derived** — no field is authored by hand;
* **rebuildable** — one command, same inputs, same bytes;
* **deterministic** — `--now` is the only time source;
* **not Execution Authority** — the document says so, in the document;
* **portable** — the output contains no workstation path, no temp directory and
  no local absolute path. Sources are `repository` / `ref` / `commit SHA` /
  repository-relative path. Running the same inputs on two machines produces a
  semantically equivalent document.

It expresses, at minimum: the last Request, the last Signed Task, the last Signed
Evidence, the currently active tasks, the last successful VERIFY, the last
successful TEST_PR (with PR number and immutable SHA), the last failed task, the
active stuck tasks, the recent and historical expired tasks, the last provable
Hong Kong Agent activity, the repository runtime pointer, the live-runtime
verification status, runtime drift, and the projection time.

## P0-2 — CONTROL_STATUS_V1

A stable, read-only query contract covering exactly the ten questions asked of
it. See `CHATGPT_CONTRACT_V1.md` for the full map:

```
1  HK Agent 最近是否有活动        → answers.hk_agent_recent_activity
2  当前有没有正在执行的任务        → answers.active_tasks
3  最近一个任务完成了吗            → answers.last_task / last_evidence
4  PR X 是否已经 TEST_PR          → answers.pr_tested.by_pr_number["X"]
5  PR X 测试结果是什么             → answers.pr_tested.by_pr_number["X"][0]
6  最近一次 VERIFY 是否成功        → answers.verify
7  当前 repository-declared runtime → answers.repository_declared_runtime
8  该 runtime 最近是否被 live 证明  → answers.runtime_verification
9  当前有没有活跃 stuck task       → answers.stuck_tasks.answer
10 最近一次失败是什么              → answers.last_failure
```

It cannot create a Task, sign, publish a Task, call an Executor, SSH, modify Hong
Kong, deploy or roll back.

## P0-3 — Request → Task → Evidence lifecycle

The closed vocabulary and the observable/unobservable boundary are in
`LIFECYCLE_V1.md`. Two rules are load-bearing and enforced by tests:

* **`COMPLETE` requires both identities.** Evidence must verify against the Hong
  Kong evidence key *and* the Task must verify against the Command Center task
  key. Evidence that verifies alone stops at `EVIDENCE_VERIFIED` / `OBSERVED`.
* **Stuck is not the same as expired.** `answers.stuck_tasks.answer` reads
  `active_stuck_tasks` only. 21 expired historical Tasks do not make 21 things
  stuck.

No new execution capability is introduced.

## The six corrections this revision makes

### 1. Task and Evidence use different verification identities

```sh
--task-verify-key      <cc-task.pub>        # hex signature, Command Center task-manifest signer
--evidence-verify-key  <hk-evidence.pub>    # base64 signature, Hong Kong agent evidence signer
```

Two separate `Verifier` objects. A Task signed with the evidence key fails. An
Evidence signed with the task key fails. If both paths resolve to the *same*
public key the projection records a `VERIFIER_IDENTITY_COLLISION` anomaly and
refuses every `PROVEN` claim. Missing key means `NOT_PERFORMED`, which can never
become `PROVEN`. Tests use two independent ephemeral keys; no test uses one key
for both roles.

### 2. The repository runtime pointer is not the live runtime

| Object | Meaning |
|---|---|
| `repository_runtime_pointer` | what the repository **declares**. `OBSERVED` at best, never `PROVEN` |
| `live_verified_runtime` | the image the newest VERIFY Evidence actually named |
| `runtime_verification` | `MATCH` / `DRIFT` / `NOT_RECENTLY_VERIFIED` / `UNKNOWN` |

`MATCH` and `DRIFT` require a VERIFY Evidence inside the verification window.
Older proof reports `NOT_RECENTLY_VERIFIED` even when the images agree.

### 3. DEPLOY is not exposed to chat

```json
{"enabled_request_actions": ["HK_STAGING_VERIFY", "HK_STAGING_TEST_PR"],
 "capability_classification": {
   "HK_STAGING_VERIFY": "SUPPORTED_PROVEN",
   "HK_STAGING_TEST_PR": "SUPPORTED_PROVEN",
   "HK_STAGING_DEPLOY": "CAPABILITY_PRESENT_BUT_DISABLED",
   "HK_STAGING_CANARY": "NOT_REQUESTABLE",
   "HK_STAGING_ROLLBACK": "NOT_REQUESTABLE"},
 "deploy_request_enabled": false}
```

`known_capability` and `currently_enabled_request_action` are separate concepts
throughout the schema. The live Command Center channel switch is a live-host fact
and is reported as `UNKNOWN`, never asserted. No deployment plan is created, no
switch is modified, no DEPLOY Task is signed.

### 4. `current_main` is gone

```
repository_main_sha        UNKNOWN unless supplied via --repository-main-sha
runtime_built_from_main_sha  the product source commit recorded by the runtime pointer
runtime_canonical_main_sha   the main commit the canonical runtime definition was frozen at
```

The projector never substitutes a runtime source SHA for the repository head.

### 5. Stuck tasks are classified

`active_tasks` / `active_stuck_tasks` / `recent_expired_tasks` /
`historical_expired_tasks`. Only the first two affect the current answer; only
`active_stuck_tasks` answers "is anything stuck".

### 6. The derived state is machine-independent

No `D:/...`, no temp path, no user directory. Anomalies name
`chenzhenxi1-sudo/go-control-tasks/tasks`, not a disk path. There is a built-in
`LOCAL_PATH_LEAK` guard and a test that scans the whole output.

## Verified current architecture

Read from repository evidence, not from old notes.

| Element | Where it really is |
|---|---|
| Request → Task Bridge | `control-plane/boss-test-pr-live-integration-v1/command-center/go-boss-request-bridge` (`1.2.0`), 22/22 self-tests |
| DEPLOY request entry | `control-plane/boss-deploy-request-v1/go-boss-request-bridge` (`1.4.0-candidate`), 22/22 self-tests — **capability only, not enabled** |
| Task repository | `chenzhenxi1-sudo/go-control-tasks` → `tasks/<task_id>.json`, 46 historical Tasks |
| Evidence repository | `chenzhenxi1-sudo/go-control-evidence` → `evidence/<task_id>-<nonce>.json`, 24 historical records |
| Request transport | a PR adding exactly one `requests/<request_id>.json`; the immutable PR head is ingested and the PR is never merged; 13 historical Requests |
| Hong Kong Agent | `hk-staging/source/agent/hk_agent/transport.py` (`0.5.7-rebuilt`) |
| Narrow Executor | `/usr/local/libexec/go-hk-deployctl` via `deployment_actions.py`, fixed argv, no shell |

```
WHAT_IS_EXECUTION_AUTHORITY=exactly one thing: a Signed Task that verifies against the pinned
  Command Center task key, inside its validity window, with an unseen task_id and nonce, for an
  allowlisted action, with the frozen parameter contract. Not a PR, not chat, not a README.

WHAT_ROLE_DOES_GITHUB_PLAY=transport, queue, audit trail, identity binding surface, immutable
  review surface, evidence transport. Never Execution Authority.

WHAT_ROLE_DOES_CHATGPT_PLAY=read CONTROL_STATUS_V1, write Request files for enabled actions,
  and nothing else. No key, no execution parameter, no shell.

WHAT_ROLE_DOES_HK_AGENT_PLAY=poll tasks/, verify, enforce allowlist/expiry/replay/one-attempt
  budget, dispatch to the Narrow Executor, sign Evidence, publish it.

WHAT_ROLE_DOES_EXECUTOR_PLAY=the only process boundary on Hong Kong: fixed path, fixed argv,
  no shell, fixed eight business services, caddy and redis protected.

WHAT_IS_COMMAND_CENTER_NOW=validator, policy gate, authority boundary, signer, task publisher,
  evidence verifier, and now also the projector of derived state. Not a chat site.

WHAT_STATE_WAS_MISSING=the projection: derived control state, the compact read contract, the
  Task/Evidence index, and a liveness representation.

WHAT_THIS_PR_ADDS=the projector, six contracts, the closed lifecycle vocabulary, the ChatGPT
  read contract, the evidence index, the liveness representation that reuses the existing
  CONTROL_PLANE_HEALTH action, isolated tests, and a real projection of the live control bus.

WHAT_REMAINS_BEFORE_CC_V1_DELIVERY=see REMAINING_CC_V1_BLOCKERS below.
```

## Acceptance summary

```text
SCOPE=CONTROL_STATE_AND_STATUS_ONLY

VERIFY_STATUS_QUERY=PASS
TEST_PR_STATUS_QUERY=PASS
TASK_LIFECYCLE_PROJECTION=PASS

TASK_SIGNATURE_IDENTITY_SEPARATION=PASS
EVIDENCE_SIGNATURE_IDENTITY_SEPARATION=PASS

REPOSITORY_RUNTIME_AND_LIVE_RUNTIME_SEPARATED=PASS
ACTIVE_STUCK_TASK_CLASSIFICATION=PASS
WORKSTATION_LOCAL_PATHS_REMOVED=PASS

DEPLOY_REQUEST_ENABLED=NO
DEPLOY_PERFORMED=NO
ROLLBACK_REQUEST_ADDED=NO
CANARY_REQUEST_ADDED=NO
WEB_UI_CHANGED=NO
HK_RUNTIME_CHANGED=NO
APPLICATION_CHANGED=NO
PRODUCTION_TOUCHED=NO
```

## Running it

```sh
python control-plane/command-center-state-v1/state_projection.py \
  --tasks-repo    <local checkout of go-control-tasks> \
  --evidence-repo <local checkout of go-control-evidence> \
  --requests-dir  <collected Request files, optional> \
  --go-repo       <local checkout of GO, optional> \
  --task-verify-key     <pinned Command Center task public key, optional> \
  --evidence-verify-key <pinned Hong Kong evidence public key, optional> \
  --tasks-head <sha> --evidence-head <sha> --go-head <sha> \
  --repository-main-sha <sha> \
  --now 2026-09-14T12:00:00Z \
  --out <output directory>

python control-plane/command-center-state-v1/run_checks.py /tmp/go-cc-state-checks
```

Pass `--now` to make the byte output reproducible. Without the two verifier keys
the projection honestly caps at `OBSERVED` and never claims `PROVEN`.

## Agent liveness

The capability already exists and needs no new Hong Kong code:
`CONTROL_PLANE_HEALTH` is in the agent allowlist, its executor path is read-only
(`uname` nodename, `/proc/meminfo`, disk free), and its result is published as
ordinary signed Evidence.

Two questions are kept separate:

```
hk_agent_recent_activity   the newest signed probe at any age  → "when did we last hear from it"
hk_agent_online            PROVEN only from liveness Evidence inside the window → "is it online now"
```

What is still missing is the **producer**: nothing drives `CONTROL_PLANE_HEALTH`
on a timer, so the control bus carries no fresh liveness Evidence and
`hk_agent_online` honestly reads `UNKNOWN` even when the agent is healthy.

## Relationship to the project context layer

`docs/project/GO_CURRENT_STATE.md`, `docs/project/CONTEXT_CHECKPOINT.json` and
`docs/state/` are a **human-readable narrative context layer**, refreshed by a
Pull Request and keyed to a `checkpoint_main_sha`. This layer is different in
kind: derived from the control bus, never hand-edited, rebuildable at any
instant. Neither replaces the other and neither is Execution Authority.

## Web Command Center classification

```
OLD_WEB_UI_CLASSIFICATION = LEGACY / HISTORICAL_ARCHIVE / OPTIONAL_OPERATOR_SURFACE
```

The repository copy is a 2026-09-11 archive of an observed live gunicorn
application. It is no longer the primary interaction path. Its live status was
**not** re-verified by this PR. No HTML, CSS, template, nginx or systemd file was
modified and nothing was deleted.

## Boundaries

```
APPLICATION_BUSINESS_CODE_CHANGE    NO
LIVE_HK_DEPLOYMENT                  NO
PRODUCTION_ACTION                   NO
MIGRATION                           NO
UNAPPROVED_TASK                     NO
SIGNING_KEY_CHANGE                  NO
AUTHORITY_MODEL_WEAKENING           NO
ARBITRARY_COMMAND_EXECUTION         NO
DIRECT_CHAT_TO_SHELL                NO
WEB_UI_REWRITE                      NO
```

The projector holds no private key, no token and no GitHub credential. It cannot
publish a Task, approve a plan, or reach Hong Kong.

## REMAINING_CC_V1_BLOCKERS

1. **No verifier public key is published.** `command-center/audit/20260911/KEY_FINGERPRINTS.txt`
   archives fingerprints only, so any projection off the Control Plane caps at
   `OBSERVED`. Importing `PROVEN` control state into ChatGPT needs the public
   verifier keys distributed read-only alongside the state.
2. **A failed execution publishes no Evidence.** `transport.py` records a
   rejection in the agent-local SQLite ledger and never publishes signed Evidence,
   so `EXECUTION_FAILED` and `TASK_NOT_PICKED_UP` are unobservable from GitHub.
   The failure half of the lifecycle is only half closed.
3. **No liveness producer.** `CONTROL_PLANE_HEALTH` exists but nothing schedules
   it, so `hk_agent_online` is honest and useless.
4. **No publication target for the derived state.** The projector writes files;
   nothing yet pushes them where ChatGPT reads. Until Command Center publishes
   the state on the control bus, the contract exists but no reader sees it.
5. **Bridge ledger facts are not on the control bus.** Request rejection reasons,
   duplicate-request detection, ambiguity holds and plan/approval consumption live
   only in `/var/lib/go-command-center/boss-request-bridge-v1/ledger.json`.
   `REQUEST_REJECTED` and Request-layer `REPLAY_REJECTED` stay invisible.

## Not proven by this PR

* Real HK-STAGING execution. All tests use ephemeral synthetic keys and fixtures.
* Deployment. `APPLICATION_HEALTH_PROVEN=false`, `DEPLOYMENT_PERFORMED=false`.
* Any claim about the live Command Center switch, plan store, runtime processes or
  agent liveness. Those are Control Plane state, not control-bus state, and this
  projection explicitly reports them as `UNKNOWN`.
