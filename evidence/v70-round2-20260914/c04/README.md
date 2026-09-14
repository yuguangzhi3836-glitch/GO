# C04 second-round scoped evidence

Anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; inherited first-round results remain bound to their prior source/scope.

Task: C04-R2-REFUND-LEDGER-RECEIPTS

A confirmed executor response must identify actual confirmed refund rows from this order owner/currency/original and positive-change roots, with the exact expected sum; reject missing/empty/capture/foreign receipts, then recover exactly once. Retain completed/order-state contradiction guard.

Local task result: **5/5 selected tests PASS**. Complete Cell percentage is not claimed. C14 and C13 are pending independent review.

Small service fix reuses existing shared validator without changing validator, models, migration, fee or permission rules. Deposit/bank/external acceptance remains unproved.

Next task: Review completed historical rental refunds against frozen plan and ledger without executing money or auto-repairing state; determine a safe reconciliation task for real contradictions.

Evidence: `result.json`, `runs.json`, `source-identity.json`, `after.raw.log`, `after.junit.xml`.

Before fix: four receipt cases FAIL and one inherited terminal guard PASS (5 collected). After fix: 5/5 PASS; necessary adjacent settlement/consent/terminal regressions 27/27 PASS. The initial interpreter failure exit127 is preserved separately.

No test dependency was installed or changed. The second baseline run used the available primary Python3.12.14 plus historical site-packages. Final runs use the restored local interpreter with the same dependency set.

Scope excludes live providers, bank/deposit settlement, PostgreSQL, HK deployment and production. No shared model, migration or permission changes; no remote write, merge or deployment.

## C14-directed continuation: exact frozen refund plan

The first candidate was held by C14: owner/root/currency/total checks alone allowed an earlier equal refund on the same order to stand in for the current cancellation. The new regression starts from three rental days (126000), shortens to two and then one (two prior 42000 refunds), and tries to use a prior 42000 receipt to complete cancellation of the remaining 42000. The first candidate FAILS this regression (DID NOT RAISE), retained in `receipt-plan-before.*`.

The correction compares actual receipt tuples `(payment_intent_id, capture_id, amount_minor, idempotency_key)` to the immutable cancellation plan as an exact multiset, after the prior ownership/currency/root checks. Invalid proof remains REFUND_PENDING; a real retry completes the remaining refund once. Business amount rules are unchanged.

Current candidate: **6/6 C04 scoped tests + 27/27 adjacent regressions = 33/33 PASS**, zero skips/errors. See `receipt-plan-after.*`, `receipt-plan-runs.json` and **`receipt-plan-source-identity.json`** for the current source. Earlier `source-identity.json` and test artifacts intentionally retain the initial candidate identity. C14 re-review and C13 remain pending; this implementer does not self-approve.
