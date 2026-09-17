# CONTROL_STATUS_V1 — the ChatGPT read contract

Scope: `CONTROL_STATE_AND_STATUS_ONLY`. This contract is read-only. It cannot
create a Task, sign anything, publish a Task, call an Executor, open a shell,
reach Hong Kong, deploy or roll back.

ChatGPT must not parse dozens of Task JSON files, the Bridge ledger, the agent
ledger, Compose files or server logs. It reads one bounded document.

## The contract answers exactly ten questions

```
1  HK Agent 最近是否有活动         → answers.hk_agent_recent_activity
2  当前有没有正在执行的任务         → answers.active_tasks
3  最近任务是否完成                → answers.last_task (+ answers.last_evidence)
4  PR X 是否已经 TEST_PR           → answers.pr_tested.by_pr_number["X"]
5  PR X TEST_PR 结果是什么          → answers.pr_tested.by_pr_number["X"][0]
6  最近一次 VERIFY 是否成功         → answers.verify
7  repository-declared runtime     → answers.repository_declared_runtime
8  该 runtime 最近是否被 live 证明   → answers.runtime_verification (+ answers.live_verified_runtime)
9  当前是否存在 active stuck task   → answers.stuck_tasks.answer
10 最近一次失败是什么               → answers.last_failure
```

Plus one channel declaration and one fate lookup:

```
which actions chat may request     → answers.request_channel
why did my Request not become a Task → answers.request_fate.by_request_id[request_id].why_not_a_task
```

Every other key in `answers` is a **supporting field**, never a required one:
`last_evidence`, `live_verified_runtime`, `go_is_healthy`, `hk_agent_online`,
`repository_main_sha`, `runtime_built_from_main_sha`, `request_fate`.

## Answer shapes

| Question | Read | Answer shape |
|---|---|---|
| 1 | `answers.hk_agent_recent_activity` | last signed `CONTROL_PLANE_HEALTH` at any age, with `age_seconds` |
| 2 | `answers.active_tasks` | count plus the task list |
| 3 | `answers.last_task` → `answers.last_evidence` | task id, lifecycle, completion time |
| 4 | `answers.pr_tested.by_pr_number["X"]` | present or absent; `in_flight` lists pending ones |
| 5 | `answers.pr_tested.by_pr_number["X"][0]` | `TEST_PR_OK`, immutable commit SHA, built image id, completion time |
| 6 | `answers.verify` | lifecycle plus assertion rank |
| 7 | `answers.repository_declared_runtime` | image config id, tag, generation, pointer path |
| 8 | `answers.runtime_verification` | `MATCH` / `DRIFT` / `NOT_RECENTLY_VERIFIED` / `UNKNOWN` plus the image relation |
| 9 | `answers.stuck_tasks.answer` | `YES` / `NO`, computed from `active_stuck_tasks` only |
| 10 | `answers.last_failure` | task id plus `kind` = `FAILED_RECORD` or `EXPIRED_WITHOUT_EVIDENCE` |

## Read the documents

```
CONTROL_STATUS_V1.json      # compact, fixed question keys, size-bounded
CURRENT_CONTROL_STATE.json  # full projection: every Request, Task and Evidence, with reasons
TASK_INDEX.json             # one row per Task, linked to its Evidence
LATEST_EVIDENCE.json        # newest Evidence per action
```

All four come from one run and cannot disagree with each other. Every source
reference inside them is a repository-relative path such as
`tasks/<task_id>.json`; there is no workstation path anywhere.

## What this contract does NOT do

```text
can_deploy                          NOT COMPUTED   (no such key exists in answers)
deployment eligibility              NOT COMPUTED
DEPLOY_READY                        NOT COMPUTED
rollback target selection           NOT COMPUTED
rollback readiness                  NOT COMPUTED
release-gate verdict                NOT COMPUTED
```

`out_of_scope` states this explicitly:

```json
{"deploy_readiness_evaluation": "NOT_IN_SCOPE",
 "rollback_readiness_evaluation": "NOT_IN_SCOPE"}
```

Deploy readiness would have to combine an approved candidate, TEST_PR, VERIFY,
CANARY, Human Approval, a deployment plan, source/package/image binding, the
current runtime and the live Command Center switch. Rollback readiness would have
to combine a signed source DEPLOY task, its Evidence and Human Approval. Neither
is implemented here, and no answer may be read as if it were.

Recorded facts that could feed a later readiness design stay in
`CURRENT_CONTROL_STATE.control_state.informational` with `contract=false`
(rollback candidate history from signed DEPLOY Evidence, the release gates read
from the canonical pointer, Production). They are facts, not a verdict.

## The distinctions a connector must preserve

1. **Activity is not liveness.** `answers.hk_agent_recent_activity` answers "when
   did we last hear from it". `answers.hk_agent_online` answers "is it online
   now" and is `PROVEN` only from liveness Evidence inside the freshness window.
   Never answer the second with the first.
2. **A repository pointer is not the live runtime.** `repository_declared_runtime`
   is what the repository declares; `live_verified_runtime` is what a VERIFY
   Evidence actually proved. They are separate objects and the first can never
   make the second `PROVEN`.
3. **Expired history is not stuck work.** `answers.stuck_tasks.answer` reads
   `active_stuck_tasks` only. `recent_expired_tasks` and
   `historical_expired_tasks` are indexed separately and never change the answer.
