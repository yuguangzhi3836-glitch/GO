# C14 scoped application authority-boundary review

`C14_SOURCE_AUTHORITY_BOUNDARY_GATE = PASS_SCOPED`

This is a static engineering review of four exact application diffs, not legal
advice, regulatory clearance, C13 independent test acceptance, release approval,
or permission to change HK-STAGING or Production. No business source was edited
by this review.

## Bound baseline and review method

- Baseline commit: `286e294d92df4b7d1c0073116a8e628734abec6c`.
- Baseline directory: `/workspace/scratch/2d68c25b0133/runtime-transport/source`.
  The parent coordinator reports that its complete 1325-file application tree
  has been verified. This review directly compared the four files listed below;
  it does not independently claim to have reverified all 1325 files.
- Candidate directory: `/workspace/scratch/2d68c25b0133/GO`.
- Exact comparisons used `git diff --no-index` on each baseline/candidate pair.
  A preliminary `diff --no-index` invocation was unsupported by GNU diff; it
  produced no comparison, and was replaced by the valid Git command.
- Read the four complete candidate modules, applicable ownership definitions,
  the existing SQL idempotency repository methods, hosted Stay/Night models,
  rental owner/transaction/isolation helpers, and four new targeted test files.
- Applicable constraints: current repository AGENTS/change control; V7 Cell
  ownership as represented by `autonomy/definitions.py`; user instruction to
  inherit PASS, close P0/P1 on existing application source, and not deploy.

## Per-domain decisions

| Change | Ownership / allowed scope | Boundary finding | Decision |
| --- | --- | --- | --- |
| `services/hosted_fare_value.py` | C01 hotel dated-accommodation facts; retain existing C11 money bridge | If a managed Stay exists but no current-date Night rows exist, the function raises `HOSTED_FARE_VALUE_INTEGRITY_INVALID` before returning a value or reaching downstream capture. It no longer silently recovers forfeited room value. Legacy reservations without a managed Stay keep the existing fallback. No new money writer is added. | ALLOW scoped source fix |
| `mobility/rental/service.py` | C04 rental order/refund lifecycle; existing C11 settlement bridge | Both completed-refund replay paths now require the order to be `REFUNDED`. Divergence raises `RENTAL_REFUND_RECONCILIATION_REQUIRED`; it does not repair state, create a refund, or claim money has settled. Owner checks, consent checks, isolated-settlement restriction, and transaction boundaries remain. | ALLOW scoped source fix |
| `journey/service.py` | C10 Journey projection; vertical orders remain owned by C01–C06 | List uses the same existing `_serialize(..., refresh=True)` as detail. `_order` checks the journey owner's order ownership. The new path reads canonical order status without changing vertical state or attachment snapshots. Existing active-membership visibility is unchanged. | ALLOW scoped source fix |
| `api/idempotency.py` | C11 transaction-safety concern implemented in a shared C12/platform mutation helper | Sync and async paths retain the existing durable claim after a callback returns successfully, when resource-ID extraction or completion persistence subsequently fails. Existing SQL claim behavior returns `IN_PROGRESS`, blocking another callback. No new platform/financial capability or arbitrary cross-domain writer is introduced. Shared-helper maintenance stays a central platform integration responsibility; this fix does not transfer C12 ownership to C11. | ALLOW scoped source fix |

## Fail-closed precision and unchanged rules

- Hotel: this adds an integrity denial only. It changes no fee, refund amount
  formula, change-validity window, credit terms, policy version, or treatment of
  legitimate lower-price forfeiture. It uses an existing Stay table/model and
  its existing reservation-ID primary key; no schema or migration is added.
- Rental: the first replay guard rejects inconsistent completed state before
  calling the money bridge. The second guard is after the existing settlement
  execution step and handles concurrent completion drift; it does **not** imply
  that no money movement could already have happened. It prevents a false
  success receipt and leaves reconciliation necessary. No additional fee,
  refund amount, payment destination, provider call, or automatic repair is added.
- Journey: existing account and active-member filters remain intact. Refresh
  uses owner-checked read access and preserves historical snapshots. The existing
  fallback to snapshot status when an order is missing/not owned remains; the
  change must not be described as proof that every rendered status is fresh.
- Idempotency: successful business effects are not treated as safe to repeat
  merely because response bookkeeping failed. Pre-result callback exception
  behavior, replay/conflict responses, and mandatory production key checks are
  unchanged. No cleanup/retry/reconciliation execution authority is invented.

## Residuals, not expanded clearance

1. An incomplete idempotency claim can remain blocked until reconciliation.
   This is an intentional duplicate-prevention versus availability tradeoff.
   No automatic reconciliation worker is established by this patch. A callback
   that commits a side effect and then raises still follows the inherited
   release-on-callback-exception path; this four-file review does not close that
   broader pre-existing atomicity problem.
2. Journey list performs additional per-item canonical reads. No 1000-user
   performance, database query-budget, provider, browser, or mobile acceptance is
   inferred from this source review. Existing missing-order fallback remains.
3. Hotel corruption that removes both the managed Stay marker and all Night
   rows is not distinguished from a legitimate legacy reservation by this
   narrow guard. Full durable provenance/reconciliation remains separate.
4. A rental terminal-state pair is an integrity condition, not independent
   evidence that actual provider/bank funds settled. Neither guard grants funds
   repair authority or changes who owns after-sales responsibility.
5. No new real legal policy, jurisdiction judgment, commercial commitment, data
   sharing permission, user fee, refund entitlement, or constitutional authority
   has been introduced or approved. C13 must independently bind test evidence
   to final candidate bytes before its scoped acceptance can be counted.

## No expansion checklist

