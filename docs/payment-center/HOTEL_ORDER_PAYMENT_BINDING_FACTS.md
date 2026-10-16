# D04 — Hotel Order / Payment Binding Facts

Status: READ_ONLY_DISCOVERY
Evidence baseline: `main@286e294d92df4b7d1c0073116a8e628734abec6c`
Scope: HOTEL P0

## 1. Verified native HOTEL binding

### 1.1 Stable identifiers

Current native hotel chain uses:

- `offer_id`
- `prebook_id`
- `order_id`
- `payment_id`
- external-operation IDs for authorize / supplier book / capture / void
- `supplier_confirmation_no`

`hotel_order_runtime.prebook_id` binds order to prebook.

`payment_runtime.order_id` binds native payment to hotel order.

For original booking payment, code uses `payment_type='ORIGINAL_BOOKING'`.

### 1.2 Amount and currency binding

`BookingService.pay()` rejects payment unless requested amount and currency exactly equal native order amount/currency.

Before authorization, `BookingConsistencyGuard.assert_before_payment()` also verifies:

- order amount equals prebook amount;
- order currency equals prebook currency;
- prebook has not expired.

This is a verified anti-stale / anti-cross-amount control in the current native path.

### 1.3 Duplicate authorization protection

Native HOTEL payment uses two layers of protection:

1. existing authorized payment lookup for an order;
2. idempotent external operation `PAYMENT_AUTHORIZE` keyed to the aggregate/request payload.

If the same completed operation is replayed, the existing payment can be returned. A different payload against the same operation/business contract is rejected as a conflict.

The mock payment provider also treats the operation ID as its idempotency key.

### 1.4 Supplier booking and capture binding

Supplier confirmation is started only after an authorized `PaymentRow` exists.

The confirmation saga hashes `order_id + payment_id` and uses an idempotent supplier-booking operation.

Successful supplier booking stores the supplier confirmation on the same hotel order and moves the order to `CAPTURE_PENDING`.

Capture then updates the same native `PaymentRow` from AUTHORIZED to CAPTURED and moves the same order to CONFIRMED.

Therefore the inspected native path has an explicit order-payment-supplier chain rather than simply trusting a client-provided payment status.

## 2. Agent Gateway binding

Agent references are namespaced as `HOTEL:<native_order_id>`.

For HOTEL:

- `reserve()` creates native prebook + native order;
- `prepare_payment()` checks expected order total/currency and calls native authorize;
- returned `PaymentTruth.payment_truth_id` is the native `payment_id`;
- `commit()` re-reads native payment state and requires the supplied `payment_truth_id` to match that native payment ID;
- only then does it call native hotel confirmation/capture orchestration.

This blocks a PaymentTruth from a different native payment/order being casually reused through the Agent contract.

## 3. Omnichannel order/payment fact binding

The newer omnichannel layer provides a stronger explicit binding object:

`PaymentOrderFactBindingRow` binds a payment intent to:

- business type;
- business ID;
- payer ID;
- payee ID;
- amount;
- currency;
- legal entity;
- source-decision ID;
- request fingerprint;
- order-fact hash;
- evidence reference.

`PaymentOrderRootRow` associates one payment intent with one business object. `OmnichannelPaymentService.create_intent()` locks and resolves the server-side order fact rather than trusting client-supplied amount/payee data.

For existing roots it rejects creation of another order payment root.

This is currently a strong local binding model, but for original HOTEL booking it is populated after native capture by `hotel_money_bridge`, not used as the primary live HOTEL executor.

## 4. Merchant / sub-merchant binding status

### VERIFIED

Native HOTEL `OrderRow` carries `supplier_id`.

The omnichannel fact binding derives `payee_id` from a vertical source decision / hotel supplier context.

The omnichannel service also defines `OmnichannelMerchantBindingRow` and requires credential references to be external secret references.

### NOT VERIFIED FOR HOTEL P0 LIVE PAYMENT

The native `PaymentRow` itself does not prove a PSP merchant/sub-merchant account binding. The inspected native provider is a mock and receives order ID, amount, currency and payment token; it does not prove that a real PSP charge is made directly under the hotel's approved sub-merchant identity.

Therefore the management requirement "hotel is the room-charge merchant / collection主体" remains a **live integration gate**, not a fact established by the current simulator.

