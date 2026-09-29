# Payment next step — 2026-09-26

Status: DEVELOPMENT CANDIDATE. No merge, deployment, real supplier, merchant credential access or live payment.

## Owner instruction
First close internal ledger and the isolated complete Aoluguya operating day; concurrently determine the first payment provider/product. Then implement the provider and perform available external test integration. Limited real-payment verification requires a separate future Owner authorization.

## Internal regression repair
Parent gate: ceb21e65a525993eeea34f50567c1089b16ece3a.
Product/test commit: 1d7df6f63525e4e9809da8f5ea3461f74090b1a0.
Application tree: 978e6b99ca391cc8913db0942aece15009a96b30.
Application files: 1546.
Application fingerprint: 0a1971254e4842364cbc0fbaef37e132ad337b8a108d9906475002ac52797d72.

Observed failure: run 36226335761 / job 108360993033, tests/payments/test_c11_deposit_ledger_width.py::test_deposit_capture_release_passes_database_column_constraint. The prior test pinned storage at 64 while migration 0140 and the model declare 128. Monetary state, complete RD identity and balanced 4000 debit/credit assertions passed before this mismatch.

The repair verifies BOTH model and actual database column width 128; aligns SQLite enforcement with PostgreSQL; tests acceptance at128 using a rolled-back direct SQL probe; rejects129; retains exact identity, amount balance, replay and the separate64-character RD business identity contract. Existing migration preservation and lossy-downgrade rejection tests are unchanged. No product implementation or business rules changed.

Local verification: Python syntax only. Original source fingerprint recomputed from the downloaded immutable source/SOURCE_FINGERPRINT.json (artifact10900498593, ZIP SHA256 0fb55a682c20a101b6ecd29faf592a30b7bd02fbb8a35820d221a882cb679d83); old fingerprint verified before replacing the one changed test digest. Full bytes must be independently rehashed in CI. No local full-suite claim. New CI and independent C13 review remain pending. Historical PASS is not transferred.

## First provider/product technical selection
Preferred first development target: Alipay preauthorization (fund authorization), hotel merchant as payee; exact legal merchant identity, product eligibility, client route, contract and credentials remain unverified. This is a technical selection for preparation, not a signed merchant contract or activation.

Why: existing hotel lifecycle models authorization before final capture; the official flow describes authorization followed by deduction when service completes. Product must support the intended booking lead time, stay length and final charge/refund policy. Ordinary immediate payment is not an automatic substitute. Preauthorization capture timing and bank settlement timing are distinct.

Official sources checked:
- https://opendocs.alipay.com/open/00nawg (Alipay preauthorization quick integration): currently states preauthorization does not support sandbox debugging.
- https://opendocs.alipay.com/open/02f912 (online fund authorization freeze API).

IMPORTANT CORRECTION: no supported Alipay preauthorization sandbox is established. Local simulated or contract tests must never be called official sandbox certification. The generic sandbox executor interface in current GO is not evidence of provider sandbox support. Do not fabricate app IDs, signers, certification results or credentials. No ordinary-payment fallback without business review.

## Next implementation contract, after internal gate closure
Preserve PaymentOrderRoot/FactBinding -> Intent/Attempt -> MoneyMovement -> Ledger.
Use provider-specific request signing, response/callback verification, merchant/app/order/amount/currency binding, persisted request identity, query-on-unknown, idempotent callbacks and reconciliation. Existing local HMAC or contract-only receipts do not prove Alipay verification.
Separate simulation, provider-certified test environment (only if actually available for the contracted product), and LIVE. A configuration flag alone cannot confer certification.
Map authorized funds, capture, release, refund and external bills to existing authority records; never create a parallel ledger.
Merchant inputs required: legal merchant/payee identity, approved product contract, application/client type and official credential references. Do not put private keys or passwords in GitHub/chat.

## Acceptance / stopping conditions
Internal: corrected exact candidate passes enforced-width tests, actual PostgreSQL migration/data preservation and full business-day normal/exception reconciliation; independent C13 opinion bound to source.
External: provider product and test capability confirmed; implement from official contract; offline tests first. For Alipay preauthorization, external real verification remains BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION; unsupported sandbox is NOT_APPLICABLE, never PASS.
Live: separate Owner authorization must define merchant, environment, allowed accounts, per-transaction/aggregate limits, operations, time window and stop/reconciliation conditions before any funds movement.
Pending commercial questions retained: cancellation-clock anchor, other unconfirmed hotel rates and real room registry. Do not infer them from fixtures.
