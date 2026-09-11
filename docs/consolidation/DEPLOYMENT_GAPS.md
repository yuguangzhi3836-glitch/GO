# Deployment gaps for canonical GO application source

The canonical application source is software-validated; it is **not** authorized or proven ready for an HK switch. This document records differences that must be resolved in a separately authorized deployment workflow.

## Database / Alembic

- DEPTH40 isolated runtime validation migrated a disposable PostgreSQL 16 database through Alembic head `0132_rail_runtime_field_widths` and rejected an old head when migration was not explicitly part of the operation.
- The current live HK RDS Alembic head/schema was not read or changed by this consolidation.
- Before any deployment, current RDS head and schema must be freshly observed through an authorized read-only preflight.
- If HK is below the required revision, migration becomes a separate explicit requirement. This consolidation does **not** authorize or execute it.
- PR #37 additionally proved synthetic PostgreSQL 18.4 upgrade/recovery behavior, including rollback/failure/recovery scenarios, but synthetic CI does not substitute for current HK schema/backup evidence.

`MIGRATION_EXECUTED=NO`

## Runtime services

DEPTH40 review expects eight business targets:

1. `api`
2. `recovery-worker`
3. `outbox-worker`
4. `mobile-push-receipt-worker`
5. `reconciliation-worker`
6. `mobile-push-worker`
7. `mobile-engagement-worker`
8. `judgment-worker`

Redis and Caddy are dependencies/non-targets in the archived HK deployment model. The exact current HK service mapping, worker commands, environment and health state must be freshly checked; historical documentation must not be applied over drift.

## Image / registry / execution binding

- The selected application source is **not** the currently installed HK business image.
- The validated DEPTH40 staging image was created in isolated CI and was not pushed/deployed to HK by the product PRs.
- A formal future deploy requires an approved image source/RepoDigest and compatibility with the installed narrow Executor's release-binding checks.
- The runbook notes that different-image candidate validation is implemented at the Executor level, but a formal different-image HK DEPLOY E2E is `NOT_PROVEN`.
- Do not substitute direct Docker/Compose mutation for the signed Task → HK Agent → narrow Executor → Signed Evidence path.

## Media layout

- DEPTH40 runtime review uses a dedicated persistent media volume and fails closed if expected local media/index layout is not satisfied.
- It does not silently generate/convert a production media index in HK.
- The current HK media volume path, ownership, permissions, index compatibility, capacity and backup must be mapped before a switch.

## Environment and external providers

- No runtime `.env` values are stored in this consolidation.
- Current HK environment variable names/required values must be mapped against the canonical source without copying secrets into GitHub.
- PR #25 found eight canonical supplier inputs empty and correctly stopped before external calls; those provider credentials/sandbox inputs remain an external readiness gate until separately supplied and verified.
- External network routes, provider endpoints and payment/supplier production credentials are outside this consolidation.

## Frontend / mobile

- Canonical source contains frontend and native/mobile assets carried by the 1271-file sealed source.
- P0.3 Apple Xcode/AppIntents software compilation passed on an iOS 18 simulator.
- Physical iPhone execution remains `HOLD_EXTERNAL_DEVICE_RUNNER`; simulator evidence is explicitly insufficient for that gate.
- Three-end real-browser/login validation and six-vertical real transaction E2E remain deployment-stage HOLDs.

## Runtime configuration

Before HK deployment, map and verify at least:

- Compose file and hash;
- current runtime environment hash (without exposing values);
- Caddy upstream/HTTPS routing;
- cookie/session expectations;
- DB and Redis connectivity;
- media mount layout and permissions;
- eight target service image IDs/RepoDigest;
- worker liveness and restart behavior;
- disk/memory/resource budget;
- non-target container integrity.

## Backup and rollback

- A current recoverable backup is required before any separately authorized migration/deployment.
- The proven HK path requires a durable `DEPLOY_RECORD_V2` before mutation and uses the formal signed rollback contract; caller-supplied image rollback is not the authority model.
- Verify durable previous-state eligibility and the installed rollback-capable Executor before a new candidate deployment.
- Historical container IDs or historical documentation must never be restored over current live state merely because they were once valid.

## Proven versus unproven boundary

Software/source evidence currently supports:

- exact sealed source identity: PASS;
- 1271-file zero restore: PASS;
- P0.2/P0.3 regression sentinel: PASS 17/17;
- isolated eight-service PG16/Redis runtime: PASS 20/20;
- synthetic PG18 upgrade/recovery review: PASS;
- canonical checkout contains complete source directly: PASS.

Still HOLD / not proven for the future HK switch:

- fresh live HK drift preflight;
- live RDS head/schema compatibility;
- any required migration authorization/execution;
- actual HK image/RepoDigest binding for this new candidate;
- exact current eight-service/Caddy/env/media mapping;
- current backup/resources/durable rollback state;
- supplier/provider live inputs;
- physical iPhone gate;
- three-end real browser gate;
- six-vertical real E2E;
- formal different-image DEPLOY E2E;
- Production release.

`HK_STAGING_DEPLOYMENT=HOLD`
`HK_RUNTIME_MUTATION=NO`
`PRODUCTION_ACTION=NO`