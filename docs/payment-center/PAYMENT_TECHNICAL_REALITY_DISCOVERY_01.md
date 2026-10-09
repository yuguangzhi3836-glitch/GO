# PAYMENT TECHNICAL REALITY DISCOVERY 01

Status: READ_ONLY_DISCOVERY
Scope: Payment Center / Hotel P0
Live money: LOCKED
Code authority: NO
Deploy authority: NO

## Purpose

This document opens the first technical reality-discovery phase for GO Payment Center.

The goal is not to design a new payment system from assumptions. The goal is to establish the current technical facts of GO order, inventory, payment, refund and PSP capability before any Payment Center implementation is authorized.

No conclusion may be promoted to architecture baseline unless it is supported by one or more of:

- current repository code;
- current database models or migrations;
- executable tests or logs;
- current runtime evidence;
- official PSP documentation;
- PSP Sandbox evidence;
- explicit management business decisions.

Unknowns must remain UNKNOWN. AI must not fill missing facts with industry convention or an idealized transaction model.

## Existing business authority

The Payment Center line is based on the approved GO Hotel Payment P0 business direction, including these core boundaries:

- hotel is the room-charge merchant / collection主体;
- GO provides booking and payment technology and does not pool hotel room revenue;
- GO subscription fees are independent from guest room charges;
- payment success and hotel-order confirmation are separate facts;
- P0 Payment Center handles GO consumer hotel orders only;
- OTA-imported orders may be synchronized/displayed but their payment/refund/freeze/settlement remains outside Payment Center P0;
- real money operations remain disabled until separate approval and production gates are satisfied.

This discovery does not reopen those business decisions.

## Critical current risk

Current GO main already contains payment-related concepts and implementations such as PaymentTruth, payment intent, money movement, refund and hotel money flows.

Therefore Payment Center must not be implemented as a second independent payment truth by default.

Before implementation, the project must determine which current objects are:

1. business-side projections;
2. current authoritative money facts;
3. adapters to be retained;
4. legacy/transitional implementations;
5. capabilities to migrate under Payment Center authority;
6. capabilities to retire.

Creating a second payment, refund, ledger or settlement truth without an explicit migration/authority decision is prohibited.

## Discovery workstreams

### D01 - Current GO order lifecycle

Establish from current code and data models:

- when a hotel order is created;
- which states exist and what transitions are implemented;
- when an order becomes payable, valid, failed, cancelled or expired;
- whether order expiry exists and how it is enforced;
- how quote/price/cancellation-policy snapshots are bound;
- how order identity/version/idempotency is represented;
- how payment state is currently connected to order state;
- how hotel confirmation is represented separately from payment success.

Deliverable: ORDER_LIFECYCLE_FACTS.md

### D02 - Current hotel inventory truth and concurrency control

Establish from current code, schema and integration paths:

- the actual inventory source(s) of truth;
- who may decrement/reserve/release inventory;
- whether a central inventory authority exists;
- whether atomic reserve/check-and-commit exists;
- transaction, locking, optimistic-version or queue mechanisms currently used;
- multi-night / multi-room behavior;
- cancellation and inventory release behavior;
- duplicate release protection;
- interaction with hotel-managed inventory and OTA synchronization;
- behavior for two concurrent requests for the final room.

Deliverable: INVENTORY_AUTHORITY_AND_RESERVE_FACTS.md

If no evidence for atomic reserve exists, record that as a blocker. Do not invent one.

### D03 - Current payment authority map

Inventory every current payment/funds-related implementation, including at minimum:

- PaymentTruth;
- PaymentRequest / payment gateway paths;
- OmnichannelPaymentIntentRow;
- OmnichannelMoneyMovementRow;
- PaymentOrderRootRow;
- PaymentOrderFactBindingRow;
- PaymentRow;
- RefundRow;
- hotel_money_bridge;
- hosted_money;
- hosted_credit / refund paths;
- agent gateway payment preparation;
- payment deadline / expiry mechanisms;
- ledger/reconciliation-like records where present.

