# C13 independent successor CI review (pending)

Read-only review of Draft PR246; no source/PR/remote writes by reviewer. Status FAILED_BROWSER_AND_PG_INCREMENT; other current-head gates tracked separately.

## Identity independently retrieved

Gate head `a0f3ebc5073813167a67ee76b38bc270e6ec28ec`.
Product `73596d9958e685368484b7b2f811d601f1d95614` (from actual candidate JSON, not shorthand).
Application tree `eb4a5517f4661cd8ad12c0a9e6d8166c87e6869f`;1517 blobs; fingerprint `c9cb7535f46bbdd18ea8d0625ad6c915a1cc1e4862119fff50620b619e3c740a`.

Independent GitHub gate recursive tree is untruncated; product and gate application trees match. Retention/depth9/next-depth/Cell candidate manifests agree. Expected inherited+repair+override union1517 exactly equals actual1517 paths.309 override blobs and all untouched original inherited blobs match; inherited manifest blob remains8eda2e86ad5164c0e8203a068026ef195cb3f995. No historical PASS transfer. All53 declared application changes match the locally reviewed bytes by Git blob hashes (`REMOTE_CHANGED_BLOBS.json`).

## Runs

| Run | Scope | Current evidence |
|---|---|---|
|36116380960|Mobile|SUCCESS; independently downloaded original artifact|
|36116380976|Retention/full tests/frontend|SUCCESS; raw artifacts verified|
|36116380948|Cell scoped|SUCCESS; raw artifacts verified|
|36116380996|Browser/PG16|Browser FAIL; PG16 six tests PASS|
|36116380958|PG18|FAILED C11 increment; C07/C09 PASS; capacity NOT EXECUTED|

Mobile artifact10854468412 ZIP SHA256334a6e46652b2ddc47241d56e79c9c7cffd6d5bd5a6b4896b3f6d53c1e90843c independently matches GitHub digest. Original logs show tsc --noEmit, contract PASS, prebuild and native module linking. Pod install is explicitly skipped; this is not a compiled/running iOS-device test. Original1517 source fingerprints independently recompute the expected source digest and bind final head/product/tree. New mobile editable form code is included in the verified source tree.

Local independent precursor review: `LOCAL_ROUND2_REVIEW.md`, all R2-001..006 closed in their stated local scopes.105 targeted Python test invocations and mobile23 tests (same suite in two timezones), plus4 independent mobile boundary tests; previous root JS timezone probe4 assertions in each of two zones. No local SQLite result is relabelled PostgreSQL. Whole candidate acceptance awaits original exact-head artifacts below.

## Browser gate failed — retained, not waived

Run36116380996 browser job108011368484 FAILED. Original artifact10855492280 ZIP SHA256d1d7bdcfc8169db780c9b4b010df8659229d90102aa4b3bba84fdb63d40c5378 matches GitHub; all121 SHA256.json payload entries independently match. Original report has33 page checks,21 journeys,0 console errors,7 failed checks/scenarios and result GAPS_FOUND.

Independent root-cause confirmation: runtime records RIDE `/refund-confirmed` HTTP200 in36.91ms and RENTAL HTTP200 in37.63ms; visible consumer/supplier pages show actual completed refunds. Exact-head browser code listens only for `(refund|cancel)` in three places, so the successful mobility `/refund-confirmed` response is not matched/recorded. Missing refund outcome generates four downstream final-state/reentry failures. The deposit scenario was also sequenced after RENTAL's completed refund; consumer order is already REFUNDED, so product correctly hides new-proposal action. This is not a reason to weaken product order eligibility.

Read exact-head original `ci/journey-v2/browser.mjs` (preserved `browser_a0f3ebc_original.mjs`) and diff against root's proposed harness-only fix: three listeners include refund-confirmed; response wait additionally binds the same order ID; deposit scenario moves inside booked after confirmed capture and before original-rent refund. Consent/hash/amount/count/ledger/replay assertions are retained. No product source change needed for these diagnosed failures. This static fix review does not change a0f3ebc FAILED evidence into PASS; a successor exact gate must run all gates again. Scoring uplift remains withheld.

## Other exact-head gates independently inspected

- PG18 C07 artifact10854733487 SHA256b5dddd84e9f8969f463f7ce50ca81510606d88e735636d456a0b2ee535704605:6PASS, zero skips, actual18.4,79 bound payload hashes match.
- PG18 C09 artifact10855590095 SHA2567ecddadfe40a95d0a3ae921580eeaa0bbe2bd073f4d95181d8ab115f377f3d5e:12PASS, actual18.4,8 bound payload hashes match.
- PG16 artifact10855407455 SHA2567afc17db5b4e22f23222bb6ea6da292a63a0a2cb1d660cbc38010cfb93ab5c27:6PASS, zero errors/failures/skips, actual16.4 and migration0138.
- Frontend artifact10855072800 SHA25697def08f925179e4f65812123a12373d4461cac1aa117b3a102be6d0b772cfbd:346PASS zero skip, compatibility34PASS.
- Cell artifact10855298998 SHA256d33fab73f9fb2c946a3d85d3f0fe8b134e6d1af7252c24c2752a922deabf22d6:28 original XMLs455PASS zero fail/error/skip;35 bound payload hashes match head/tree.

Retention338-file inventory is disjoint and exhaustive across4 shards. Original JUnit totals3064tests=3057PASS+7PG-only skips,0fail/error. Skips are same5 PG race matrix,1PG root concurrency,1PG outbox row-lock cases as prior baseline; not relabelled as executed SQLite tests. Parent-package and archive-parent-objects jobs are skipped.

| Shard | Tests | Passed | Skipped | Artifact | ZIP SHA256 |
|---|---:|---:|---:|---|---|
|0|770|770|0|10854609611|38e917498f064f0f5c2c84cae7ee1f84d4aee13ab54a5469a3b4023ceaf2f539|
|1|772|767|5|10855776358|6bb059a81acb5c28c47124c56417268491850bae82aa35e01453ceb48eae09f2|
|2|795|794|1|10855379122|fddb3e09d7acf599ba0d3cd7a34bd4d3b88dd4419dc1e770b16427865a6559b3|
|3|727|726|1|10855433523|5270a3f822b5faa811899c3400367e63944dd4b31133b75cf7125165b634f9a0|

All ZIP digests above locally match GitHub artifact metadata. These successes do not override the browser gate failure.

## Real PostgreSQL blocker retained

C11 artifact10856140575 ZIP SHA25695c4eeed8b1ce8f57addb63c4bb65f8e6f01fa1e8254802abcc806d586a98d23 matches GitHub metadata;97 bound payload hashes independently match candidate head/tree. Existing process12, payments47 and outbox1 all PASS. New11-file increment has167tests=162PASS+5FAIL,zero skips. Capacity step was skipped after failure and supplies no executed evidence.

Actual PostgreSQL rejected73-character BUSINESS:RENTAL_DEPOSIT:<full obligation ID> in account_code VARCHAR(64). Failed cases are capture/remainder release at4000 and10000, rollback/retry, concurrent authorization/settlement and missing-capture-ledger recovery. Original XML/log are retained in failed-pg-increment.xml and failed-pg-increment.log. SQLite results did not detect this database constraint. This is a real product defect requiring a successor product/tree and fresh exact-head CI, independently of the browser harness defect. No candidate acceptance or scoring uplift is granted.
