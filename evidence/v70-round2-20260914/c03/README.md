# C03 second-round scoped execution

Base: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`. Task: `R2-C03-RUNTIME-01`.

Status: Evidence ready; C14 and independent C13 are pending. Workflow completion is 4/6 phases; no full-domain percentage is asserted.

Scope:

- Rail API booking, ticketing, change, refund and account isolation
- Persistent rail change resolution, crash/replay and money receipt checks
- Dual date inventory holds: confirmed and failed change both release the correct pool; final refund releases the remaining allocation

Results: 27 passed, 0 failed, 0 skipped in final passing runs. Each run has command/environment, raw log, JUnit and before/after domain SHA-256.

Unresolved:

- PostgreSQL concurrency and physical supplier ticket issuance were not run.
- Image/HK/browser and real provider acceptance remain outside this scoped evidence.

Next task (ready for central dispatch, not represented as executed): R2-C03-DEPTH-02: verify unpaid-expiry versus payment/cancellation race and full target inventory rejection before supplemental authorization.

Execution was isolated SQLite with synthetic providers and FastAPI TestClient where used; this is not browser, HK, image or production acceptance. No remote write, merge or deploy was performed.