For each item, record:

- path and owning module;
- persisted model/table if any;
- who creates it;
- who mutates it;
- what business fact it represents;
- whether it currently claims payment authority;
- whether it is source-of-truth, projection, adapter, simulator or unknown;
- proposed future ownership only as a candidate, never as a fact.

Deliverable: CURRENT_PAYMENT_AUTHORITY_MAP.md

### D04 - Hotel order / payment binding

Establish the current real binding between hotel order and payment:

- stable keys linking order, reserve, payment intent, payment attempt, money movement and refund;
- amount and currency binding;
- hotel / merchant / sub-merchant binding;
- snapshot/fact binding preventing cross-order or stale-amount payment;
- duplicate payment protection;
- retry and channel-switch behavior;
- payment-success versus supplier/hotel-confirmation behavior;
- current late-success / timeout / unknown-state behavior where implemented.

Deliverable: HOTEL_ORDER_PAYMENT_BINDING_FACTS.md

### D05 - PSP capability verification

Verify separately for WeChat Pay, Alipay and international-card acquiring/hosted checkout:

- product/mode intended for P0;
- when a real PSP transaction/order is created;
- when a usable QR/deep-link/hosted credential is produced;
- merchant-controlled expiry support;
- close/cancel/void support;
- query support and authoritative status source;
- asynchronous callback behavior;
- idempotency behavior;
- refund behavior;
- authorization / hold / capture / delayed-settlement capability where applicable;
- behavior under timeout, callback loss, network interruption and late success.

Official documentation can establish documented capability only.

Actual GO usability, merchant eligibility, signed-product availability and edge-case behavior require Sandbox or provider test evidence. These must remain NOT_VERIFIED until such evidence exists.

Deliverable: PSP_CAPABILITY_MATRIX.md

## Failure scenarios that must be covered before design freeze

At minimum the later integration review must explicitly handle:

- two users attempting to buy the final room concurrently;
- reserve success followed by payment failure;
- payment success with lost callback;
- payment success racing inventory expiry;
- GO outage after PSP success;
- repeated clicks / client retry / service retry;
- channel switch after a failed or unknown attempt;
- payment credential expiry followed by late success;
- payment success followed by hotel-confirmation failure;
- refund API timeout;
- concurrent refund requests / over-refund prevention;
- OTA or hotel-side inventory change racing GO checkout.

No default behavior is approved merely because it is common in other systems.

## AI operating rule for this workstream

AI may:

- read and trace code;
- inspect models/migrations;
- inspect tests and evidence;
- read official PSP documentation;
- identify contradictions and missing evidence;
- generate candidate options with consequences;
- write tests for already approved semantics.

AI may not independently decide or silently redefine:

- when inventory is reserved or released;
- inventory-reserve duration;
- payment-intent lifecycle;
- authoritative payment-success criteria;
- late-success handling;
- channel-switch rules;
- refund liability;
- settlement/unfreeze criteria;
- ownership of payment truth;
- behavior for PSP UNKNOWN / PROCESSING states.

For undecided matters the required output format is:

1. VERIFIED FACTS
2. UNKNOWN / MISSING EVIDENCE
3. OPTIONS
4. CONSEQUENCES (inventory / order / money / customer / recovery)
5. REQUIRED HUMAN DECISION
6. REQUIRED TEST / SANDBOX EVIDENCE

## Exit criteria for Reality Discovery 01

This phase is complete only when:

- D01-D04 are grounded in the current main branch and relevant schema/tests;
- D05 distinguishes official documented capability from actual Sandbox-tested capability;
- current payment authority conflicts are explicitly identified;
- unknowns are preserved rather than guessed;
- no second money truth has been introduced;
- no production payment, refund, settlement, inventory or deployment action has occurred.

Only after this phase may a Payment Center architecture candidate be proposed for formal review.
