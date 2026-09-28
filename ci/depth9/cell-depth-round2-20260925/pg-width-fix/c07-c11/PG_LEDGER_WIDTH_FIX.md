# PostgreSQL deposit ledger width correction

Failure evidence: CI run 36116380958 / job 108011368278, independently retained by C13 in `reviews/round2/c13/failed-pg-increment.*`. 162 passed / 5 failed. All five failures were PostgreSQL rejecting a 73-character deposit business ledger account code against existing VARCHAR(64). Ordinary SQLite VARCHAR did not enforce this limit.

Correction is deliberately narrow:

- New RENTAL_DEPOSIT ledger writes use `RD:<complete obligation_id>`: current IDs produce 52 characters. RD is a reserved namespace; the entire business ID remains unchanged and visibly recoverable. Two different complete IDs cannot become equal through truncation or hashing because neither is used.
- Other business account codes retain their existing representation.
- Writer and deposit graph validator use the same account-code helper. An oversized future deposit ID fails before either ledger entry is added.
- Existing legacy captures are readable only when the complete two-entry capture exactly matches the old code and all existing identity/amount/currency/direction/evidence checks pass. Corrupt/truncated codes are rejected. No existing account or business identifier is rewritten.
- No migration, increased column size, C04 identifier change, or weakening of the ledger assertion was introduced.

Regression: `tests/payments/test_c11_deposit_ledger_width.py` installs actual SQLite INSERT/UPDATE database triggers equivalent to the VARCHAR(64) limit; on PostgreSQL the native constraint is used. It verifies source-bound capture/release succeeds, deliberately oversized SQL updates fail, complete identities with equal long prefixes remain distinct, explicit oversize code rejection occurs before ledger insertion, exact legacy reads remain unchanged, and corrupt legacy identity is held.

Local result: **33 passed**, including existing deposit tests, in 8.47 seconds with `-p no:cacheprovider`. PostgreSQL rerun remains required on the new product binding; this local result is not a PG PASS.

Frozen three-file manifest: `PG_WIDTH_FIX_SHA256SUMS.txt`. Independent C13 review was requested before the parent rebinds CI.
