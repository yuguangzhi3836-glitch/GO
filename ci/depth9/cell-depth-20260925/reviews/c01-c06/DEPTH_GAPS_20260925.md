# C01/C02/C03/C05/C06 depth increment and coverage review

Date: 2026-09-25. Source candidate: PR #246, `6acf9fdcde4b208b12a8c9d57ef74497e745faae`. Local development only; no merge, deployment, Hong Kong action, supplier request or real payment. C04 is owned by the separate rental workstream. This is developer evidence, not C13 independent PASS.

## Completed increment: C05 fixed-fare currency integrity

Confirmed source defect: `application/src/go_hotel/mobility/ride/service.py` used fixed engineering fares 16800/26800 in both search and create, while accepting arbitrary caller currency. A USD/JPY request relabelled a CNY amount without a new supplier quote or conversion. Rail and attraction already restrict these engineering prices to CNY.

Fix: reject non-CNY currency in both entry points before order creation, reservation expiry or source decision. Missing currency retains the CNY default. No historical rows, shared schema, ledger or payment root were changed.

Baseline reproduction: loaded the exact original service source from the frozen candidate separately and called `search(..., "USD")`; assertion confirmed `(16800, "USD")`. Output: `BASELINE_REPRODUCED: fixed 16800 engineering fare returned as USD`. No database or network provider call was needed to demonstrate the defect.

Added `application/tests/test_c05_engineering_currency.py`: 12 cases cover USD/JPY, lowercase/whitespace/empty/null rejection, absence of orders/source dispatch on rejection, both fares with explicit/default CNY, persisted currency, and HTTP 422 on incompatible search currency.

Validation: **23 passed in 7.60s** with frozen dependencies, isolated SQLite, combining the 12 new tests, existing mobility refund-consent tests and concurrent UNKNOWN episode tests. JUnit: `c05-currency-junit.xml`. This run contains no skipped cases and is not PostgreSQL or browser/device evidence.

Command (from `go/application`):

```sh
PYTHONPATH=src:tests /workspace/scratch/cdb63add4518/go-venv/bin/python -m pytest tests/test_c05_engineering_currency.py tests/test_depth33_mobility_refund_consent.py tests/test_v70_r5_c05_concurrent_unknown.py --junitxml=/workspace/scratch/cdb63add4518/reviews/c01-c06/c05-currency-junit.xml
```

## Per-cell gaps and bounded next actions

These entries distinguish confirmed source findings from unproven completeness. Accepted historical tests are retained; none is restarted merely because organizational roles were clarified. C13's separate matrix identifies historical accepted scopes; they do not automatically certify the new candidate.

| Cell | Current evidence / inspected boundary | Gap classification | Next acceptance obligation |
|---|---|---|---|
| C01 Hotel | C13 located `test_v70_r4_c01_unknown_episode.py` and `test_v70_next_c01_authorization_replay.py`; their accepted scope includes episode fencing and lawful-fare-change replay. This agent did not modify or rerun hotel code. | Coverage reconciliation, not a newly established defect | Bind remaining tenant/media revoke/import races and original payment → adjustments → refunds conservation to the final candidate. Reuse unchanged accepted evidence; run affected integration scope only. |
| C02 Flight | Unified candidate retains #240 flight recovery work; inspected `flight/changes.py` includes immutable plan integrity and change-consent guards. C13 reports fixed-head PG recovery CI. | Final integrated evidence reconciliation | Confirm exact final-source retention of partial-party, multi-segment changes and hard-exit/lease recovery evidence; do not recreate flight/payment truth. |
| C03 Rail | Inspected `rail/service.py`: locked reservation/prepare states, money adjustment key by quote, refund fee retention; `rail_change_resolution.py` binds supplier resolution to quote. | **Confirmed and fixed**: a second precomputed quote remained usable after a first change altered its fare basis. Baseline test failed; peer quotes are now atomically SUPERSEDED when a change starts, and quote creation locks the order. | Two-quote sequential-change regression now passes. Existing money-resolution and capacity race tests retained and rerun. Obtain real-PG evidence for the added locking scenario before making a PG concurrency claim. |
| C05 Ride | Currency defect fixed and 23 relevant tests pass. Inspected `ride/service.py` search and `ride/refunds.py:terms`. | **Confirmed source contract discrepancy**: search advertises free cancellation until 24h / late fee 8400 or 13400, whereas refund quote always uses fee 0. Not silently changed because existing-order policy applicability is unresolved. | Freeze the accepted cancellation contract at booking and map authoritative pickup-time/clock boundaries to refund consent; first establish whether displayed late fees or the current full-refund behavior is the intended engineering contract. Test before/at/after cutoff, order modifications and original accepted policy retention. No new refund authority. |
| C06 Attractions | Inspected `attractions/service.py` and `validity.py`: consumed prebook integrity, frozen session/timezone windows, reservation transition and supplier confirmation; C13 located internal-policy and raw-payload binding tests. | **Confirmed and fixed**: delayed first-change confirmation mutated the second change using an old voucher; repeated pending submission failed instead of replaying. Both original failures were reproduced. | Current quote identity is required for every pending change; explicit stale/foreign quote is refused. Ordinary non-change recovery remains compatible. Pending same-quote submission replays without new evidence. API, correct second-episode resolution, stale closure/confirmation and existing capacity/DST/validity suites pass. |

