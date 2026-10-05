# Runtime ingress recovery — 2026-10-05

Change classes: PRODUCT_FIX, CONTROL_PLANE, TEST_ONLY, DOCUMENTATION.
Base: bf633805b7dad35ffa9cd4bb7e9f2407cb0fe753.
Candidate only; NOT_LIVE_VERIFIED. No merge, host installation, restart or deployment.

## Observed failure chain

- #420 and #447 both used V74-R1-C12-01. Running the actual base parser locally produced the same key `c1-ghaw-builder-v1:C12:V74-R1-C12-01`, with different payload hashes:
  - #420: bfcc7fbfda7579b3063b561eddbbf489cd5a34abf7f4025fa11ebba1f407efef
  - #447: 02ffa3183f08065806325ed895a5ba1db21fd592108353c540756e0cb74663ef
- #447's body contained 4410 characters, but its objective contained only 288: the parser stops at the first blank line. The later restrictions were not in its execution payload.
- #447 was closed as superseded/not planned, not completed. #448 used fresh V79-R1-C12-01 and the full 1595-character objective was validated before publication.
- Runtime automatically dispatched run [37324212522](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/37324212522), Runtime task `rt_fbb5e2d2e06f4b11aad9bbc084249b96`, attempt 1. The actual job log says `WORK_ORDER_ACCEPTED V79-R1-C12-01 C12`. Agent sandbox Python smoke passed 4 tests.
- That Builder later failed at 183.846950 / 180 AI credits. Its partial edits had failing tests; no Draft PR or sealed result was delivered. Those edits are NOT adopted here. This candidate is a smaller independently implemented fix against the frozen base. No paid Builder rerun or budget increase.
- An offline injected Runtime enqueue exception also reproduced a whole-poll abort on the base. This is a source-level recovery defect, not a readback of the host's queue.

## Minimal change

1. The ingress's existing parser and key function identify different issue numbers claiming one key in the already-fetched bounded open-issue snapshot. Source freshness is deliberately checked later: an older-source open issue can already own that key.
2. The consumer refuses the colliding issues with issue-number evidence. It never changes the key or appends an issue number to bypass deduplication.
3. Runtime construction / per-issue enqueue exceptions are reported using fixed safe codes. Later independent Builder issues and C14 review issues can still be processed. A possibly committed enqueue is retried only with the existing deterministic key on a later poll.
4. The owner README now explicitly requires historical task-ID uniqueness and validation of the actual first-paragraph payload.

No changes to worker dispatch, lease fencing, Runtime kernel, models, budgets, workflows, database, business logic or service topology. No new persistent component or durable identity store.

## Validation

Python 3.12.14, isolated local materialization of the frozen runtime-channel source.

```
cd control-plane/runtime-host-channel-v1
python3 -m unittest test_c1_issue_consumer test_c1_issue_ingress test_c1_ingress_recovery test_c1_ghaw_registration
# 139 tests, 0 failures, 0 errors, 0 skipped
```

126 pre-existing tests and 13 new recovery cases. The bounded-candidate test now uses distinct task IDs, so it tests the processing limit instead of supplying conflicting identities. No source/authority assertion was removed.

The C13 adapter was also executed locally with pytest 9.1.1 and `--noconftest`: 1 adapter passed, invoking all 139 backend tests with zero skips. This verifies the adapter, not the full application conftest or remote C13 environment.

New coverage: duplicate IDs; stale-source collision; same-issue repeat; no cross-poll store; collision beyond processing cutoff but within fetched snapshot; malformed issue; closed-history limitation; disabled/no Runtime access; continued Builder and review processing after conflict; Builder/review enqueue exceptions; Runtime-open recovery; lost enqueue response with one durable row.

`application/tests/test_c13_runtime_ingress_recovery.py` is the explicit C13 no-DB inventory adapter. It executes these actual four suites in a subprocess from the same frozen checkout, requires exactly 139 tests and zero skips, and prints their result. It does not stand for application business acceptance.

## Limits and operational acceptance still required

- Conflict detection is limited to the bounded open-issue snapshot. Closed/unlisted historical owners and changed payloads across polls are NOT detected by this patch. The current Runtime API lacks a reliable read-by-key contract; this candidate does not pretend otherwise.
- No live heartbeat/lease/queue snapshot was available through this session. The new run proves dispatch and execution started, not 14 healthy services or continuous recovery.
- No heartbeat/status framework is included in this narrow candidate. That remains subsequent bounded work after this fix is accepted.
- Independent C14 then C13 review must bind this candidate's exact head; CI and review status must be read back separately.
- Installation is separate from merging. Through the existing authorized host-management path, verify installed source identity and consumer active/enabled state; read current poll records, task/lease/outbox state, and Builder/review ticks. Do not run an enabled `--once` command as a read-only probe: it can enqueue/claim work.
- Never reset/delete queue rows or outboxes, reuse the old external task ID, or dispatch a second paid attempt to bypass a stuck result. Preserve #448's failure evidence.
- Recovery point is the previous installed consumer/ingress source pair. Rollback requires the normal authorized operation; this patch requires no data migration.

## Baseline regression repaired before final review

Remote run 37326953532 executed 646 tests and had one failure: the unchanged registration test expected one post-step artifact although the existing portable-Python workflow uploads two. The same failing method was reproduced locally with the frozen base test and workflow. Only the assertion is corrected: exactly one identity-bound result artifact plus exactly one named Python-environment artifact with its four explicit paths; duplicates and arbitrary extra uploads remain rejected. Workflow, result name/path and result sealing are unchanged. All 45 registration tests pass locally; the explicit C13 adapter now executes 139 tests across four suites. Earlier 94-test evidence belongs to the first candidate revision.

## Independent review remediation

C14 round FORMAL-REVIEW-I450-3dc8e29c067c (run 37327185908) returned FAIL solely for C14-CLASS-001: missing PRODUCT_FIX classification. The declaration above is corrected while retaining CONTROL_PLANE, TEST_ONLY and DOCUMENTATION. That opinion remains bound to the earlier head; this revised candidate requires a fresh C14 round and automatic C13 if admitted. No prior PASS is transferred.
