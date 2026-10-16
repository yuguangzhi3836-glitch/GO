# D03 — Current Payment Authority Map

Status: READ_ONLY_DISCOVERY
Evidence baseline: `main@286e294d92df4b7d1c0073116a8e628734abec6c`
Scope: HOTEL P0 first; cross-vertical payment primitives included where they affect authority

## 1. Executive finding

Current GO main does **not** have one cleanly isolated Payment Center authority.

Instead, HOTEL currently has a native booking-payment path based on `PaymentRow` / `payment_runtime`, while a newer omnichannel money graph based on `OmnichannelPaymentIntentRow`, `PaymentOrderRootRow`, `PaymentOrderFactBindingRow`, `OmnichannelMoneyMovementRow` and ledger/reconciliation models also exists.

`hotel_money_bridge` imports a completed native HOTEL payment into the omnichannel graph after capture.

Therefore the repository already contains two layers of payment truth representation. Adding a third Payment Center truth without a formal authority/migration decision is prohibited by this discovery.

## 2. Authority inventory

| Object / service | Current role proven by code | Current authority classification | External-live status |
|---|---|---|---|
| `PaymentRow` / `payment_runtime` | Native HOTEL original authorization/capture/void fact keyed to hotel order | CURRENT NATIVE HOTEL PAYMENT FACT | Mock provider only in inspected path |
| `Payment` domain object | In-memory projection of `PaymentRow` | PROJECTION | N/A |
| `PaymentTruth` in Agent Gateway | Protocol result. For HOTEL it points to native `PaymentRow` authorization; for non-HOTEL it requires fully captured omnichannel truth | ADAPTER / PROJECTION | Depends on underlying path |
| `OmnichannelPaymentIntentRow` | Cross-vertical payment orchestration intent, channel selection, retry/unknown-state guard | PAYMENT ORCHESTRATION FACT | External executor not configured in inspected service |
| `OmnichannelPaymentAttemptRow` | Per-attempt/channel execution state | ATTEMPT FACT | Simulator path proven; live not proven |
| `PaymentOrderRootRow` | One root payment intent bound to one business object | ROOT BINDING FACT | Local persistence |
| `PaymentOrderFactBindingRow` | Binds payer/payee/amount/currency/source decision/order fingerprint to intent | ORDER↔PAYMENT FACT BINDING | Local persistence |
| `OmnichannelMoneyMovementRow` | Authorization/capture/refund/release/etc money graph with parent-child budgets | MONEY GRAPH FACT | Simulator / certified external-fact modes; live executor not proven |
| `OmnichannelLedgerEntryRow` | Double-sided ledger entries posted from confirmed money movements | ACCOUNTING RECORD / PROJECTION FROM MONEY GRAPH | Local persistence |
| `OmnichannelReconciliationRow` and PSP/bank lines | Reconciliation evidence / state | RECONCILIATION FACT | External real feed not proven here |
| `RefundRow` / `refund_runtime` | Legacy/native hotel refund receipt keyed to order and native payment | NATIVE HOTEL REFUND RECEIPT | Real PSP execution not proven |
| `hotel_money_bridge` | Imports a captured native HOTEL `PaymentRow` into omnichannel root/movements; also provides isolated refund/adjustment bridging | TRANSITIONAL ADAPTER | Explicit simulator/isolated behavior in inspected path |
| `unified_money_movement_service` | Enforces movement budgets, evidence, ledger posting, scoped close | MONEY GRAPH CORE | Not equivalent to live PSP execution |
| `MockPaymentProvider` | Native HOTEL authorize/capture/void/refund simulator | TEST/SIMULATOR | NOT LIVE |
| `VerticalPaymentDeadlineRow` | Payment deadline state for RAIL/ATTRACTION/RIDE/RENTAL only | NON-HOTEL DEADLINE FACT | HOTEL excluded by schema constraint |

## 3. Native HOTEL payment authority

`BookingService.pay()` uses `go_hotel.payments.mock.payment_provider` and creates/persists an original `PaymentRow` after authorization.

The native HOTEL lifecycle then uses that row to gate supplier booking and later capture:

`HOTEL Order -> PaymentRow AUTHORIZED -> supplier book -> PaymentRow CAPTURED -> Order CONFIRMED`

The native `PaymentRow` therefore currently has operational authority inside HOTEL booking code.

However, the inspected provider is `MockPaymentProvider`; repository evidence does not establish a real PSP-backed native HOTEL payment authority.

## 4. Omnichannel payment authority

`OmnichannelPaymentService.create_intent()`:

- locks/resolves the authoritative business order;
- verifies payer ownership;
- resolves a vertical source decision;
- snapshots payer/payee/amount/currency/order/source facts;
- enforces one root payment for a business order;
- creates `PaymentOrderRootRow` and `PaymentOrderFactBindingRow`.

The service also has channel and payment-attempt state, including `UNKNOWN_EXTERNAL_STATE` and fallback protection.

