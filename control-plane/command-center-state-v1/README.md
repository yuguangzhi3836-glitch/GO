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
DEPLOY_READINESS_EVALUATION        NOT_IN_SCOPE
ROLLBACK_READINESS_EVALUATION      NOT_IN_SCOPE
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
| `contracts/failure_evidence_v1.schema.json` | the signed failure record: its binding, its closed vocabularies, and what it may never authorize |
| `contracts/control_state_v1.schema.json` | the projection format and the rank rules |
| `contracts/control_status_v1.schema.json` | the bounded ChatGPT read contract and the question map |
| `contracts/agent_liveness_v1.schema.json` | how liveness is represented, and what it may never claim |
| `identity/VERIFIER_IDENTITIES_V1.json` | the published verifier identities, their fingerprints and their host provenance |
| `identity/keys/*.pub` | the two published public keys. No private key is ever published |
| `identity/README.md` | how the keys were obtained, how to bind them, and the five outcomes |
| `LIFECYCLE_V1.md` | the closed lifecycle vocabulary and what the control bus can see |
| `CHATGPT_CONTRACT_V1.md` | how a connector reads status and writes a Request |
| `tests/test_state_projection.py` | isolated tests, including signer-identity separation and identity binding |
| `tests/fixtures/real/` | 24 real signed Task/Evidence pairs, used as a live regression fixture |
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

A stable, read-only query contract that answers **exactly ten questions**, plus
one channel declaration. See `CHATGPT_CONTRACT_V1.md` for the full map:

```
1  HK Agent 最近是否有活动        → answers.hk_agent_recent_activity
2  当前有没有正在执行的任务        → answers.active_tasks
3  最近任务是否完成                → answers.last_task / last_evidence
4  PR X 是否已经 TEST_PR          → answers.pr_tested.by_pr_number["X"]
5  PR X TEST_PR 结果是什么         → answers.pr_tested.by_pr_number["X"][0]
6  最近一次 VERIFY 是否成功        → answers.verify
7  repository-declared runtime     → answers.repository_declared_runtime
8  该 runtime 最近是否被 live 证明  → answers.runtime_verification
9  当前是否存在 active stuck task   → answers.stuck_tasks.answer
10 最近一次失败是什么              → answers.last_failure
   which actions chat may request  → answers.request_channel
```

It cannot create a Task, sign, publish a Task, call an Executor, SSH, modify Hong
Kong, deploy or roll back.

### Deploy / rollback readiness is explicitly not part of this contract

```text
can_deploy                    REMOVED FROM THE CONTRACT
rollback_targets              REMOVED FROM THE CONTRACT
release_gates                 REMOVED FROM THE CONTRACT
deployment_eligibility        NEVER COMPUTED
DEPLOY_READY                  NEVER COMPUTED
```

`CONTROL_STATUS_V1.out_of_scope` states it:

```json
{"deploy_readiness_evaluation": "NOT_IN_SCOPE",
 "rollback_readiness_evaluation": "NOT_IN_SCOPE"}
```

Deploy readiness would have to combine an approved candidate, TEST_PR, VERIFY,
CANARY, Human Approval, a deployment plan, source/package/image binding, the
current runtime and the live Command Center switch. Rollback readiness would have
to combine a signed source DEPLOY task, its Evidence and Human Approval. Neither
belongs to this PR.

Recorded facts that could feed a later readiness design remain, but only as
non-contract data:

```
CURRENT_CONTROL_STATE.control_state.informational.contract = false
  rollback_candidate_history   from successful signed DEPLOY Evidence
  release_gates                read from the canonical pointer
  final_release_gate / hk_deploy_gate / production
CURRENT_CONTROL_STATE.control_state.deploy_capability
  {"capability": "CAPABILITY_PRESENT_BUT_DISABLED",
   "request_enabled": false,
   "readiness_evaluation": "NOT_IN_SCOPE"}
```

No test asserts their presence in `answers`, and a test asserts they are absent.

## P0-3 — Request → Task → Evidence lifecycle

The closed vocabulary and the observable/unobservable boundary are in
`LIFECYCLE_V1.md`. Three rules are load-bearing and enforced by tests:

