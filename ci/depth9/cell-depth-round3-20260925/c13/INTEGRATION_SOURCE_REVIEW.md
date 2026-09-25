# C13 Round 3 independent integration source review

Status: scoped source review and local regression complete; exact-candidate integration acceptance PENDING. No newly demonstrated blocker in this reviewed increment. This is neither a module completion claim nor a formal independent Lite Runner opinion.

The frozen v1.0.0 denominator remains 286 obligations / 933 required cases, scope hash `2a9ebac6832212e6118f2b1190f0d44b34a3bf814f17dddc244cd592d85df37e`. No atomic obligation is promoted to PASS by this review. Historical merchant-backend learning must be mapped explicitly; uncovered obligations are versioned additions, not retrospective claims of coverage.

## Binding and execution

`INTEGRATION_SOURCE_BINDING.json` records independently computed hashes: all 7 C04, 6 C05, 5 C11 and 5 C12 manifest files matched; four root integration files were additionally fingerprinted. Product SHA supplied by integrator is `54728d0ff26a8ab2217ca97639e57efc2cc8fbcf`; this local report does not itself verify the remote tree or a future gate head.

Independent run used APP_ENV=test, a dedicated SQLite file, PYTHONPATH=src, Python -B and pytest -p no:cacheprovider on:
- tests/test_rental_operations.py
- tests/test_c05_policy_operations.py
- tests/payments/test_c11_deposit_operations_review.py

Raw result `OPERATIONS_INDEPENDENT.xml`: **35 tests, 0 failures, 0 errors, 0 skips**, 9.405 seconds. These are independently executed existing regressions, not newly authored probes or evidence of PostgreSQL/browser behavior.

## Reviewed integration boundaries

- C04 operations API derives actor and unverified statement reference/hash server-side, delegates to domain authorization and version/idempotency checks, and records evidence in the same transaction. Workspace distinguishes permitted business actions from money authority. Consumer adapter serializes the body once; shared admin adapter passes an object to its own request wrapper.
- C04 widget persists pending command before submission, scopes storage to actor/order, reads current workspace and actor receipts after uncertain responses, and does not use an old successful response as current financial authority. Generation guards protect replaced views; unavailable storage/read failure blocks new commands.
- C11 review reads source/root/intent/fact/movements/ledger authority. Incomplete or unknown facts suppress monetary authorization; settled money and subsequent appeals do not license a new payout. Finance widget reads current source and injects matching revision/hash into existing guarded commands. Repair and compensation remain HOLD, not implemented capabilities.
- C05 registry is isolated and opt-in, authenticates real stored admin/session/permissions, requires different maker/checker, binds audit hash and policy version, and serializes offer policy resolution/revocation. Accepted order snapshots remain immutable. Missing/invalid opted-in policy does not fall back to synthetic file authority. Activation is engineering readiness only.
- Root main includes both new routers. Admin index loads widgets before shared module; config declares policy route; shared navigation and custom dispatch reach it. Rental order view mounts business/finance widgets with order/route generation checks. Backend authorization remains decisive even when a navigation link is visible.
- C12 fixtures create isolated authenticated identities and enable the registry, not pre-approve business policy. Positive policy, rental dispute/appeal/adjudication/settlement and no-damage release writes are actual UI submissions. The maker self-approval call and read-only finance call are explicit negative API checks.
- Browser subprocess, mocked-widget subprocess and each SQL audit exit code participate in the mandatory gate. Private accounts and database are not copied into evidence; isolated state is removed in finally.
- operations-ledger.py independently opens SQLite read-only and joins two separate completed rental orders to root, intent, fact binding, confirmed movement graph, balanced ledger and evidence-chain hashes. It checks distinct orders from original journeys, one authorization/release and optional capture, parent references, 5000 capture versus zero-capture release, conservation, latest case and distinct reviewers. This is additional isolated SQL evidence, not a production-money assertion.

## Required next evidence and limits

Run the exact new gate head, verify source-binding/tree fingerprint and raw artifacts, and inspect actual browser outcomes and PG incremental cases. The original six-domain journeys and original money audit must remain mandatory. A harness that is statically correct has not yet demonstrated real clicks or database execution.

Source review plus 35 local tests does not cover all required cases or dependencies of a frozen atomic obligation. Authority repairs, compensation after settled appeals, all-team ongoing operations, and other unimplemented requirements retain their current NOT_ASSESSED/HOLD states. No prior ecab PASS transfers automatically. No deployment or external integration is authorized by this report.