## Remaining boundary

No claim of five-cell 100% completion is made. Browser/mobile journeys, true PostgreSQL concurrency and fixed-candidate independent acceptance must be mapped to actual evidence. Real supplier/PSP certification remains outside this internal-development increment; unknown or missing evidence is not PASS. Persistent operations ownership remains with the corresponding C01–C14 team.


## Second increment: C03/C06 quote and episode fencing

Baseline `test_c03_c06_change_quote_fencing.py` produced **3 failures** before changes, preserved in `change-fencing-before.xml`: stale rail fare quote accepted, stale attraction confirmation accepted, and same attraction submission rejected. These are reproduced failures, superseding the initial candidate-only observations above.

Changes:
- `application/src/go_hotel/rail/service.py`: same order lock for quote creation and execution; peer QUOTED offers become SUPERSEDED before initiating the selected change. Existing order-before-quote lock order preserved.
- `application/src/go_hotel/attractions/service.py`: same pending quote is safely replayed; supplier resolution may carry quote_id; old/mismatched quote fails closed. For every pending change, omitted quote_id is rejected rather than bound to the latest change (tightened after C13 identified a prechange ordinary-recovery replay).
- `application/src/go_hotel/api/routes/attractions.py`: carry quote_id through validation, idempotency identity and service call; identity refusal maps to HTTP 409.
- `application/tests/test_c03_c06_change_quote_fencing.py`: six cases including API identity forwarding, bound replay and successful second-episode resolution.

First regression run: **91 passed** (`change-fencing-after.xml`), comprising original 3 new tests, `test_depth22_rail_resolution.py` and `test_next_depth_c06_supplier_validity.py`.
Second run: **39 passed** (`change-fencing-integration.xml`), comprising all 6 new tests, `test_depth23_capacity.py`, `test_next_depth_c03_payment_inventory_races.py`, `test_sprint3b_rail.py` and `test_sprint3d_attractions.py`.
Counts overlap and must not be summed as unique coverage. Both runs use isolated SQLite, no skips. Existing Alembic configuration emitted five deprecation warnings per run.

C06 caller contract (final revision): every change resolution must echo the quote_id returned by change-quote / change submission evidence; unbound change callbacks intentionally stop with HTTP 409. Ordinary UNKNOWN recovery without a pending change retains behavior. Four existing change-confirmation callsites in three tests were updated to supply their actual quote identity; assertions were preserved. Source route was updated; no direct frontend caller was located by repository search, and frontend source was not present locally during this review. Root was notified to complete exact-candidate frontend callsite inspection.

C05 policy provenance trace: `ride/flight_sync.py:engineering_policy/snapshot_policy` freezes wait/delay terms, not cancellation terms. `ride/refunds.py:terms` produces zero-fee quotes, and `services/mobility_refund_consent.py:freeze` records them only when refund is requested. Read operating decisions/state do not establish an approved zero-fee ride cancellation policy. Therefore neither search fee terms nor historical refund amounts were rewritten on an assumption.


## C13 first-change blocking finding and final correction

C13 independently reproduced an additional ambiguity: ordinary UNKNOWN recovery could precede the first change; replay of that old unbound recovery confirmation could incorrectly resolve the first change. The initial first-change compatibility allowance was therefore removed, not waived. Every pending change now requires explicit quote_id. The new persisted regression also verifies correctly bound first confirmation succeeds.

Additional changed test files (callsite adaptation only): `test_depth23_capacity.py`, `test_next_depth_c06_supplier_validity.py`, `test_sprint3d_attractions.py`.

Expanded final-code regression: **106 passed** covering seven fencing tests, capacity, supplier validity/DST, attraction HTTP golden path, and ordinary cross-domain UNKNOWN/closure recovery. The same invocation also included C13's probe by its external path; that one case failed before reaching business logic because the external path did not inherit application/tests/conftest.py (missing table). Raw evidence retained as `c06-strict-quote-regression.xml`; do not label this entire invocation PASS. The unchanged independent probe was rerun separately with the test conftest explicitly loaded; result is recorded in `c06-independent-probe-fixed.xml`.