## 5. Retry and channel-switch behavior

### Native HOTEL path

The current native HOTEL path has no verified real payment-channel state machine. `payment_method_token` is passed to the mock provider.

The code supports retry after a declined authorization because a failed payment does not promote the order to `PAYMENT_AUTHORIZED`, but real PSP retry/channel-switch semantics are not established by this mock behavior.

### Omnichannel path

The omnichannel service has explicit selected channel / payment attempt semantics:

- active/unknown attempt blocks resend;
- timeout maps to `UNKNOWN_EXTERNAL_STATE`;
- channel fallback is blocked while state is unknown;
- fallback after a definitive failure requires another allowed channel and user consent.

Those are implemented local contract semantics, but the actual behavior against WeChat/Alipay/card PSPs remains D05/Sandbox work.

## 6. Unknown / late-success behavior

### Native HOTEL authorization

If payment authorization succeeds externally but local commit fails, current code records reconciliation-required state and has `recover_authorization()`.

### Supplier booking

If supplier booking times out or result is unknown, current code explicitly does **not** void the authorization because the supplier might have booked. It marks reconciliation required and later checks supplier status.

### Capture

If capture succeeds externally but local commit fails, current code can query provider status and recover the local capture commit.

These are good failure-shape controls.

However the provider is a mock, so real callback-loss / query-lag / late-success semantics are not established.

## 7. Verified expiry gap affecting binding safety

The native flow verifies prebook expiry before authorization, but does not verify prebook expiry again immediately before supplier booking.

Because Agent `prepare_payment()` and `commit()` are separate operations, a payment authorization may remain bound to an order after the associated prebook has expired.

Current code does not prove what a real supplier does in that interval.

This must be resolved together with D02 inventory authority and D05 PSP behavior. It cannot be solved by inventing a payment TTL in Payment Center alone.

## 8. Refund binding

Native `RefundRow` binds:

- refund ID;
- order ID;
- payment ID;
- amount/currency/status.

The current cash-fare after-sales path also creates an omnichannel REFUND money movement against a confirmed CAPTURE parent and then writes a native `RefundRow` for an original HOTEL payment.

`UnifiedMoneyMovementService` prevents aggregate confirmed refund/compensation from exceeding captured money in its graph.

Because both native refund receipt and omnichannel refund movement exist, future Payment Center must formally declare which is the financial source of truth and which is compatibility/projection data.

## 9. Current end-to-end HOTEL fact chain

Current inspected primary path is:

`Offer -> Prebook -> Hotel Order(PAYMENT_PENDING) -> PaymentRow(AUTHORIZED) -> Supplier Booking -> Hotel Order(CAPTURE_PENDING) -> PaymentRow(CAPTURED) -> Hotel Order(CONFIRMED) -> hotel_money_bridge -> Omnichannel Payment Root / Money Movements / Ledger`

This chain is current implementation evidence, not a recommended final architecture.

## 10. Blockers

D04_BLOCKER_01=REAL_HOTEL_SUBMERCHANT_BINDING_NOT_PROVEN
D04_BLOCKER_02=AUTHORIZATION_TO_SUPPLIER_BOOK_EXPIRY_RULE_NOT_PROVEN
D04_BLOCKER_03=REAL_PSP_UNKNOWN_LATE_SUCCESS_CHANNEL_SWITCH_NOT_PROVEN
D04_BLOCKER_04=NATIVE_VS_OMNICHANNEL_REFUND_AUTHORITY_NOT_FORMALLY_ASSIGNED

## 11. Evidence paths

- `application/src/go_hotel/services/booking.py`
- `application/src/go_hotel/services/consistency.py`
- `application/src/go_hotel/repositories/sql.py`
- `application/src/go_hotel/payments/mock.py`
- `application/src/go_hotel/agent_gateway/real_core.py`
- `application/src/go_hotel/services/omnichannel_payment.py`
- `application/src/go_hotel/services/unified_money_movement.py`
- `application/src/go_hotel/services/hotel_money_bridge.py`
- `application/src/go_hotel/services/catalog_cash_fare_execution.py`

D04_RESULT=CORE_BINDINGS_ESTABLISHED_WITH_LIVE_INTEGRATION_GAPS
