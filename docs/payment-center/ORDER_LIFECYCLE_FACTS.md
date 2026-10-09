# D01 — Current GO Hotel Order Lifecycle Facts

Status: READ_ONLY_DISCOVERY
Evidence baseline: `main@286e294d92df4b7d1c0073116a8e628734abec6c`
Scope: HOTEL P0 only unless explicitly noted

## 1. Verified facts

### 1.1 Native hotel state models

`application/src/go_hotel/domain/models.py` currently defines hotel order states:

- `PAYMENT_PENDING`
- `PAYMENT_AUTHORIZED`
- `BOOKING_PENDING`
- `CAPTURE_PENDING`
- `RECONCILIATION_REQUIRED`
- legacy compatibility states `PAID`, `CONFIRMATION_PENDING`, `CONFIRMED`
- after-sales states `CHANGE_PENDING`, `CANCEL_PENDING`, `CANCELLED`, `CONVERTED_TO_CREDIT`, `FAILED`

Payment states are `CREATED`, `AUTHORIZED`, `CAPTURED`, `VOIDED`, `REFUNDED`, `FAILED`.

A newly constructed native hotel `Order` defaults to `PAYMENT_PENDING`.

### 1.2 Offer / prebook timing is separate from order timing

The domain model gives:

- Offer default expiry: 15 minutes.
- Prebook default expiry: 10 minutes.
- Prebook default hold type: `SOFT`.
- Prebook default `inventory_held=False`.

The persisted `prebook` table has `expires_at`.

The persisted `hotel_order_runtime` table does not contain an `expires_at` or payment-deadline column in the initial schema, and current repository search did not identify a later migration adding such a column.

Therefore, current evidence supports a prebook expiry, but does not support a distinct native HOTEL order-payment expiry clock.

### 1.3 Order creation

`BookingService.create_order()` requires:

1. a known prebook;
2. prebook state `PREBOOKED`;
3. `BookingConsistencyGuard.assert_order_can_be_created()` to pass.

That guard rejects an expired prebook and rejects price/policy mismatch.

The order is persisted with version `1`; fare acceptance can also be snapshotted at order creation.

### 1.4 Original hotel payment is authorize → supplier book → capture

`BookingService.pay()` is explicitly authorize-only. It:

- requires exact order amount and currency;
- requires order state `PAYMENT_PENDING` (or idempotently returns an existing authorization for later states);
- rechecks prebook expiry before payment authorization;
- creates an idempotent external operation `PAYMENT_AUTHORIZE`;
- invokes the configured payment provider `authorize()`;
- persists a `PaymentRow` as `AUTHORIZED` and moves the order to `PAYMENT_AUTHORIZED`.

`BookingService.confirm()` then:

- requires an authorized payment;
- creates/claims an idempotent supplier-booking operation;
- invokes the hotel connector `book()`;
- on definitive supplier rejection, voids the authorization and makes the order `FAILED`;
- on supplier timeout/unknown result, does not void the authorization and moves the case to reconciliation;
- on supplier confirmation, stores supplier confirmation and moves the order to `CAPTURE_PENDING`;
- only then invokes payment capture.

Successful capture makes the `PaymentRow` `CAPTURED`, the order `CONFIRMED`, and the prebook `CONSUMED`.

### 1.5 Unknown external states have recovery paths

Current code contains explicit recovery paths for:

- payment authorization succeeded externally but local commit failed;
- supplier booking result unknown;
- supplier booking succeeded but local commit is uncertain;
- capture succeeded externally but local commit is uncertain.

This is not a simple synchronous `payment success = booking success` model.

### 1.6 Agent transaction API separates payment preparation and commit

For HOTEL, `GoTransactionCore.prepare_payment()` calls native `booking_service.pay()` and returns a `PaymentTruth` representing the authorization.

Later, `GoTransactionCore.commit()` checks that the supplied payment truth still matches the native hotel payment and calls `booking_service.confirm()`.

Therefore a real temporal gap can exist between authorization and supplier booking/capture. It must not be assumed to be one atomic HTTP request.

## 2. Verified conflict / race window

`BookingConsistencyGuard.assert_before_payment()` checks prebook expiry.

`BookingConsistencyGuard.assert_before_booking()` currently checks order/prebook amount and fare-rule consistency, but does **not** check:

- prebook expiry;
- current supplier inventory availability;
- whether a SOFT/unheld prebook still represents available inventory.

Therefore the following sequence is not currently disproved by the code:

1. prebook is still valid;
2. payment authorization succeeds;
3. time passes;
4. prebook expires or unheld inventory changes;
5. `confirm()` proceeds to supplier `book()` without a local prebook-expiry check.

A real supplier connector might still reject or protect this sequence, but no production hotel connector is currently registered in this repository baseline. This must remain an integration blocker/unknown, not be papered over by a guessed TTL.

## 3. Legacy / compatibility path

`SqlRepository.commit_payment_saga()` still contains an older captured-payment path that can move `PAYMENT_PENDING -> PAID`.

The current booking service's primary path is the newer authorization → supplier booking → capture flow. The coexistence of legacy states/methods must be treated as compatibility debt until usage is fully traced; it must not be mistaken for a second approved HOTEL payment lifecycle.

## 4. Unknown / missing evidence

- No verified HOTEL order-level automatic payment deadline was found.
- No verified scheduler/job was found that automatically expires `PAYMENT_PENDING` hotel orders after a fixed duration.
- No management-approved `30 minute` hotel order/payment TTL exists in current code evidence.
- No production hotel connector behavior has been verified for authorization-to-booking delay.
- Runtime/ECS/database contents were not inspected in this repository-only pass.

## 5. Risks requiring human/technical decision later

1. What owns the authoritative deadline between prebook, payment credential, authorization and supplier booking?
2. What must happen when a prebook expires after authorization but before supplier confirmation?
3. Is a hard supplier hold mandatory for a payable hotel order, or can SOFT/unheld inventory proceed to authorization?
4. Which legacy HOTEL states and methods remain supported versus transitional?

No answer is approved by this document.

## 6. Evidence paths

- `application/src/go_hotel/domain/models.py`
- `application/src/go_hotel/services/booking.py`
- `application/src/go_hotel/services/consistency.py`
- `application/src/go_hotel/repositories/sql.py`
- `application/src/go_hotel/agent_gateway/real_core.py`
- `application/alembic/versions/0001_sprint1d_runtime.py`

D01_RESULT=PARTIAL_FACTS_ESTABLISHED
D01_BLOCKER=HOTEL_PAYMENT_DEADLINE_AND_AUTH_TO_BOOK_EXPIRY_SEMANTICS_NOT_PROVEN
