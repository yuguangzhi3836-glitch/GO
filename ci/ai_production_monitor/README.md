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

## Run locally

```bash
python ci/ai_production_monitor/test_monitor.py
GITHUB_TOKEN=... GITHUB_REPOSITORY=yuguangzhi3836-glitch/GO \
  python ci/ai_production_monitor/monitor.py --dry-run
```

## Authority boundary

`MODE = OBSERVATION_ONLY`

The monitor is not C15, is not an acceptance gate, and `AUTHORIZES_ANY_ACTION = NO`.
