# Flight and hotel date release verification — 2026-10-01

Scope: Owner asked to unblock controlled Hong Kong publication and verify the existing Chinese airport, search simulation-panel and single-calendar hotel date fixes. PRODUCT_FIX / TEST_ONLY / DOCUMENTATION. No DOT/Runtime source added.

## Fixed source under inspection

- Parent PR #298: e109af4dc4ae84f27f63d0104aa42c8d6b64b34d; root tree c4f4faa0182e9cd1c200033cff57d82b3fd8c40f.
- Control-plane PR #299: 510cc086d0697d2b8ea1ad03a371d159e80600fc; open/unmerged at inspection.
- This increment is stacked on #298; it is NOT complete historical non-DOT retention or an admitted release.

## Product findings and correction

1. Chinese input is retained. Search route inputs have no three-letter pattern and accept up to 120 characters. The real airport resolver and JourneySearch Pydantic validators resolve 福州 -> FOC and 哈尔滨 -> HRB. Existing quote/provider/production truth controls remain.
2. #298 had only renamed the search sidebar's 模拟体验 block to 服务状态, retaining the unwanted panel. This increment removes that entire default sidebar status block. Quote and order disclosures about unconnected live inventory/ticketing remain unchanged. The flight JS cache identifier is advanced in index.html.
3. Hotel dates are retained, not missing. PR #267 fixed source 679f56e71d9aa5d7cb9205eb55bd1a277225c21e and #298 both have date-range.js Git blob 0caa12ec298ebde1b7f79193195fe75ce71f2ee8. showExplore and showHotelSearch bind cin/cout; direct.js binds checkIn/checkOut. index.html and direct.html load date-range.js?v=20260927-mobile1. bind changes native date inputs to readonly text, and openPicker keeps both selections in one dialog and writes both fields only at its single confirmation. No date implementation rewrite is required.

## Actually executed locally

- node application/scripts/check_flight_search_release.cjs: PASS. Real flight script evaluated with explicitly doubled DOM and API. Asserts rendered search inputs have no IATA-only pattern; no simulation/status panel; Chinese request payload; same-route refusal; quote/order truth preserved; cache identifier.
- python application/scripts/check_flight_airport_models.py: PASS, 8 cases. Real resolver plus exact AST model definitions from journeys.py with Pydantic 2.13.5. Chinese city, full airport name, lowercase IATA, English whitespace, fullwidth IATA all resolve FOC/HRB. Alias-equivalent same airport, unknown airport and ambiguous Shanghai reject. No HTTP/database/provider test claimed.
- node --test application/tests/test_mobile_date_range.cjs: 4/4 PASS, 0 failed/skipped. Existing range, cross-month/year, zero-night refusal, restart/edit and native-picker binding tests.
- node --check application/frontend/consumer/flight-journeys.js: PASS.
- Browser launch attempted: no Chromium binary installed. No browser, WebKit or physical phone acceptance is claimed in this increment. PR #267's historical browser results remain bound to its own source.

## Publication chain: concrete blockers

- Remote Desktop Commander reports the only exposed execution device EASON offline. There is no verified Command Center host installation channel in this session.
- #299 source fixes persistent CANARY/DEPLOY selecting different sources by using a common admission and signed TEST_PR. It remains uninstalled; repository code is not running code.
- Current main's docs/canonical-baseline/CURRENT_CANDIDATE.json still carries release_candidate_v1.source_commit bd25d7acca1b5f54a7fb555008ed60b76ee45f21 / PR52, not #298. It is not evidence that this candidate was admitted. This inspection does not establish which bytes the live Bridge currently reads.
- #298 records the most recent located live VERIFY from control-tasks #126, task go-boss-request-verify-20261001T120903Z-17d1570d252b, selecting old PR202 image sha256:3652b1d6392ee8eed816bfa484872bfc443a95abbd36bcbca887c96975915cdf. No newer live image verification was executed here.
- #298 expressly retains unresolved whole-scope retention, capacity, independent review and schema/image admission. This small frontend check does not override them.
- Changing flight source changes candidate identity: #298's prior TEST_PR/build evidence is historical for the parent, not this updated application.

## Exact continuation

Restore the existing controlled Command Center installation channel; read back current running Bridge bytes; review/install #299 while preserving live differences and ledger; verify installed hashes. Finish acceptance of the exact final business candidate, build through the existing TEST_PR channel and bind truthful source/tree/image/package/migration/rollback facts through existing candidate admission. Then CANARY -> fresh VERIFY -> DEPLOY -> post-deployment VERIFY. The phone acceptance must exercise 福州 -> 哈尔滨, absence of the search status panel, and one calendar selecting hotel arrival/departure before one confirmation.

No direct HK shell, formal task/signature creation, arbitrary candidate admission, fabricated release PASS, migration, real inventory/payment, merge, installation or deployment was performed.
