# C06 — V70-R2-C06-02

EVIDENCE_READY (4/6 stages), independent C14 then C13 still pending. Whole-domain completion is unknown.

Source anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; inherited candidate: `a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b`.

Server-provided session-relative supplier validity contract: frozen IANA timezone, UTC half-open boundaries, integrity and redemption enforcement; legacy validity remains explicitly unverified.

Trusted catalog policies are optional and never accepted from client bodies. No default supplier policy is invented. Present policies are validated and sealed in existing prebook terms, then enforced using DB time under the order transaction. DST ambiguous/nonexistent sessions require review. Confirmed date changes reuse the sealed policy. Present contracts are integrity-checked before legacy fallback; redemption refuses missing contracts.

Current targeted result: **44 PASS, 0 failures, 0 errors, 0 skips**. Exact command, unique SQLite DB path, timestamps, source hashes before/after, raw output and JUnit remain alongside this report.

Earlier failures are preserved: red: 13 FAIL / 2 PASS before implementation; review-red: 2 FAIL / 16 PASS including deleted window and missing contract bypasses; original logs preserved.

Remaining concrete scopes:

- Default engineering catalog has no supplier validity policy: output LEGACY_UNVERIFIED, no supplier-window acceptance claim. Existing valid legacy contracts retain pre-existing redemption compatibility.
- Actual supplier authorization/policy evidence, provider callback ingestion and external redemption remain unproven.
- PostgreSQL, timezone database upgrade behavior, visible frontend window presentation and genuine supplier inventory are not covered.

Next executable task for scheduler: `V70-R2-C06-03` — Bind a real authorized supplier policy import to frozen validity terms and expose the frozen window/LEGACY_UNVERIFIED state consistently in the consumer flow; supplier data availability remains an explicit external gate.
