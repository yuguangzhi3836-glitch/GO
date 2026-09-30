# CI PostgreSQL acceptance harness

The workflow `.github/workflows/c1-c14-runtime-postgres.yml` provisions an
ephemeral PostgreSQL 18 service inside GitHub Actions and executes the Runtime
acceptance suite against it.

It is deliberately isolated from HK-STAGING, Command Center live services,
Production, payment and supplier systems.

Current scenarios:
- 1,000 task contention at 4/8/16 workers;
- unique idempotency-key enforcement;
- effect-key exactly-once recording;
- worker crash after claim and lease recovery;
- stale-worker completion fencing;
- retry exhaustion -> ESCALATED;
- evidence projection consistency.

The workflow uploads raw results plus JUnit/SHA256 aggregate evidence.

Note: the current GitHub Actions service-container model does not expose a safe
in-job Docker restart control for the service container through this candidate.
Therefore a true PostgreSQL process/container restart must still be executed in
a dedicated isolated runner before installation eligibility. The harness must
not call a marker-only check a production-grade DB restart proof.