* **`COMPLETE` requires both identities.** Evidence must verify against the Hong
  Kong evidence key *and* the Task must verify against the Command Center task
  key. Evidence that verifies alone stops at `EVIDENCE_VERIFIED` / `OBSERVED`.
* **`REQUEST_VALIDATED` requires a signed Task.** A Request file on the bus is
  human intent and nothing more. Acceptance is reported only when the named Task
  is present, carries `sha256(request_id)[:12]`, matches its claimed digest, and
  verifies under the bound published identity; otherwise the Request stays
  `REQUEST_CREATED` with the failed claim visible. See section 10.
* **Stuck is not the same as expired.** `answers.stuck_tasks.answer` reads
  `active_stuck_tasks` only. 21 expired historical Tasks do not make 21 things
  stuck.

No new execution capability is introduced.

## The corrections and additions this revision makes

### 1. Task and Evidence use different verification identities

```sh
--task-verify-key     <cc-task.pub>        # hex signature, Command Center task-manifest signer
--evidence-verify-key <hk-evidence.pub>    # base64 signature, Hong Kong agent evidence signer
--verifier-identities <VERIFIER_IDENTITIES_V1.json>
```

Two separate `Verifier` objects. A Task signed with the evidence key fails. An
Evidence signed with the task key fails. If both paths resolve to the *same*
public key the projection records a `VERIFIER_IDENTITY_COLLISION` anomaly and
refuses every `PROVEN` claim. Missing key means `NOT_PERFORMED`, which can never
become `PROVEN`. Tests use two independent ephemeral keys; no test uses one key
for both roles.

### 1b. A key that loads is not the right key (CC V1-01)

Supplying a key is not the same as supplying *the* key. The projection therefore
binds every verifier against the published identity contract:

```text
--verifier-identities defaults to identity/VERIFIER_IDENTITIES_V1.json
```

| Situation | `identity_binding` | Result |
|---|---|---|
| fingerprint matches the published pin | `BOUND` | `PROVEN` possible |
| no key supplied | `MISSING_KEY` | fail-closed, never `PROVEN` |
| key file does not load | `KEY_UNREADABLE` | fail-closed, never `PROVEN` |
| key loads, fingerprint differs | `IDENTITY_MISMATCH` | fail-closed, never `PROVEN` |
| no usable pin (contract missing/unreadable) | `IDENTITY_UNRESOLVED` | fail-closed, never `PROVEN` |
| one key supplied for both roles | `IDENTITY_COLLISION` | fail-closed, never `PROVEN` |

A verifier whose binding is not `BOUND` is disabled, so it cannot return `True`
and therefore cannot produce `PROVEN`. Its binding is still reported, so **"wrong
key" is never quietly downgraded to "no key"**. `verification.proven_allowed`
summarises the gate and `verification.fail_closed_reasons` names each failure.

### 2. The repository runtime pointer is not the live runtime

| Object | Meaning |
|---|---|
| `repository_runtime_pointer` | what the repository **declares**. `OBSERVED` at best, never `PROVEN` |
| `live_verified_runtime` | the image the newest VERIFY Evidence actually named |
| `runtime_verification` | `MATCH` / `DRIFT` / `NOT_RECENTLY_VERIFIED` / `UNKNOWN` |

`MATCH` and `DRIFT` require a VERIFY Evidence inside the verification window.
Older proof reports `NOT_RECENTLY_VERIFIED` even when the images agree.

### 3. DEPLOY is not exposed to chat, and its readiness is not evaluated

```json
{"enabled_request_actions": ["HK_STAGING_VERIFY", "HK_STAGING_TEST_PR"],
 "capability_classification": {
   "HK_STAGING_VERIFY": "SUPPORTED_PROVEN",
   "HK_STAGING_TEST_PR": "SUPPORTED_PROVEN",
   "HK_STAGING_DEPLOY": "CAPABILITY_PRESENT_BUT_DISABLED",
   "HK_STAGING_CANARY": "NOT_REQUESTABLE",
   "HK_STAGING_ROLLBACK": "NOT_REQUESTABLE"},
 "deploy_request_enabled": false,
 "readiness_evaluation": "NOT_IN_SCOPE"}
```

