# C07 account transaction fence

Source: c318980c5bd6d8c55756c22d8dfeb6046d9ab7db.

This closes the source-code phantom insertion gap identified after the existing-job deletion fix. Existing source jobs alone could not fence a concurrently inserted job. Source lifecycle/import operations now share a PostgreSQL account-scoped transaction advisory lock, before connection and job row locks. SQLite keeps BEGIN IMMEDIATE. No schema or table-wide lock is added.

The callback owner probe is refreshed after the account lock, with owner checked again. Internal _session call sites already hold the account fence and reuse the transaction. RESULT.json enumerates each covered entry point. Other vault operations are not claimed to be globally serialized.

Final distinct scope: 62 local cases passed. First run: 61 passed and 1 test-spy failure due to observing SQLAlchemy's internal SELECT for the explicitly permitted owner probe. The spy was narrowed to service calls; all 5 new fence tests then passed, with no source change. Logs are retained. LOCK_SQL_CAPTURE.json captures parameterized SQL and deterministic account keys without executing PostgreSQL.

The earlier source-lock-fix phantom missing-code limitation is superseded by this code, while its original evidence remains historical. Actual PostgreSQL concurrent execution is NOT_RUN, and is not inferred from SQL capture or SQLite threads. Combined-source C14 and independent C13 remain required. No upload, merge, or deployment was performed.
