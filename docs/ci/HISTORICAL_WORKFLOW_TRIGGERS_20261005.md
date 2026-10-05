# Historical workflow trigger scope — 2026-10-05

Change classes: BUILD, TEST_ONLY, DOCUMENTATION.
Base main: ee4a0a4ea4c9a95b7017b8db991de7554962f42a.

## Scope

Four workflow path entries replace application/** with a workflow-specific
.github/historical-gates/<workflow-basename>.json path. Every other existing
path, job, source check, anchor, dependency, permission and failure condition
is unchanged. No source manifest rebinding, application changes, new action,
dispatch, privileged event, continue-on-error or skip-on-anchor-mismatch.

Ordinary application PRs are outside these frozen historical gates. Existing
specialist CI/package/compatibility paths and changes to each workflow itself
still invoke the original exact-source checks.

## Explicit opt-in

For a historical acceptance request that otherwise changes application only,
add or modify the corresponding JSON file in the same PR:
- .github/historical-gates/v70-cell-gap-closure.json
- .github/historical-gates/canonical-parent-retention.json
- .github/historical-gates/depth47-module-boundaries.json
- .github/historical-gates/v70-next-depth-postgres.json

Suggested content: {"reason":"Explain this historical acceptance request"}.
This is only a changed-path trigger: contents are NOT parsed, not an authority
grant, not a source selector and not a validated source identity. Even an empty,
malformed or deleted marker can trigger; it cannot bypass any existing gate.
A file merely present on main is not an opt-in for unrelated future PRs.
PR three-dot diff, not just the latest commit, determines path membership.
Keep the marker in the requesting PR diff through review. Not triggered does
not mean historical acceptance PASS. No opt-in files are added by this patch.

## Validation

historical-trigger-validation-20261005.json records 84 local assertions:
YAML parsing, only the intended on.pull_request.paths semantic delta, exact
jobs bytes, smoke/application negative cases, every retained path positive
case, mixed application/specialist diffs, marker isolation and main filtering.
The path simulation is limited to the exact paths and trailing /** patterns
actually present. It is not a GitHub execution or PostgreSQL/browser test.

Remote acceptance cases:
1. This PR edits all four workflows: all four are expected to trigger.
2. At unchanged main application bytes, old frozen-source mismatches must
   remain failures, individually attributed from actual run logs.
3. After approved merge, refresh #425 on new main; its six original changed
   paths should not invoke these four workflows. That live check is pending.
4. A specialist or opt-in PR with wrong source must fail; valid source must
   proceed to the original tests, with test failures still failing the job.

Existing canonical-parent-retention !cancelled() test conditions are retained;
they can run after prerequisite failure. Any resulting secondary missing-
dependency errors must be reported separately, not mistaken for the first
failure or claimed fixed by this trigger-only patch.

## Branch configuration

Read-only GitHub /branches/main response: protected=false,
protection.enabled=false, required_status_checks.enforcement_level=off,
contexts=[], checks=[]. Repository /rulesets response: [].
The dedicated /branches/main/protection endpoint returned403 due to integration
permissions. The positive branch response and empty ruleset list show no
global required status checks in the observed configuration; not inferred
from403. Recheck before merge if repository settings change. No settings edited.

## Parallel candidates

#425 remains separate and unchanged.
#427 (fix/acceptance-source-binding-20261005) includes #425 plus manifest
rebinding and failure-stage changes, and touches all four workflows. This PR
neither incorporates nor approves it. Its specialist path changes still
trigger historical gates after this patch. If merged in either order, recheck
the final workflow diff; retain this trigger scope and independently reviewed
#427 job changes rather than replacing whole files. Do not duplicate #425
if #427 becomes the chosen integration route.

## Review and rollback

An independent read-only review is requested for the exact submitted head;
that is not formal Runtime C14/C13 acceptance. CI failure is not PASS.
No merge/deploy authorization is conveyed. #407–#418 remain undispatched.
Revert the dedicated change through a reviewed PR, restoring the four
application/** entries. No application, database or runtime rollback needed.