`known_capability` and `currently_enabled_request_action` are separate concepts
throughout the schema. The live Command Center channel switch is a live-host fact
and is reported as `UNKNOWN`, never asserted. No deployment plan is created, no
switch is modified, no DEPLOY Task is signed.

The contract computes no `can_deploy`, no deployment eligibility, no rollback
target selection and no release-gate verdict. Release-gate and rollback-candidate
facts survive only under `control_state.informational` with `contract=false`.

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

### 7. The verifier identities are published (CC V1-01)

Until CC V1-01 the repository archived **fingerprints only**, so nothing off the
control bus could be raised above `OBSERVED`. `identity/` now publishes both
verifier public keys with an identity contract, and the projection binds to it.

```text
GO-CC-TASK-MANIFEST-SIGNER   TASK       hex     SHA256:bkwH368MFv+n+18Pca6MB1jV4jZtBbsn8yjC1bf/hns
HK-AGENT-EVIDENCE-SIGNER     EVIDENCE   base64  SHA256:WZ2gG4WHnO5zmijyK8TSOHFpY+EBkk8TWbSbfbRjFNw
```

The binding is anchored on both sides: the fingerprint the Command Center signs
Tasks with is the same fingerprint the Hong Kong agent verifies them with, and
both agree with the 2026-09-11 audit archives already committed in this
repository. The two fingerprints differ, which is the separation requirement.

The keys were obtained by a single **read-only** operation on the Command Center
host with explicit human authorisation, verified twice, and are byte-identical to
the files on the host:

```text
retrieved   2026-09-14T14:34:46Z  over the Alibaba Cloud Workbench tunnel
read        /etc/go-command-center/keys/task-manifest-signing.pub
            /etc/go-command-center/deployment-plans-v1/authority.pub
            /etc/go-command-center/deployment-plans-v1/hk-evidence.pub
not read    any .pem, any *token*, any private key
not done    no write, no service change, no signing, no deployment
```

**No private key is published, and a test asserts it.**

### 8. Real history now reaches PROVEN

`tests/fixtures/real/` carries 24 real signed Task/Evidence pairs taken from the
control bus. Against the published keys they resolve, with no synthetic key
material:

```text
task_signature_verified       True   for all 24
evidence signature_verified   True   for all 24
lifecycle                     COMPLETE for all 24
assertion state               PROVEN  for all 24
actions covered               VERIFY 12, DEPLOY 4, TEST_PR 3, CANARY 2, health 2, ROLLBACK 1
```

Without the keys the same fixture stays at `OBSERVED`, which is the honest
before/after the publication buys.

The same binding was applied to the live-bus snapshot, which moved from
`EVIDENCE_PUBLISHED 24 | TASK_EXPIRED 21 | POLICY_HOLD 1` to
`COMPLETE 24 | TASK_EXPIRED 18 | POLICY_HOLD 4`. See
`evidence/PROJECTION_20260914/README.md` for what the three new failures are.

### 9. A failure is published, not swallowed (CC V1-02)

The failure half of the lifecycle used to live only in the agent-local SQLite
ledger, so the control bus could not tell "never picked up" from "picked up and
failed". A Task whose **claimed** execution attempt fails now publishes a signed
`FAILED` record to the same `evidence/<task_id>-<nonce>.json` path a success
uses, signed by the same Hong Kong evidence identity and bound to the original
`task_id`, `nonce`, `action_id` and `environment`.

The consumer side needed two corrections for that to be read honestly:

* **A signed non-success status is now evaluated before the validity window.** A
  failure is recorded when the attempt stopped, which may legitimately be after
  `expires_at`; only a claimed success can time out. Without this, every failure
  record would have been mislabelled `EVIDENCE_TIMEOUT`.
* **Two distinct records for one Task identity now fail closed.** They are
  reported as `EVIDENCE_CONFLICT` and capped at `EVIDENCE_VERIFIED` / `OBSERVED`,
  because one Task identity cannot have two outcomes; byte-identical duplicates
  are not a conflict.

