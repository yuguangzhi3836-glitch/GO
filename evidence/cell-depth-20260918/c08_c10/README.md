# C08 / C10 focused development evidence

Candidate source commit: `123df6fc580b528d1e12dea6eef2045c51cac0f6`. Classification: ACTIVE_CANDIDATE, local scoped pass only.

- C08: terminal failure audits now cover unexpected classification, planning and verification errors; no model replay or execution authority was added.
- C10: official evidence upgrades an unverified manual import even when the provider timestamp predates it; first-delivery races reconcile once; existing state is refreshed before transition checks and event deduplication follows the row lock.

The same nine new regression cases produced **8 failures / 1 pass** on the baseline and are included in the final **63 passes / 0 failures / 0 skips**. Baseline source files were restored only for the reproduction subprocess, then restored to the fixed bytes before final verification. Fixtures use isolated SQLite and deterministic providers. Raw log, JUnit, command, exact changed-file hashes and external holds are adjacent.

No source upload, merge, deployment, database migration, live provider connection, C14 verdict or independent C13 verdict is claimed. PostgreSQL concurrency, real provider evidence and client acceptance remain separate work.
