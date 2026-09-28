# Browser gate repair after a0f3ebc

Run 36116380996 / job 108011368484 failed; original artifact 10855492280 remains authoritative failure evidence. This result is not relabelled PASS.

The browser observer only recognized /refund and /cancel, while mobility UI correctly confirms the bound refund quote through /refund-confirmed. Three observer/request-capture/wait matchers now include that endpoint. The response wait is additionally bound to the same order ID. Existing quote, capture/refund counts, amounts, currency, ledger, final state and identical-request replay assertions are unchanged.

The rental deposit scenario was incorrectly scheduled after booked() had already run the full rental refund. A refunded rental must not offer a fresh deposit obligation. The scenario now runs inside booked(), after successful original capture verification and before the existing rent-refund journey. It still verifies no implicit acceptance, explicit checked consent, ACTIVATED without payment intent/authorization, refresh stability and mobile-width layout. The original rental refund remains mandatory.

Only ci/journey-v2/browser.mjs changes. The application tree, product commit and application fingerprint remain unchanged. Node syntax check passed; actual browser execution and independent C13 review remain required on the new gate commit. All five candidate CI groups will be evaluated on the new head; no prior-head PASS is transferred.
