# C13 independent review V2: PASS_SCOPED

This verdict is limited to the V2 payment audit integrity/readiness repair in the supplied minimal dependency subset. V1 FAIL evidence remains unchanged under review/. No implementation files were modified by the reviewer.

## Independently verified

`PYTHONPATH=src:tests python -m pytest tests/test_payment_sandbox_audit_integrity.py review/v2/test_independent_review_v2.py -q --junitxml=review/v2/independent-tests.xml`: 35 passed (23 supplied tests plus 12 independent cases), with the expected unknown no_db marker warning because repository pytest configuration is absent.

The independent cases verify both sole-grant identity mutations now block new certification writes; corrupt grant actor no longer produces a preflight certification false positive; two concurrent appends both commit with a valid resulting chain; resource_type/resource_id damage is detected at root, middle and tail; healthy ALIPAY and WECHAT_PAY chains remain independent; and two concurrent writers attempting conflicting actor reuse of one reference produce exactly one commit and one reference-conflict rejection.

The concurrency barrier was moved immediately before entering `_append_event`, so the new transaction lock can serialize execution normally. No synchronization barrier is imposed inside the critical section. These tests use isolated SQLite sessions and do not fake query results or the lock implementation.

The readiness, certification and cutover safety scripts were independently rerun and all passed. Logs, JUnit and independent test source are alongside this report. Frozen V2 hashes were recomputed and matched exactly.

## Assessment

The V1 reproduced identity-filter bypass, append fork and preflight false-positive defects are repaired for the tested cases. `_events` uses an additional retained role marker, hash binding and link closure; `_append_event` locks before chain reads; preflight uses validated cutover certification state. No additional scoped blocker was reproduced.

## Limits and remaining gates

This reviewer executed SQLite only. PostgreSQL advisory-lock behavior is source-reviewed, not independently executed here; the planned isolated PostgreSQL gate must pass before claiming that backend is verified. The implementation is intended for normal READ COMMITTED transaction behavior; this review does not establish behavior under arbitrary isolation levels or concurrent out-of-band database updates.

Retained roles, original hashes and links are local recovery evidence, not a separately trusted immutable ledger. A DBA rewriting the entire chain, deleting a complete suffix, or changing multiple discovery anchors coherently is outside this hash integrity guarantee. These tests do not constitute a cryptographic signature, external attestation or universal corruption detector.

No real PSP, merchant key, Hong Kong action, deployment or merge was accessed/performed. Full repository reconstruction and the reported 17 parent blob identities were not independently reverified here. A minimal-subset scoped pass is not full business-journey payment 100%, not proof of real provider connectivity, callback authenticity, real reconciliation/settlement correctness, or permission to connect external payment.

## Verified SHA256

- `src/go_hotel/services/payment_sandbox_cutover.py`: `37b4537b98d20e3e4ed40622758e95d36f403bf23b3081d3e9f947ffcc3c8f9f`
- `src/go_hotel/services/payment_sandbox_runtime.py`: `8ee52e0c3985e7951814a8d0eebf2a566c5e728b58abda8976298102a6cf73ad`
- `tests/test_payment_sandbox_audit_integrity.py`: `33075f98ee447576a793a48cb132fd077a7f40cdbaff5e4cdfa744956321a247`
