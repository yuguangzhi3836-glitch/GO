# C10/C11 follow-up — consumer source authority and supplier money projection

Input remains PR #246 candidate `6acf9fdcde4b208b12a8c9d57ef74497e745faae`, plus first-batch local fixes. No money execution or supplier connection outside isolated fixtures.

## Findings and fixes

1. Public consumer `/v1/payments/intents` directly called the generic internal creation service. Its non-order branch accepted caller business type/payee/amount/currency. A consumer could create an unbound RENTAL_DEPOSIT, RENTAL_CHANGE, SUBSCRIPTION_INVOICE or arbitrary obligation. New `create_consumer_intent` restricts that role-bound route to existing authoritative ORDER_TYPES. Existing order resolver supplies amount, currency, payee and source-decision identity; internal service creation remains unchanged.
2. C13 identified another C10 path: `order_supplier_fulfillment.record_supplier_fact` always projected PAID, even without a complete capture and after a refund. New `_payment_state` reads the existing Intent/Root/FactBinding identity and amount/currency, then confirmed movements and authorization/capture/release/refund bounds. Missing, mismatched or unresolved evidence projects UNKNOWN_EXTERNAL_STATE. Independently proved money can remain PAID while supplier fulfillment is unknown; partial/full refunds remain PARTIALLY_REFUNDED/REFUNDED. A full refund also projects refund completion. Root review added same-supplier replay refresh without repeating supplier events and a bound, unrefunded PAID requirement for new confirmation. C13's independently failing parent-chain probe led to same-root/type and per-parent balance checks; unknown movement types are rejected.

## Evidence

- `source-boundary-before.txt/xml`: original public path 4 failures / 3 passes, unwanted intent accepted with HTTP 200.
- `supplier-money-before.txt/xml`: initial attempt blocked at app setup because frontend materialization was incomplete, not a business verdict.
- `supplier-money-baseline.txt/xml`: exact original #246 supplier service loaded in an isolated test process, 8 failures / 1 pass. Replay script and exact original source retained alongside; shared source was never reverted.
- `second-fixed.txt/xml`: final 52 passed, 5 existing warnings. Includes 26 new boundary/financial projection cases plus existing supplier/rail and six-vertical agent checkout tests.
- An intermediate fixed run had one fixture error: missing source decision for the valid order creation case. Fixture now creates its isolated server-side decision, consistent with the production contract; no production guard was weakened.

## Files added or modified by second batch

- `application/src/go_hotel/services/omnichannel_payment.py`
- `application/src/go_hotel/api/routes/omnichannel_payment.py`
- `application/src/go_hotel/services/order_supplier_fulfillment.py`
- `application/tests/test_c11_consumer_payment_source_boundary.py`
- `application/tests/test_c10_supplier_money_projection.py`

## Boundary

Rental deposit creation/settlement remains HOLD for the missing durable source contract described in C04_DEPOSIT_SCOPE.md. No ORDER_TYPES expansion, deposit resolver, migration, deposit root or C04 money-status promotion was introduced. Tests are local SQLite and implementation-side; independent C13 and PG evidence remain separate.
