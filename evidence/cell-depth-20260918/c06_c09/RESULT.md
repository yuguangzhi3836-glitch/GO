# C06 / C09 local development candidate

Source commit: `b7b1dba35108e099849d8464f9c8d85a9c3e4fde`. Base: `42f3e62da844279cc3569c90eaa58d24a291a4d5`.

Classification: PRODUCT_FIX + TEST_ONLY + DOCUMENTATION. No model, migration, shared dependency, topology or authority change.

| GAP | TASK | TEST | EVIDENCE | Verdict / NEXT_TASK |
| --- | --- | --- | --- | --- |
| C06-CHANGE-STALE-QUOTE | Fence issuance with the order lock and supersede sibling quotes when a change starts. Rollback leaves untouched quotes available. | test_cell_depth_c06_change_quote_binding.py stale replay and rollback | before.xml, regression.xml, final-focused.xml | LOCAL PASS; integrate and independently review current candidate |
| C06-CHANGE-WINDOW | Apply the consumed supplier validity policy to target date/session before quote issuance and execution. | same file, nonexistent/ambiguous DST cases | before.xml, regression.xml | LOCAL PASS; real supplier identity, authority, raw response, provenance and E2E remain BLOCKED_EXTERNAL |
| C09-PUBLIC-BINDING | Public reads verify hotel, decision validity, standard and amount binding plus sealed evidence hash. Historical internal audit stays available. | judgment/test_cell_depth_c09_public_binding.py | before.xml, regression.xml, final-focused.xml | LOCAL PASS; exact-source C14 then independent C13 required |

Validation: 148 affected regression tests passed; 17 new focused tests passed after final review additions. The union is 150 distinct cases, zero skipped. Raw failed reproductions, the initial working-directory collection failure and a corrected standard-upgrade test-fixture failure are preserved. No failures were suppressed.

Standard upgrade inspection: the only runtime constructor for RecommendationDecisionRow is JudgmentService._reevaluate_in; it creates a fresh judgment ID and one new decision for each new evaluation. Unchanged evaluation reuses the existing pair. The explicit standard-upgrade test confirms both historical pairs remain readable and the current one stays public. ORM and migration 0013 both declare valid_from non-null and valid_to optional; expiration uses [valid_from, valid_to).

C06 engineering fixtures remain external_live=false. Synthetic supplier receipts, local SQLite and HTTP TestClient are not real provider or PostgreSQL evidence. Current publication falls back to NOT_YET_RATED in hotel search for an invalid binding; detail returns a review-required error without an endorsement. Original source/tests stay retained.

Remaining gates: integrate source, exact application tree/fingerprint rebind, independent C14, independent C13, required PostgreSQL concurrency, real attraction provider binding and authorized three-end acceptance. GitHub source upload remains blocked outside this task; no source was uploaded, no PR merged, no deployment performed. No global 100% claim.
