# DEPTH24 independent runtime acceptance

This workflow uses only disposable PostgreSQL 16.4 / Redis 7.4 services in GitHub Actions, Python 3.13.5, frozen offline wheels, and Node 22.22.0. It has read-only repository permission and consumes no deployment, payment, production, or user credentials. The database password is a disposable CI fixture.

The pinned DEPTH17 WORK and sealed DEPTH24 cumulative delta reproduce the complete tracked source manifest. The separate locked parent restoration and 1542-case historical acceptance remain preserved in the engineering archives. Source materialization in CI is not presented as full parent-runtime restoration.

The original six PostgreSQL cases run without skipping. The unchanged thirty DEPTH24 cases are also exercised with a separate fixture using the disposable PostgreSQL service; twenty-nine cover application behavior and one is a SQLite migration-history test. Redis uses the actual project queue adapter. Node runs all 115 frontend logic tests and 44 JavaScript syntax checks.

Missing reports, skipped tests, or failed prior steps hold the runtime gate. Even a successful runtime gate does not pass the final system Release Gate: whole-system business depth, master traceability, and browser/device acceptance remain open.