4. **A capability present is not a request enabled, and a platform probe is not a
   human right.** `answers.request_channel` separates `known_capabilities` from
   `enabled_request_actions`, and separates `human_request_actions` from
   `platform_request_actions`. You may write a Request file only for an action in
   `enabled_human_request_actions`. `CONTROL_PLANE_HEALTH` is created by the
   platform's own bounded producer: it carries fixed empty parameters, it is
   read-only, and it confers no execution or deploy authority on anyone.
5. **`repository_main_sha` is not the runtime build source.**
   `answers.repository_main_sha` is `UNKNOWN` unless it was established out of
   band; `answers.runtime_built_from_main_sha` is a different field with a
   different meaning.

## The request channel

```
HUMAN_REQUEST_ACTIONS       HK_STAGING_VERIFY     SUPPORTED_PROVEN                enabled
                            HK_STAGING_TEST_PR    SUPPORTED_PROVEN                enabled
                            HK_STAGING_DEPLOY     SUPPORTED_PROVEN                    enabled
                            HK_STAGING_CANARY     CAPABILITY_PRESENT_REQUESTABLE  enabled
                            HK_STAGING_ROLLBACK   CAPABILITY_PRESENT_REQUESTABLE  enabled
PLATFORM_REQUEST_ACTIONS    CONTROL_PLANE_HEALTH  SUPPORTED_PROVEN_PLATFORM_ONLY  enabled
```

The connector may write a Request file only for an action listed in
`enabled_human_request_actions`, and DEPLOY is one of them. There is no deploy
switch and nothing to open: a DEPLOY Request is itself the Human Approval — its
author as reported by GitHub, its platform `created_at`, and the digest of its
canonical content — so a request that asks to deploy this candidate is the whole
of the authorisation. Command Center derives the plan and the one-time
authorisation from facts it already holds.

Every enabled action has the same shape. It supplies `action_id`, `environment`, a
fresh `request_id` and `requested_at`, and at most one target selector: `pr_number`
for `HK_STAGING_TEST_PR`. A `HK_STAGING_ROLLBACK` Request carries nothing else: the
deployment it undoes is the newest one the Bridge published, and the images to restore
come from that deployment's own record on the host, so the connector cannot name a
deployment, a service, an image or a target even though it can ask for the undo. It may never write a `CONTROL_PLANE_HEALTH` Request: that
action is the platform's read-only probe, created by the platform's own producer
on a timer, and writing one by hand would forge an automation identity.

Being enabled is not a promise that the host will accept it. Whether the host
currently accepts a DEPLOY Request is a live-host fact reported as
`live_request_switch`, and the host answers for itself: a host with deployments
suspended refuses the Request with `deployment_authorization_mode_unsupported`.
Report that token and stop; do not retry, and do not treat it as a defect in the
Request. A DEPLOY Request must also be opened after that candidate's CANARY and
after a preflight VERIFY, because those are the windows the host itself re-reads.

The connector must never supply an image id, repo digest, service list, compose
path, env file, shell command, executor path, signature, nonce, `task_id`,
`release_id`, `approval_id`, `canary_evidence_id`, `source_deploy_task_id` or
`plan_id`. `plan_id` is not a Request field at all any more: plans are derived by
Command Center, so the Bridge refuses a Request that still carries one rather than
reading around the field. Do not submit it, and do not try to prepare a plan or
declare a release gate — neither is expressible.

## Creating a Request on GitHub

1. Branch from current `main` of `chenzhenxi1-sudo/go-control-tasks`.
2. Add exactly one `requests/<request_id>.json`. Nothing else.
3. Open a PR targeting `main`. Do not merge it — Command Center ingests the
   immutable PR head.
4. Read the result from Signed Evidence, never from the PR.

## Reading what happened to a Request

A Request file existing means a human wrote it. It never means the Request was
accepted, so never infer acceptance from a branch, a PR or a file:

```
answers.request_fate.by_request_id["<request_id>"]
    lifecycle            REQUEST_CREATED / VALIDATED / REJECTED / DUPLICATE /
                         REPLAY_REJECTED / UNKNOWN
    why_not_a_task.state closed set:
                           BECAME_A_TASK                    only with a signed Task behind it
                           ACCEPTANCE_CLAIMED_BUT_UNPROVEN   a claim that could not be corroborated
                           REFUSED
                           DUPLICATE_REQUEST_ID
                           REPLAYED_SUBMISSION
                           NOT_SETTLED_BY_BRIDGE            the Bridge spoke: not settled yet
                           NO_BRIDGE_FACT_OBSERVED
                           REQUEST_NOT_ON_THE_BUS
    why_not_a_task.reason_code  the Bridge's own token, verbatim
    binding.proof_state  TASK_SIGNATURE_AND_DIGEST_PREFIX / NOT_ESTABLISHED / NOT_APPLICABLE
```

`requests[].why_not_a_task` carries the same answer per Request, and
`request_visibility` carries the counts, the refusals with their reason class and
origin, the duplicate/replay list, and the submissions that could not be bound to
a Request identity at all.

Three things to hold on to:

* **A Bridge fact is an observation, not a permission.** It authorizes no retry,
  no replay and no action, whatever it says.
* **A duplicate or a replay is never a success**, and each is reported with
  `counted_as_success = false`.
* **`BECAME_A_TASK` is the only state that means the Request became work**, and it
  appears only when a signed Task on the control bus carries that Request's
  digest and verifies. If the fact export is not wired yet, every Request reads
  `REQUEST_CREATED` — that is honest, not a failure.