A failure record authorizes nothing. The projection reports `retry_permitted`,
`replay_authorized` and `authorizes_any_action` as **false from the contract** and
separately reports what the artifact claimed, so a record claiming otherwise is
recorded and given no effect. `answers.last_failure` now carries the failure
`kind`, `stage` and `reason_code` alongside the Task that caused it.

### 10. What the Bridge did with a Request is now on the control bus (CC V1-05)

Acceptance was a Bridge-ledger fact that never reached the control bus, and a
refusal reason was printed to the Bridge's stdout and kept nowhere — the ledger
holds the accepted half and the `ignored` reasons only. Every Request could
therefore only be reported as `REQUEST_CREATED`, and *"why did my Request not
become a Task?"* had no answer on the bus.

`control-plane/command-center-request-visibility-v1` reads the ledger, the
operator's journalled copy of the Bridge's own poll output, and the collected
Request files — all read-only — and emits one Request fact per Request identity:
`REQUEST_CREATED`, `REQUEST_VALIDATED`, `REQUEST_REJECTED`, `REQUEST_DUPLICATE`,
`REQUEST_REPLAY_REJECTED`. The projection consumes it through
`--request-facts-dir` and publishes:

```
requests[].lifecycle                  the strongest fact that could be proven
requests[].lifecycle_source           BRIDGE_FACT / CONTROL_BUS_ONLY
requests[].why_not_a_task.state       a closed set, plus the Bridge's reason code
requests[].binding.proof_state        TASK_SIGNATURE_AND_DIGEST_PREFIX or NOT_ESTABLISHED
request_visibility.by_lifecycle       counts
request_visibility.rejected_or_refused           reason, class and origin
request_visibility.duplicate_or_replay           counted_as_success = false
request_visibility.acceptance_claims_without_a_signed_task
request_visibility.submissions_without_a_request_identity
answers.request_fate                  the answer surface for a ChatGPT connector
```

Four properties are enforced by tests rather than asserted in prose:

* **An acceptance is corroborated, never believed.** `REQUEST_VALIDATED` is
  accepted only when the named Task is on the control bus, its `task_id` carries
  `sha256(request_id)[:12]`, its claimed digest describes the Task as stored, its
  signature verifies, and the verifier is bound to the published identity. A
  failure leaves the Request at `REQUEST_CREATED`, surfaces the claim and the
  reason it failed, and records `REQUEST_BINDING_UNPROVEN` — never
  `REQUEST_VALIDATED`. Forging a positive fact would need the Task signing key.
* **A refusal never loses its reason.** The Bridge's token is carried verbatim
  with an `origin`; a token the contract cannot classify is
  `UNCLASSIFIED_REJECT`, and the contract is checked against every refusing token
  the Bridge sources can emit (81 today, zero unclassified).
* **A duplicate or a replay is never a success.** Each is its own lifecycle and
  each is reported with `counted_as_success = false`.
* **Nothing here is authority.** Every fact carries the same eight `false` values
  in its `authority` block, and the projection refuses any fact that claims
  otherwise. `request_visibility.facts_are_execution_authority` is false.

`TARGET_INSTALLED=NO`: nothing drives the export on a timer or publishes its
output, so a real projection supplies zero facts and every Request honestly reads
`REQUEST_CREATED`. The remaining gap is the missing wiring, not the missing
mechanism.

### 11. Readiness is evaluated read-only, and a YES is not an approval (CC V1-06)

`control-plane/command-center-deploy-readiness-v1` answers *"can we deploy now,
and why not"* as `DEPLOY_READY = YES / NO / UNKNOWN`, combining this projection's
output with an optional operator-supplied bundle of live-host facts. #94 kept
deploy readiness `NOT_IN_SCOPE` on purpose: it would have had to combine an
approved candidate, TEST_PR, VERIFY, CANARY, Human Approval, a deployment plan,
source/package/image binding, the current runtime and the live Command Center
switch. Every one of those now has a defined source, and the ones that are
live-host facts are `UNKNOWN` by construction rather than assumed.

