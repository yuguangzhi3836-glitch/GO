# CONTROL_STATUS_V1 — the ChatGPT read contract

ChatGPT must not parse dozens of Task JSON files, the Bridge ledger, the agent
ledger, Compose files or server logs. It reads one bounded document.

## Read the document

```
CONTROL_STATUS_V1.json      # compact, fixed question keys, size-bounded
CURRENT_CONTROL_STATE.json  # full projection: every Request, Task and Evidence, with reasons
TASK_INDEX.json             # one row per Task, linked to its Evidence
LATEST_EVIDENCE.json        # newest Evidence per action
```

All four are derived from the same run and cannot disagree with each other.

## Question → key

| A human asks | Read | Answer shape |
|---|---|---|
| GO 现在正常吗？ | `answers.go_is_healthy` | `state` + `value` (`HEALTHY_AS_OF_LAST_PROBE`) + `as_of` + `age_seconds` + `stale` |
| 香港 Agent 在线吗？ | `answers.hk_agent_online` | `PROVEN` only from a fresh signed liveness probe; otherwise `UNKNOWN` with `last_seen` |
| 我刚才的任务执行了吗？ | `answers.my_task_executed` | `last_request` → `last_task` → `last_evidence` chain |
| PR 123 测了吗？测试结果是什么？ | `answers.pr_tested.by_pr_number["123"]` | commit SHA, lifecycle, built image id, completion time |
| 现在香港跑哪个版本？ | `answers.current_runtime` | image config id + `control_plane_drift` verdict |
| 最近一次部署是什么？ | `answers.deploy` + `answers.rollback_targets` | newest successful DEPLOY Evidence, rollback candidate set |
| 能不能部署？为什么不能？ | `answers.can_deploy` | `value` is `NO` while a release gate is `HOLD`, plus every blocking reason |
| 有没有任务卡住？有没有 Evidence 回来？ | `answers.stuck_tasks` / `answers.pending_evidence` | Task ids with expiry and lifecycle |
| 可以回滚到哪？ | `answers.rollback_targets` | verified DEPLOY task ids, newest first |
| Control Plane 漂移了吗？ | `answers.control_plane_drift` | `NONE` / `DRIFT` / `UNKNOWN` with both image ids |

## The three sentences a connector must never say

1. *"The agent is online"* — unless a fresh signed `CONTROL_PLANE_HEALTH` Evidence
   is inside the liveness window. A successful VERIFY task is not liveness.
2. *"The task failed"* — unless signed Evidence reports a non-success status.
   Absence of Evidence means `UNKNOWN`, not failure.
3. *"Deployment is approved"* — deployability is governed by the live Command
   Center switch, an approved plan in the root-owned store, and fresh CANARY /
   VERIFY proofs. None of those are readable from the control bus, and all three
   release gates are `HOLD`.

## Creating a Request from chat

The connector may write only the Request contract
(`contracts/request_v1.schema.json`). It may supply `action_id`, `environment`,
`request_id`, `requested_at`, and one target selector: `pr_number` for
`HK_STAGING_TEST_PR` or `plan_id` for `HK_STAGING_DEPLOY`.

It must never supply an image id, repo digest, service list, compose path, env
file, shell command, executor path, signature, nonce, `task_id`, `release_id`,
`approval_id`, `canary_evidence_id` or `source_deploy_task_id`. Those are derived
by Command Center from fixed, root-owned, human-approved state.

## Creating a Request on GitHub

1. Branch from current `main` of `chenzhenxi1-sudo/go-control-tasks`.
2. Add exactly one `requests/<request_id>.json`. Nothing else.
3. Open a PR targeting `main`. Do not merge it — Command Center ingests the
   immutable PR head.
4. Read the result from Signed Evidence, never from the PR.