| Area | Review result for these four diffs |
| --- | --- |
| Existing PASS work | Existing implementations reused; no business module rebuilt |
| Domain truth | No new cross-domain truth mutation or owner change |
| Money / commercial terms | No new fee, pricing rule, settlement formula, or refund destination |
| Schema / migration | None |
| Service/image topology | None |
| Deploy/runtime configuration | None |
| Credentials, signatures, permissions | None |
| HK DEPTH48 | Unchanged by this review; no server action performed |
| Production | HOLD; no clearance or operation |

## Exact reviewed SHA256 identities

Paths below are relative to `application/src/go_hotel/`.

| File | Baseline SHA256 | Reviewed candidate SHA256 |
| --- | --- | --- |
| `services/hosted_fare_value.py` | `4098dbb4d36de42454224c63c762d1cbdfb015136a8fd57655626c9deec428c0` | `cf9f2c3ed701419e974f2c9144724238be3ea1d82b18d979fdfbb1b0815ee4e5` |
| `mobility/rental/service.py` | `2792eb30b0624cdfc240828f61d715f9557bd94276038ea75895984b2b30e7d6` | `d8768e8eef0d2e083d6b777ba3eca38124caa801ecda49282c8308708f8c0c99` |
| `journey/service.py` | `c72da725c211a6f0aad169dd07804b8b9a4f602799b525d3bf19b9c84bf4e509` | `cbb4ad735e6a3a6632154dace37a80ef7945e95706bbfc17e1a32f674e0ab67b` |
| `api/idempotency.py` | `9786db63135e935fdf28c13b7565f7711af4fcb4c70764ecf3eca61dd78401cd` | `260a12d78f7e4b1cb375ee71e200486146feb3b8946ad1805ba5c15534f86c58` |

Conclusion: no blocking authority-boundary finding was identified in these four
reviewed deltas. Allow progression to C13 independent scoped acceptance and
evidence assembly only. Do not mark a Cell or the full system 100%, merge, deploy,
or lift any release gate solely on this review.

## Addendum — C08 synthesis-failure audit finalization

`C14_C08_SOURCE_AUTHORITY_BOUNDARY_GATE = PASS_SCOPED`

This addendum separately reviews the C08 delta. It does not alter the four-file
scope or identities above, and does not review C14's own release-guard code.

Reviewed `git diff --no-index` between the same fixed baseline and candidate for
`application/src/go_hotel/go_ai/service.py`, including its surrounding
`orchestrate`, `_execute_compute_task`, `_complete_request`, and request-audit
methods. Also read
`application/tests/go_ai/test_c08_synthesis_audit_finalization.py` and the actual
baseline-red/candidate-green logs produced by the developing Cell.

| Check | Finding |
| --- | --- |
| Domain owner | C08 GO AI orchestration/request audit. This changes no C09 Recommendation Truth, C10 Journey Truth, C11 Transaction Truth, or C12 provider/configuration authority. |
| Exact behavior | A synthesis-compute exception now calls the existing `_complete_request` with existing code `GO_AI_ORCHESTRATION_TASK_FAILED`, then rethrows the existing ValueError or wraps an unexpected Exception in that code. The same failure-finalization pattern already existed for subtasks. |
| Fail-closed result | A failed synthesis cannot continue into response verification/success completion through this path. With the existing audit database available, the request becomes FAILED instead of remaining ROUTING. No partial answer is promoted to success. |
| No retry expansion | Candidate selection, provider-attempt count, cost tier, parallelism, fallback ordering, and synthesis inputs are unchanged. No new retry, provider call, key lookup, or network endpoint is added. |
| Privacy / truth | The new write contains the existing failure code and audit state, not prompt/answer text. The successful advisory-only response boundary, deterministic order/payment authority, supplier-evidence rule, and GO Judgment boundaries remain unchanged. |
| Schema / commercial / deployment | No new table, field, migration, fee, commercial policy, runtime topology, deployment configuration, permission, or execution authority. |

The developing Cell's original logs show two baseline failures and one success,
then three candidate successes. The new tests use deterministic providers and a
per-test SQLite audit database, including the existing genuine worker thread.
This reviewer inspected those logs and tests; it did not rerun them or present
the developer runs as independent C13 execution.

Residual scope: a database failure while `_complete_request` persists the audit,
a missing request-audit row, process termination, or failures outside this
synthesis-compute block are not repaired here. Unexpected provider RuntimeError
still has no FAILED invocation row in the existing `_execute_compute_task`
contract; the targeted test expressly expects only the preceding successful
invocation, while confirming that the parent request is FAILED. Thus this is
request-level finalization closure, not complete provider-attempt audit coverage
or a durable recovery/retry guarantee. No blocking new authority-boundary finding
was identified in the delta.

### C08 exact identities and inspected developer evidence

| Item | SHA256 |
| --- | --- |
| Baseline `go_ai/service.py` | `cddeb74c559f9e82b28595f461a08f608288aa38646142a7ac9f50375759b8ca` |
| Reviewed candidate `go_ai/service.py` | `9b0ef8d9907155a60c143f55c8ecb32ec18dc2262a44354144d2fad71e1adf45` |
| New C08 test file | `1c431307f6c97dd2389950391bcaf0af93e99f9f3004088a8c0f31196d022327` |
| `c10-evidence/c08-baseline-red.junit.xml` | `95be66917f6765b141ca1942fd5b4a6f63f4d7bcd89605294df229cd489ec72e` |
| `c10-evidence/c08-candidate-green.junit.xml` | `adeb2c3152614ba86115ea5cf87fa221c3f882577584570510a03abe765b7719` |

The evidence paths are relative to `/workspace/scratch/2d68c25b0133`. C13 remains
the independent acceptance step. This source-boundary PASS authorizes neither
merge nor deployment and is not legal/production clearance. HK DEPTH48 remains
unchanged; Production remains HOLD.
