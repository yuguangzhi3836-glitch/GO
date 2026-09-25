# C11 response to C04 deposit/damage handoff

The current internal implementation can allocate partial CAPTURE and RELEASE against an AUTHORIZATION in the existing OmnichannelMoneyMovement graph. It checks cumulative and parent authorization budgets under the root Intent lock and uses deterministic idempotency keys. This capability is reusable; it does not prove the rental's deposit was authorized.

## Missing source contract: HOLD

- The rental order's deposit_minor is a quote/configuration value, not an authorization receipt.
- C04's adjudicated append-only case is an internal isolated adjudication record; supplier evidence is ADMIN_RECORDED_UNVERIFIED and money_status remains C11_MONEY_REVIEW_REQUIRED.
- The current create_intent resolver's ORDER_TYPES does not include RENTAL_DEPOSIT. There is no durable versioned deposit agreement tying order, vehicle, consumer consent, supplier/payee, currency, liability cap and authorization to a separate deposit root.
- RENTAL_ORDER is rent; RENTAL_CHANGE is a fare adjustment. Neither root may fund damage by relabeling its capture/authorization.

## Smallest safe future implementation

1. Agree the durable deposit source fact contract and consent/inspection provenance with C04/C14. A new deposit-obligation record and migration are likely needed because no existing durable source contains the required facts; this is not a second money ledger.
2. Resolve that record server-side into the existing PaymentOrderRoot + PaymentOrderFactBinding + Intent with dedicated RENTAL_DEPOSIT identity and immutable source revision. No caller-supplied payee or amount becomes authority.
3. In isolated fixtures only, create a contract-simulator AUTHORIZATION receipt on that bound root. Real activation remains separately gated.
4. Resolve C04's current adjudication under order/case locks; freeze decision hash and deterministic capture/release keys. Reuse existing Movement/Ledger and original authorization parent; serialize against concurrent allocation.
5. Record C04 outcomes only after verified C11 movement facts; unknown outcomes remain pending and retries recover the original operation. Reversal requires linked refund/compensation facts.

## Work implemented now

Source review found the consumer HTTP intent route forwarded arbitrary business types into the internal non-order fallback. That allowed a consumer to create an unbound RENTAL_DEPOSIT, RENTAL_CHANGE or arbitrary obligation using caller amount/payee. The consumer route now uses a dedicated source-bound service entry point that allows only existing authoritative ORDER_TYPES. Internal subscription/service creation remains unchanged. This closes an actual unauthorized source path without fabricating a deposit contract or claiming deposit settlement is complete.

No deposit root, deposit movement, schema migration, real PSP operation, or change to C04 money_status was created by this work.
