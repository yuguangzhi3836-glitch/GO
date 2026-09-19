# Independent scoped code review — Ctrip depth round 1

Reviewed at: 2026-09-19T01:18:27.628170+00:00

Baseline: PR #217, commit `0cdff19160845b22f3aa9fa5e281413ddd460514`.
Reviewer: independent_code_review agent; no product or test files modified by reviewer.

## Candidate fingerprints

| File | SHA256 |
| --- | --- |
| application/src/go_hotel/services/aoluguya_supply_truth.py | `bc6dca001afb7e7a00c8fc890c15813dbaf2b85d3d1fbfda2c9698ace10121aa` |
| application/src/go_hotel/services/hotel_partner_core.py | `e2c717c8c676abec7dc81f979ead1d5a32773907bceec4046c20eb917437bb5d` |
| application/src/go_hotel/services/consumer_ota_comparison.py | `af9004f126c8bf13d3a818ec888ff43d77041a6f0018ef8050dcaa90e2b97a73` |
| application/src/go_hotel/services/consumer_unified_lifecycle.py | `74f3f4d0bc8760aefc2ec08ee4c69fe776dd27f0e5a04860075d89176e87e8ec` |

## Result

Two blocking findings were raised during initial review and independently reproduced against real in-memory SQLite persistence. Both have been fixed and the original reproduction scenarios now pass assertions. No unresolved blocking regression was identified in the reviewed four-file increment. This is a scoped code review, NOT formal C14/C13 acceptance, PostgreSQL acceptance, HTTP acceptance, deployment approval, or proof of 100% product depth.

## Findings and independent verification

1. **Variant state omitted from rollback (fixed).** Initial projection of one CLOSED plan and one OPEN plan followed by rollback produced Offer ACTIVE / Variant INACTIVE. The updated v2 backup captures variant states and rollback restores them. Independently rerun scenario asserted Offer ACTIVE, Variant ACTIVE and `variant_states_restored is True`. Output: `rollback reproduction: FIXED / ACTIVE ACTIVE`.
2. **Partial snapshot erased permanent plan identity (fixed).** Initial bindings o0→flex and o1→prepaid, followed by a flex-only snapshot, deleted the o1 binding. A later flex + brand-new-plan snapshot silently reused o1 via breakfast matching. Updated code retains bindings and marks absent offers/variants INACTIVE. Independently rerun scenario asserted the new plan raises UNMAPPED_OR_AMBIGUOUS, o1 remains bound to prepaid, its preexisting price 101 remains unchanged, and both states remain INACTIVE. A subsequent flex + prepaid snapshot correctly restored o1 to ACTIVE at price 1500. Output: `identity reproduction: FIXED / rejected new identity; retained old price; original resumes`.

Verification used `go-depth-venv/bin/python` with source and tests on PYTHONPATH, the existing RateIdentityTests fixture, real SQLAlchemy sessions and isolated in-memory SQLite databases. Assertions ran in an inline script, exit code 0. This reviewer did not rerun or claim ownership of the implementation team's full test suite.

The legacy rollback branch now explicitly reports PARTIALLY_ROLLED_BACK with LEGACY_BACKUP_VARIANT_STATE_UNAVAILABLE where historic backup lacks variant state. This branch was inspected in source; independent inline scenarios above specifically exercised v2 backup.

## Other reviewed increments

- Selected hotel import filters whole chosen fields before normalization, rights checks and writes. Unselected top-level hotel fields, rooms, media, and ownership metadata are preserved. Source attribution is merged per imported field. The feature selects contacts/address as whole objects, not individual nested values.
- OTA comparison requires exact integer occupancy values and a parseable future expiry before quote eligibility. Existing amount validation already rejects booleans/noninteger amounts. Missing or invalid expiry now suppresses quotes.
- External order import validates amount_minor as a nonnegative exact integer before opening its transaction, including repeat imports. Lifecycle/refund behavior outside this guard was not changed by this increment.

## Remaining scope and risks

- No PostgreSQL row-lock/concurrent-writer acceptance; no HTTP/schema, browser, production adapter, consumer/supplier/admin end-to-end or deployment verification.
- Room imports remain append-oriented across distinct imports; stable cross-import source room IDs and canonical 17-room reconciliation are not delivered by selected_fields.
- Composite hotel fields are replaced as whole objects when selected. Nested field selection is intentionally rejected; UI must communicate that boundary.
- Backup identity checks protect variant set changes, but broad concurrent cutover/booking and operational rollback safety remain unverified.
- No actual hotel media download/upload or GO data migration was performed by this review.
- These hashes bind this review to the local candidate. Any subsequent product change needs review delta assessment.
