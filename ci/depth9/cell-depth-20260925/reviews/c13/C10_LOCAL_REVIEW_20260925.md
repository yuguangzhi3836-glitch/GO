# C13 local C10 review

Independent review of supplier immutability and unknown-external projection increment; not formal candidate acceptance.

Read `consumer_unified_lifecycle.py`, `vertical_lifecycle_projection.py`, two new tests and the supplier-fulfillment call boundary. Independently executed:

`GO_TEST_DB_PATH=/tmp/go_c13_c10_review.db PYTHONPATH=src:. ../../go-venv/bin/python -m pytest -q tests/test_c10_lifecycle_supplier_identity.py tests/test_c10_unknown_payment_projection.py tests/test_depth20_api_fulfillment.py --junitxml=/workspace/scratch/cdb63add4518/reviews/c13/c10-junit.xml`

Result: **37 passed**. This is SQLite isolated execution, not PostgreSQL or full end-to-end authentication evidence. Supplier immutable comparison occurs before stale/idempotent shortcuts, including None-to-known; unknown external native state is no longer inferred PAID by `vertical_lifecycle_projection`.

## Cross-boundary finding C13-LOCAL-002

`order_supplier_fulfillment.record_supplier_fact` calls the lifecycle projector directly and sets `payment_state='PAID'` for all SUPPLIER_CONFIRMED, UNKNOWN_EXTERNAL_STATE and SUPPLIER_FAILED paths. Only SUPPLIER_CONFIRMED branch checks captured money. Therefore the single-function projection change does not establish that all status-projection paths derive PAID from actual confirmed money.

Finding reported to C07–C11 implementation group and root. Implementation group confirmed the separate path and is preparing source-bound money derivation. Review must cover missing/foreign root and intent, currency, confirmed capture and refund state. A supplier outcome may be unknown while a proven payment is paid; such cases must keep these axes separate. An unknown supplier result alone must not erase or manufacture actual payment truth.

No code was changed by the reviewer. First two-file increment has no additional blocker found within tested scope; C13-LOCAL-002 remains pending successor implementation and review. No module completeness or release approval is implied.

## Successor finding C13-LOCAL-004 — summed money amounts without parent binding

The first implementation of `_payment_state` validated root/intent/binding fields and aggregate amounts, but did not validate `parent_movement_id`. Independently executed `probe_c10_money_parent.py`: after a valid isolated captured rail order, change its capture parent to `not-an-authorization`, then record supplier UNKNOWN. Actual projection remained PAID; expected UNKNOWN_EXTERNAL_STATE. The original negative JUnit is `c10-parent-probe-junit.xml` (1 failed). The implementation team is adding parent-kind/root binding and per-parent limits, alongside root's same-state replay refresh finding. Both need successor review before closure.

## Final local successor review — findings closed within this scope

Read final frozen `order_supplier_fulfillment.py` and consumer intent route/service plus tests. Independently executed `test_c10_supplier_money_projection.py` (17), `test_c11_consumer_payment_source_boundary.py` (9), and the unchanged `probe_c10_money_parent.py` (1) using a dedicated SQLite path and `-p no:cacheprovider --noconftest -p conftest`. Result: **27 tests, 0 failures, 0 errors, 0 skips**, exit 0. Final JUnit `c10-c11-final-junit.xml`, SHA256 `11776b7d49dca5e2cf20b7d05fef7807bfbb099a2c16f69c0d5c0ab94b37a61c`.

Verified fixes:

- Supplier outcome no longer manufactures PAID; missing/wrong capture, wrong binding/currency, orphan/foreign parent and unknown movement kind produce UNKNOWN_EXTERNAL_STATE.
- Properly confirmed same-root parent edges and per-parent authorization/refund limits are required. The original orphan-parent probe now passes unchanged.
- Supplier UNKNOWN preserves independently proven PAID/PARTIALLY_REFUNDED/REFUNDED, separating money from fulfillment truth.
- Same-state supplier replay refreshes stale money projection after capture loss or refund without rewriting supplier timestamp or adding supplier events.
- New supplier confirmation refuses mismatched or refunded money graph.
- Consumer intent creation permits authoritative ORDER_TYPES only. Caller payee/amount/currency/operation/source-decision cannot replace source facts; foreign payer is rejected; internal subscription creation remains available.

C13-LOCAL-002 and C13-LOCAL-004 are closed for these local bytes, including root's identified same-state replay gap. No additional blocker found in this bounded review. No broad payment completeness, real PSP readiness, PostgreSQL concurrency or final candidate C13 PASS is asserted.

All five source/test digests were independently checked against `reviews/c07-c11/SECOND_SHA256SUMS.txt` after execution:

| File | SHA256 |
|---|---|
| services/omnichannel_payment.py | ecba8b7d56e00dcc79b5517d9b3d689c3215cf8d122a00c4ebb72c8627e8a782 |
| api/routes/omnichannel_payment.py | ade243f3fe72d1234af71b0990adb944d83cea9bd5a3c6fb4246fa33d0a68c8c |
| services/order_supplier_fulfillment.py | a6fd71e62fa765724996be08ef2cbe96509127e8913b0c38974b029ee80d8a1a |
| tests/test_c11_consumer_payment_source_boundary.py | 5796f1a6d2ee30ab886f5a23076171804ab4f009206e1be50e915c6995dc2737 |
| tests/test_c10_supplier_money_projection.py | 8404cc7358d2a88ae31e72a386967439853ae6bfee716120237d3190f047a16c |
