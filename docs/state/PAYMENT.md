# PAYMENT — CURRENT STATE

Baseline: `main@8ffcde66d36c1bbf849218529ef015f6e81725af` (refreshed 2026-09-14; previous baseline `286e294d`)

Truth classes: `CURRENT_MAIN_FACT` · `ACTIVE_CANDIDATE` · `UNKNOWN / HOLD / BLOCKERS` · `EVIDENCE / ENTRYPOINTS`

## CURRENT MAIN FACTS

- Current main contains both native HOTEL payment records/flows and newer omnichannel payment/funds models.
- Current code includes concepts such as payment intent, payment attempt, money movement, payment-order root/fact binding, ledger/reconciliation-like records and agent-facing payment truth.
- HOTEL native booking currently uses a mock payment provider for authorize/capture/void/refund semantics.
- Repository code does not prove that real WeChat Pay, Alipay or international-card acquiring is configured for live execution.
- Current main therefore must not be described as having a completed production Payment Center merely because payment/funds code exists.
- Newly merged on main since the previous baseline: `application/src/go_hotel/flight/payment_recovery.py` and the C11 flight idempotency/completion-guard work. This is **flight-side payment recovery and idempotency on existing payment roots** — it is not a Payment Center, adds no new money truth, and does not change the statements above.

## ACTIVE CANDIDATES

- PR #61 — `Payment Center: start technical reality discovery before implementation`
  - branch: `payment-center/reality-discovery-01`, head `bf1c266aaaad980de1ea667d02ff5620e09a4060`
  - status at this checkpoint: **OPEN / DRAFT / unmerged** (verified 2026-09-14)
  - purpose: establish order, inventory, payment authority, binding and PSP facts before Payment Center implementation.

PR #61 is not imported into `CURRENT MAIN FACTS` simply because it exists. Its discovery output must not be restated as canonical main payment architecture.

## CURRENT HIGH-RISK QUESTIONS

- Which existing representation ultimately owns authoritative money truth?
- How should native HOTEL payment facts relate to omnichannel payment/money records?
- What is projection/adapter versus source-of-truth?
- What is the real hotel inventory/payment sequencing contract?
- Which PSP/acquirer products are actually eligible and available to GO/hotels?

These are questions, not silently approved architecture decisions.

## BUSINESS DECISION HANDLING

Payment business owners should normally decide outcomes in plain language.

Technical terms such as PaymentIntent, MoneyMovement, ledger, authorization, capture, idempotency and reconciliation belong in engineering evidence/design, not in management decision questions unless translated.

When a payment business decision changes, preserve the earlier decision and perform impact review instead of overwriting history.

## UNKNOWN / HOLD / BLOCKERS

- Live-money execution authority: not granted by this state card.
- Real merchant/sub-merchant onboarding: not proven here.
- Real PSP sandbox behavior for GO: not proven here.
- International-card acquirer/product selection: not established as a current main fact here.
- Payment Center ownership boundary: under active discovery, not yet canonical.
- `HK_DEPLOY` / `FINAL_RELEASE` / `PRODUCTION` remain `HOLD` on canonical main; no payment-side exception exists.

## EVIDENCE / ENTRYPOINTS

- `application/src/go_hotel/services/booking.py`
- `application/src/go_hotel/payments/mock.py`
- `application/src/go_hotel/services/omnichannel_payment.py`
- `application/src/go_hotel/services/unified_money_movement.py`
- `application/src/go_hotel/services/hotel_money_bridge.py`
- `application/src/go_hotel/flight/payment_recovery.py`
- `application/src/go_hotel/agent_gateway/real_core.py`
- active candidate PR #61

PAYMENT_STATE_STATUS=REFRESHED_AT_MAIN_8ffcde66
