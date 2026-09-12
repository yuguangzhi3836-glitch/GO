# Local credit acceptance clock repair

Base: 6f3e9c197a46419c4dea8aac0bd00f889024e801 (inherits PR53 audit changes).
Original immutable DEPTH46 application tree: 365b848d419ca5517b2cf711c271694bde346e33.

PRODUCT_FIX / TEST_ONLY. Added a current-stay eligibility check inside conversion_facts, called under the order lock during both quotation and acceptance. It uses catalog_cash_fare.facts' latest confirmed check-in, and preserves the existing UTC date-level future-stay policy. No hotel timezone policy, credit expiry formula, historical contract, schema or runtime changes.

Local Python 3.12.14, dependency-isolated AST-loaded actual source functions with mocked SQL/session/provider dependencies. Before/after raw outputs are retained here. Baseline exposes missed eligibility rejection (including reaching supplier preparation); repaired version passes 5 unittest methods. This does NOT demonstrate actual database rollback, real provider calls, PostgreSQL concurrency, browser/mobile journeys or Hong Kong runtime behavior. Two passing baseline compatibility cases remain passing (future contract payload and existing conversion replay).

Reproduce repaired checks:
`python -B -m unittest discover -s application/tests -p test_credit_acceptance_clock_unit.py -v`

The test does not import the full application or install external dependencies. A full dependency environment was not available locally. Before logs use the same test harness with baseline service source loaded instead of the repaired source.

This source-only candidate is saved separately without opening a PR or triggering CI; commit uses [skip ci]. GitHub Actions quota exhaustion is USER_REPORTED, not independently inspected billing evidence. No merge/deployment/installation, no network/auth changes, and no Hong Kong/Production access.

IMPORTANT: inherited CURRENT_CANDIDATE/CURRENT_PARENT fingerprints describe the old verified parent, NOT this modified application. This branch is not a sealed or installable parent. Full updated source-manifest/alignment registration, application regression and independent CI remain required before review/merge. Historical parent and evidence bytes are preserved. All complete-business/release gates HOLD.

Still open: credit redemption timezone semantics, new-vs-historical expiry policy, six-vertical fulfillment completion, final visible cross-end money/state coverage. No claim of 100% completion.
