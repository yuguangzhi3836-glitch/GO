# AI Production Quality Monitor

Observation-only metrics for long-lived Issue #260.

This monitor reads existing sealed C13/C14 GitHub Actions artifacts and refreshes only the marked `Live Metrics` section of Issue #260. It does not change C13/C14 verdicts, candidates, branches, merge state, deployment state, or runtime.

## Current scope

Available now:

- unique candidate SHA count from sealed C14 reviews
- C14 PASS / NOT_APPLICABLE / FAIL / BLOCKED counts
- C13 PASS / FAIL / BLOCKED counts
- same-SHA C14-to-C13 full-pass count
- Today / rolling 7-day / rolling 30-day windows

Deliberately unavailable until a stable origin work-item identity is carried across candidate revisions:

- true first-pass rate
- rework depth
- current blocked backlog by logical work item

The monitor reports these as `NOT_YET_AVAILABLE` instead of inferring lineage from SHA or task-name patterns.

## Boss 14-Cell daily digest

The same monitor also summarizes what the Product Owner actually asked C01-C14 to do today.

- source of Boss intent: Formal C01-C12 Task Issues created by `yuguangzhi3836-glitch`
- manual C14 Review Issues are included; automatic C13 results come from sealed review evidence
- linked Builder PRs are found from the existing Issue/work-order identity in PR bodies
- C14/C13 `FAIL` or `BLOCKED` is reported as a candidate/review blocker, **not** as a Runtime failure
- monitor/API read warnings are `NON_BLOCKING_OBSERVATION`; they do not create remediation work
- Runtime is reopened only for a proven generic transport failure such as task loss, duplicate paid dispatch, broken lease/attempt fencing, wrong candidate/result adoption, generic Builder failure, broken C14→C13 chaining, or unrecoverable in-flight work

Schedule on `main`: **12:00 and 17:00 Asia/Shanghai (UTC+8)**. Both runs refresh the same marked section in long-lived Issue #260; no second monitor, queue, authority or scheduler is introduced.

`AUTO_REPAIR_RUNTIME = NO` remains a deliberate boundary.
## Run locally

```bash
python ci/ai_production_monitor/test_monitor.py
GITHUB_TOKEN=... GITHUB_REPOSITORY=yuguangzhi3836-glitch/GO \
  python ci/ai_production_monitor/monitor.py --dry-run
```

## Authority boundary

`MODE = OBSERVATION_ONLY`

The monitor is not C15, is not an acceptance gate, and `AUTHORIZES_ANY_ACTION = NO`.