Pass `--deploy-readiness <DEPLOY_READINESS.json>` and the state document carries:

```
control_state.deploy_readiness          value YES / NO, or the state is UNKNOWN with a null value
control_state.deploy_readiness_gates    one entry per gate, in the evaluator's order
control_state.out_of_scope.deploy_readiness_evaluation   EVALUATED_READ_ONLY
control_state.out_of_scope.deploy_readiness_document     the verdict's repository-relative path
```

Four properties are enforced by tests rather than asserted in prose:

* **Unprovable is never yes.** A mandatory gate that could not be established
  keeps the verdict at `UNKNOWN`; the projection carries that as an `UNKNOWN`
  assertion with a null value, and the per-gate detail is still there, so nothing
  is lost by the null.
* **A verdict is quoted, never computed here.** This layer evaluates nothing
  itself. Without a document it states nothing, and it never infers readiness
  from the presence of an approved candidate.
* **A verdict that claims authority is refused.** The evaluator's ten boundary
  flags must be exactly the published ones; any disagreement records
  `DEPLOY_READINESS_UNREADABLE` and leaves the state `UNKNOWN`.
* **`answers` is untouched.** The frozen ChatGPT contract still carries no
  `can_deploy`, no deployment eligibility, no `release_gates` and no
  `rollback_targets`. Surfacing readiness there is #107's decision, not this one.

Rollback readiness remains `NOT_IN_SCOPE`; CC V1-09 / #104 owns it and the
evaluator says so instead of guessing.

As of the committed projection the verdict is **`NO`**: the candidate commit has
never been TEST_PR'd on the control bus and the newest verified VERIFY is outside
its freshness window, while five further gates are unprovable offline.

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

TASK_VERIFIER_IDENTITY_PUBLISHED=PASS
EVIDENCE_VERIFIER_IDENTITY_PUBLISHED=PASS
VERIFIER_FINGERPRINT_BINDING=PASS
WRONG_KEY_REJECTED=PASS
CROSSED_IDENTITY_REJECTED=PASS
SAME_KEY_COLLISION_REJECTED=PASS
MISSING_KEY_NEVER_PROVEN=PASS
REAL_CONTROL_BUS_HISTORY_REACHES_PROVEN=PASS
PRIVATE_KEY_PUBLISHED=NO

SIGNED_FAILURE_EVIDENCE=PASS
FAILURE_BOUND_TO_TASK_IDENTITY=PASS
FAILURE_AUTHORIZES_NOTHING=PASS
FAILURE_OUTSIDE_VALIDITY_WINDOW_IS_EXECUTION_FAILED=PASS
CONFLICTING_FAILURE_RECORDS_FAIL_CLOSED=PASS
INSTALLED=NO

REPOSITORY_RUNTIME_AND_LIVE_RUNTIME_SEPARATED=PASS
ACTIVE_STUCK_TASK_CLASSIFICATION=PASS
WORKSTATION_LOCAL_PATHS_REMOVED=PASS

DEPLOY_REQUEST_ENABLED=NO
DEPLOY_PERFORMED=NO
DEPLOY_READINESS_EVALUATION=NOT_IN_SCOPE
ROLLBACK_READINESS_EVALUATION=NOT_IN_SCOPE
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
  --request-facts-dir <exported Bridge Request facts, optional> \
  --go-repo       <local checkout of GO, optional> \
  --task-verify-key     <pinned Command Center task public key, optional> \
  --evidence-verify-key <pinned Hong Kong evidence public key, optional> \
  --verifier-identities <identity/VERIFIER_IDENTITIES_V1.json> \
  --tasks-head <sha> --evidence-head <sha> --go-head <sha> \
  --repository-main-sha <sha> \
  --now 2026-09-14T12:00:00Z \
  --out <output directory>

python control-plane/command-center-state-v1/run_checks.py /tmp/go-cc-state-checks
```

Pass `--now` to make the byte output reproducible. Without the two verifier keys
the projection honestly caps at `OBSERVED` and never claims `PROVEN`. With them,
`PROVEN` additionally requires the keys to match the published identity contract;
`--verifier-identities` defaults to that contract and the two published `.pub`
files under `identity/keys/` are the intended inputs.

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
DEPLOY_READINESS_EVALUATION         NOT_IN_SCOPE
ROLLBACK_READINESS_EVALUATION       NOT_IN_SCOPE
```

