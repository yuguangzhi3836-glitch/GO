# C01 / C07 local depth repair — 2026-09-18

Candidate only. No upload, merge, deployment, live migration, or provider readiness is claimed.

C01 fixes lower-case legal/address/brand changes bypassing review and prevents new hotel-library imports from mutating a non-draft property while reporting DRAFT. Existing draft imports and low-risk contact maintenance remain available.

C07 makes import preview creation and connection publication atomic, rolls back malformed uploads so they can be corrected, prevents late callbacks from resurrecting disconnected/deleted connections, freezes pending imports after disconnect, and keeps deletion terminal. Authorization-state comparison now hashes exact bytes rather than case/whitespace-normalized profile values.

Initial reproduction: 10 failed / 1 passed. Additional opaque-state reproduction: 2 failed. Final distinct coverage: **43 passed, 0 skipped** (C01 23 in verification.xml; C07 20 in final-c07.xml). The intermediate after.xml has four test-assertion failures caused by SQLite timezone serialization; comparing the stored property before/after corrected the assertion without weakening the mutation check. Raw logs and JUnit reports are retained.

RESULT.json binds changed files, commands, results, source identity and NEXT_TASK. SHA256SUMS.json binds the evidence. Local application-tree identity includes the initial snapshot's generated cache; root integration removes that inherited file and rebinds the combined application source. Exact-source C14 and independent C13 remain pending. PostgreSQL locking, real provider integration, published hotel workflows and device/UI acceptance are not proven by these SQLite tests.
