# C13 independent review — deposit ledger width correction

Scope: frozen 3 paths in ../c07-c11/PG_WIDTH_FIX_SHA256SUMS.txt, independently hash-matched after execution. Product source was not edited by reviewer. Candidate acceptance and scoring remain HOLD pending new exact-head CI.

Actual prior PostgreSQL failure: BUSINESS:RENTAL_DEPOSIT:<49-character obligation ID> requires 73 characters but account_code is VARCHAR(64). This is a product defect; see PR246_a0f3ebc_CI_REVIEW.md and retained original failed-pg-increment.xml/log.

Correction reviewed: RENTAL_DEPOSIT writer uses reserved RD: namespace followed by complete unchanged obligation ID (52 characters for current IDs). It does not truncate/hash identity. Other business codes retain their existing namespace. IDs exceeding the 64-character code limit raise before either ledger entry is added. Deposit graph validator shares the helper and accepts either exact new two-entry pair or exact historical full-name two-entry pair, checking amounts/currency/type/movement evidence; it does not rewrite legacy facts. Corrupted historical prefixes fail closed. This preserves original business IDs, source hashes, graph root/parent and accounting balance.

Independent execution: go-venv/bin/python -m pytest -p no:cacheprovider tests/payments/test_c11_deposit_ledger_width.py tests/payments/test_c11_rental_deposit_money.py, with separate DATABASE_URL. Original JUnit width-independent.xml: 33 tests, 33 passed, zero failed/errors/skips. Includes all five previously PG-failing cases and full capture/remainder conservation, rollback, concurrent retry, missing ledger, complete suffix identity, boundary length, oversize-before-write and legacy exact/corrupt compatibility. New database test installs INSERT/UPDATE width-enforcement triggers for SQLite and proves a 65-character direct SQL update is rejected.

This is local SQLite evidence with an explicit constraint, not PostgreSQL execution. New PG gate should retain all prior 167 cases plus three PG-applicable width node IDs and enforce zero skips. Two historical oversized SQLite-only fixtures intentionally belong to full SQLite retention, since PG never admitted those historical oversized rows. Bounded capacity must actually execute; it was skipped on the failed head.

Conclusion: no remaining blocker found in this narrow correction; ready for exact-head CI verification, not final candidate acceptance.
