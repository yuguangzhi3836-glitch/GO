# C02 — V70-R2-C02-02

Source anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; inherited candidate PR73 `a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b`.

Pure partial-passenger/coupon plan with explicit nonuniform original fare allocations, exact selected leg/passenger/ticket identity, owner/order/PNR/hash/expiry checks and receipt-indexed result preview; unselected coupons remain identical.

Builder finite scope: **25/25 new cases PASS**; 25/25 selected cases PASS in the final run. Six-stage completion: 4/6; C14 and C13 remain pending. Full-domain percentage is unknown.

Limitations:

- Not integrated with HTTP, persistent plan storage, consent capture, payments, ticket supplier, or order execution. Existing HTTP partial-passenger requests still reject422.

- plan_hash is a content checksum, not source authentication or execution authority; integration must bind a trusted stored hash and semantic validation.

- This finite planner rejects negative fare differences and same-day adjacent itinerary dates; it does not claim complete airline fare rules or full partial-party reissue.

Next proposed task (not executed): V70-R2-C02-03: specify trusted persisted coupon-plan and exact-consent integration with C11, including same-day segments and negative fare-difference treatment before enabling HTTP.

Final raw run: `plan-bound.raw.log`, `plan-bound.junit.xml`; commands in `RUNS.json`; current source hashes in `SOURCE_IDENTITY.json`; actual task times in `EXECUTION.json`.

No dependency, model, migration, permission, deployment or remote Git operation. Existing passes are inherited with their original scope. Earlier builder runs preceded final source pinning; C13 must validate the final fixed candidate independently.