But `execute()` currently rejects any mode other than `CONTRACT_SIMULATOR` with `EXTERNAL_PAYMENT_EXECUTOR_NOT_CONFIGURED`.

`checkout_readiness()` similarly reports blockers unless a certified merchant binding exists and explicitly reports `external_live=False`.

Thus the omnichannel layer is structurally much closer to a Payment Center core, but current repository evidence does **not** establish live PSP execution.

## 5. Money movement and ledger authority

`UnifiedMoneyMovementService` supports:

- AUTHORIZATION;
- CAPTURE;
- REFUND;
- COMPENSATION;
- PAYOUT;
- RELEASE.

It enforces idempotency and cumulative amount budgets, including:

- capture cannot exceed authorization;
- capture + release cannot exceed authorization;
- refund/compensation cannot exceed captured value;
- payout cannot exceed net captured value;
- child movements must reference a compatible confirmed parent.

Confirmed capture/refund/etc movements create double-sided ledger entries.

However a movement may be confirmed by `CONTRACT_SIMULATOR`, so `CONFIRMED` in this graph does not by itself prove a real external PSP money event unless evidence mode/authority is separately established.

## 6. HOTEL bridge proves current dual-layer model

`HotelMoneyBridge.ensure_original_root()` requires exactly one native HOTEL `PaymentRow` with:

- `payment_type='ORIGINAL_BOOKING'`;
- `status='CAPTURED'`.

It then creates/reconciles an omnichannel payment intent/root/fact binding and creates AUTHORIZATION and CAPTURE money movements.

In the inspected path those bridge movements use `CONTRACT_SIMULATOR` and evidence references such as `isolated-legacy-payment://...`.

Therefore the omnichannel HOTEL money graph is currently derived from/imported from the native captured HOTEL payment rather than being the original executor of that payment.

This is a major architectural fact for Payment Center migration.

## 7. PaymentTruth is not one uniform money truth today

Agent Gateway exposes a common `PaymentTruth`, but its semantics differ by vertical:

- HOTEL: `prepare_payment()` returns the native `PaymentRow.payment_id` after authorization, with `truth_type=HOTEL_AUTHORIZATION`; captured flag is normally false at this step.
- Other inspected vertical paths: Agent Gateway looks for an omnichannel intent and requires `state=SUCCEEDED` plus full confirmed capture before returning `PaymentTruth`.

Therefore `PaymentTruth` is currently a protocol abstraction over heterogeneous native money semantics, not proof of one centralized Payment Center authority.

## 8. Refund authority is also split

Native hotel after-sales can persist `RefundRow` linked to the original native `PaymentRow`.

At the same time, current after-sales flows also create `OmnichannelMoneyMovementRow` REFUND movements against the omnichannel root/capture graph.

The current code attempts to keep these linked, but this is another reason a future Payment Center must explicitly select one financial authority and define projections/compatibility records.

## 9. Current authority conflict

### VERIFIED

- Native HOTEL booking treats `PaymentRow` as the payment fact used for authorization/capture and booking transitions.
- Omnichannel layer maintains a richer intent/attempt/money/ledger model.
- HOTEL bridge imports native captured payment into that graph.
- Real HOTEL PSP execution is not present in the inspected native path; it uses `MockPaymentProvider`.
- Omnichannel live external executor is explicitly not configured in the inspected service.

### CONFLICT / TRANSITIONAL DEBT

A captured HOTEL transaction can be represented as both:

1. native `PaymentRow(status=CAPTURED)`; and
2. omnichannel `PaymentIntent + AUTHORIZATION/CAPTURE movements + ledger`.

The code contains reconciliation checks, but ownership is not yet formally declared for future real-money use.

## 10. Candidate future ownership — NOT A DECISION

The following is only a migration candidate for later formal review:

- Business/booking side retains hotel order, fare, supplier confirmation and inventory facts.
- Payment Center owns live PSP intent/attempt/external transaction/money movement/refund/ledger/reconciliation facts.
- Native HOTEL `PaymentRow` becomes either a compatibility projection or is retired after migration.
- `PaymentTruth` remains a read contract emitted from the authoritative Payment Center fact, not an independent store.
- `hotel_money_bridge` becomes a migration/compatibility adapter, not a permanent second financial authority.

No part of this candidate is approved by D03.

## 11. Evidence paths

- `application/src/go_hotel/services/booking.py`
- `application/src/go_hotel/payments/mock.py`
- `application/src/go_hotel/services/omnichannel_payment.py`
- `application/src/go_hotel/services/unified_money_movement.py`
- `application/src/go_hotel/services/hotel_money_bridge.py`
- `application/src/go_hotel/agent_gateway/real_core.py`
- `application/src/go_hotel/db/models.py`
- `application/src/go_hotel/services/catalog_cash_fare_execution.py`

D03_RESULT=CURRENT_AUTHORITY_SPLIT_IDENTIFIED
D03_BLOCKER=FUTURE_REAL_MONEY_AUTHORITY_NOT_FORMALLY_ASSIGNED
