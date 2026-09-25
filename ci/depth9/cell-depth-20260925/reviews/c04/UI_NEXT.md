# Minimal existing UI integration path

Inspected `application/frontend/consumer/rental-after-sales.js`: wraps existing renderMobilityOrder/mobilityModify, uses state.rentalOrder, GOBooking.dialog, api, money and toast. Currently renders dates, pending change and pending refund, without damage-case discovery/actions.

Next bounded implementation:
1. Add owner-checked verified latest-case discovery on rental order detail or GET damage-cases (reuse damage._history; do not ask consumer to type case ID, don't infer current decision from historical replay).
2. Extend existing rental-after-sales render wrapper with a case card: claimed amount, submitted pickup/return evidence, customer response, current decision, appeal history and plain-language pending review. Render escaped values, never supplier HTML.
3. Consumer response and appeal dialogs bind expected_version and keep one idempotency key for retries; refresh latest case after 409 or reconnect. Never let browser supply actor/owner/role/reviewer or execute money.
4. Evidence upload must return server-bound media reference + digest and scope to order/actor; existing form references alone are isolated fixtures. Real UI must not ask customers to invent SHA256 or technical evidence URLs.
5. Admin console case queue: authenticated opening/review/appeal review; separate claimant and adjudicator identities; display unverified-source label honestly. Disable write controls outside isolated environments until verified supplier binding/policy/media path exists.
6. UI acceptance: phone viewport; own vs other customer's case; same-tab retries; stale version; independent review; appeal hold and reversal; no misleading deposit released/charged text when money_status remains review-required.

No frontend file modified this round. Backend source review and funds authority remain separate gates.
