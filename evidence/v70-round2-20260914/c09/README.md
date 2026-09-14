# C09 second-round scoped execution

Base: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`. Task: `R2-C09-EVIDENCE-AUTHORITY-01`.

Status: Evidence ready; C14 and independent C13 are pending. Workflow completion is 4/6 phases; no full-domain percentage is asserted.

Scope:

- Reproduce and reject six request overrides of persisted risk/review/remediation evidence
- Confirm serious-risk veto with a complete independent six-dimension endorsement assessment
- Require every recommendation dimension and explicit boolean commercial independence; retain existing HTTP runtime and nested commercial/traveler-fit exclusions

Results: 25 passed, 0 failed, 0 skipped in final passing runs. Each run has command/environment, raw log, JUnit and before/after domain SHA-256.

Baseline regression: 6 failed / 10 passed. The request could replace persisted evidence fields. The candidate rejects overlapping database-derived fields before a judgment is published, while keeping independent assessment supplementation.

Unresolved:

- Builder tests are isolated SQLite/FastAPI TestClient with synthetic evidence; no physical reviewer/provider, browser, image, HK or PostgreSQL concurrency acceptance.
- Concurrent reevaluation / durable hook replay remains a separate depth task.

Next task (ready for central dispatch, not represented as executed): R2-C09-DEPTH-02: verify same-hotel concurrent reevaluations and hook replay preserve one ACTIVE judgment and a matching current recommendation/evidence snapshot.

Execution was isolated SQLite with synthetic providers and FastAPI TestClient where used; this is not browser, HK, image or production acceptance. No remote write, merge or deploy was performed.
