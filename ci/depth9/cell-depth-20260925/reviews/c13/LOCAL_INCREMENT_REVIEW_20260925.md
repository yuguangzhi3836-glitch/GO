# C13 local increment review — initial finding

Scope is local uncommitted candidate only, not formal C13 acceptance. Reviewer did not modify product code. No external systems, provider, PSP, merge or deployment used.

## Validation

Independent isolated SQLite command:

`GO_TEST_DB_PATH=/tmp/go_c13_review_20260925.db PYTHONPATH=src:. ../../go-venv/bin/python -m pytest -q tests/test_rental_damage_disputes.py tests/autonomy/test_policy_lifecycle_binding.py --junitxml=/workspace/scratch/cdb63add4518/reviews/c13/local-increment-junit.xml`

Result: 43 tests passed (16 rental +27 policy lifecycle). This does not demonstrate PostgreSQL concurrency or production HTTP authentication. The rental HTTP tests override the principal in an isolated router app.

## Blocking finding C13-LOCAL-001

`damage._history` trusts `list_vertical_evidence` payload without checking the stored execution-item/order binding or stored chain integrity. The helper selects only `execution_id` and exposes no validation. Therefore a damaged historical row can drive later adjudication rather than fail closed.

Independent reproduction on separate SQLite database `/tmp/go_c13_damage_corrupt_probe.db`:

1. Create the completed order fixture, call `claim()` to open one damage case.
2. Set its `JourneyRecoveryEvidenceChainRow.execution_item_id` to `foreign-rental-order` without changing `execution_id`.
3. Call `damage.respond(OWNER, order_id, case_id, 'respond-corrupt', 1, 'DISPUTE', ev('c'))`.
4. Actual output: `CORRUPTED_EXECUTION_ITEM_ACCEPTED REVIEW_REQUIRED`.

Required fix: validate historical damage evidence against the exact order and hash/sequence chain before replay/read/transition, refuse malformed or conflicting records, and prove refusal appends nothing. In particular validate execution_item, embedded order, case owner and case identity. Keep the repair local to the damage reader where possible rather than redesigning the shared evidence store. Finding reported to root and C04 for implementation.

## Other observations

- Rental mutations remain explicitly isolated; no supplier tenant access, appeal, verified original evidence or C11 funds execution is implemented. Decision remains `C11_MONEY_REVIEW_REQUIRED`. This incremental feature is not module 100%.
- Snapshot cap and claim cap, caller-bound idempotency, independent maker/checker, stale response rejection and append rollback are tested. SQLite serialization is not evidence of PostgreSQL process safety.
- Policy lifecycle change binds conditions to full version/approval/validity/content hash, preserves restrictive rules, checks expiration/revocation and checks policy again after condition resolution. No blocking defect found in the reviewed local lifecycle increment. Synthetic policy approval references do not approve real law or contracts; registry origin and caller authorization remain external responsibilities.

## File SHA256 captured after the first run (repair had landed concurrently)

| File | SHA256 |
|---|---|
| rental/damage.py | 63bd2b60ae0fa0f4989031408bd55952408dd43686e3d91f96df3d4e5e6ea32a |
| api/routes/rental_damage.py | c2763081545c3b8bc466898e629a97405baa8e66139cff8bce06bf55a347f412 |
| autonomy/action_control.py | 290ad29a48e057022cb911f7fdecbe601902c15a64bef7851b81eb3e9eed322e |
| autonomy/types.py | a0aeb541030395f7191482b9df8ee85acb9764b8bb2094a47042e102d110dacc |
| autonomy/condition_evidence.py | 6ec835cd92019daf5443bb4a577b2224b12579850f53bd9e9945a6cad69b4903 |
| tests/test_rental_damage_disputes.py | 615a204b160c6a28d8fa62dc1f5c80a8af80b975a1bad9bb1f6dcc7100115261 |
| tests/autonomy/test_policy_lifecycle_binding.py | 7e1f49750c1fe044933c3f7027f2311ef539e80e153adb7fee1b32f4cd6231ff |

## C13-LOCAL-001 resolution

C04 added full evidence chain verification, execution-item/order/owner binding and five corruption regressions. Reviewer read the repair and independently ran the frozen 21-case rental test file on `/tmp/go_c13_damage_recheck_20260925.db`: **21 passed**, JUnit `rental-fixed-junit.xml`. The file hashes above were captured after that repair had already landed, and describe this repaired first-batch scope, not the vulnerable original. C13-LOCAL-001 is closed for these bytes. The original finding is retained for history.

Disposition: repaired rental first-batch local scope has no remaining blocker found; policy lifecycle no blocker found within limited review. The absence of PostgreSQL/full-auth/device/funds evidence remains explicit. No formal independent acceptance or release authority is created by this report. Later appeal changes require separate inspection.