The projector holds no private key, no token and no GitHub credential. It cannot
publish a Task, approve a plan, or reach Hong Kong.

## REMAINING_CC_V1_BLOCKERS

**Closed by CC V1-01:** verifier public keys are now published, bound and
fingerprint-pinned (`identity/`). The Control Plane no longer caps at `OBSERVED`.

**Closed by CC V1-02:** a claimed execution attempt that fails now publishes a
signed failure record, so "picked up and failed" is no longer invisible and
absence of Evidence now indicates no claim.

**Closed by CC V1-03:** a bounded liveness producer exists, so `CONTROL_PLANE_HEALTH`
is now driven on a clock instead of never.

**Closed by CC V1-04:** the derived state has a formal publication target
(`CURRENT.json` + immutable snapshots), so a reader has one stable entry point.

**Closed by CC V1-05:** the Bridge's Request facts are exported and projected, so
`REQUEST_REJECTED`, `REQUEST_DUPLICATE` and Request-layer
`REQUEST_REPLAY_REJECTED` are now expressible on the control bus with their
reasons.

1. **Three historical Tasks fail under the published Task signer.** With the
   identity now bound, `go-m3-042-e2e-health-20260905T151233846901Z`,
   `…20260905T152130238921Z` and `…20260906T011815978751Z` resolve as
   `POLICY_HOLD` / `FAILED` instead of silently expiring. They are structurally
   identical to Tasks that verify, and they verify under neither published
   identity, so they appear to carry a **third, earlier Task-signing identity**
   that was superseded before `2026-09-06T07:47:11Z` and whose public key is not
   published anywhere. Attribution is open; this is a real finding, not a
   defect introduced by CC V1-01.
2. **The failure closure is not installed.** The HK agent source now publishes
   failure records, but nothing is deployed by CC V1 and no installation is
   claimed. `INSTALLED=NO`. Live failure visibility therefore still depends on a
   later, separately approved install.
3. **The liveness producer is not installed.** The mechanism exists (CC V1-03)
   but no systemd unit or timer change has been made, so the control bus still
   carries no fresh liveness Evidence. `INSTALLED=NO`.
4. **The publication target is not wired.** The target and the publisher exist
   (CC V1-04) but nothing pushes to it, so `CURRENT.json` does not exist and a
   reader reports `UNKNOWN`. `TARGET_INSTALLED=NO`.
5. **The request fact export is not wired.** The exporter exists and CI verifies
   it (CC V1-05), but nothing drives it on a timer or publishes its output, so a
   real projection supplies zero facts, every Request reads `REQUEST_CREATED`,
   and refusal reasons stay unobservable from the control bus.
   `TARGET_INSTALLED=NO`.
6. **The deploy readiness evaluator is not scheduled.** The evaluator exists and
   CI verifies it (CC V1-06), but nothing runs it on a timer and no live bundle
   is published anywhere, so the readiness verdict is only as current as the
   operator's last run. `INSTALLED=NO`.
7. **Every remaining blocker above is a wiring gap, not a mechanism gap.** The
   mechanisms for failure closure, liveness, publication, request visibility and
   deploy readiness were each added by a CC V1 issue and are each uninstalled.
   Installing any of them is a separately approved change and is not implied by
   having built it.

## Not proven by this PR

* Real HK-STAGING execution. The identity fixtures are real control-bus records,
  but no live execution is performed or claimed here.
* Deployment. `APPLICATION_HEALTH_PROVEN=false`, `DEPLOYMENT_PERFORMED=false`.
* Any claim about the live Command Center switch, plan store, runtime processes or
  agent liveness. Those are Control Plane state, not control-bus state, and this
  projection explicitly reports them as `UNKNOWN`.
* That the published identities are the *only* identities that have ever signed
  in this ledger. They are not: three historical Tasks do not verify under either
  of them, and that is reported rather than smoothed over.
