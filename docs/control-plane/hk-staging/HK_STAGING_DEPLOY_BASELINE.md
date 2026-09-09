# Proven HK-STAGING baseline

## Scope

- Environment: `HK-STAGING-01`
- Proven Agent version: `0.5.4-rebuilt`
- Agent source commit: `27f7f7f5b1b0d295c3f721c5c0728ceb9f69d9c8`
- Agent artifact SHA-256:
  `6387efc36237979c7590caec3da59b129deb9b132ded7a75139055b4b93f514e`
- Agent manifest SHA-256:
  `1a797755878d902e39fdd61a1948b70c03e8a77f9e9a911fd6eb930cc2e4f1ba`
- Proven Executor version: `0.3.0-verify-canary-deploy-runtime`
- Executor revision: `R4-fixed-post-deploy-api-readiness`
- Executor source commit: `2aedc3af8d8368d6a66f87a7117df61577a28fd6`
- Executor artifact SHA-256:
  `444ca59094b23be5e92a89f8a50f7bda86597a192905c220a8967bae54c351cc`
- Executor manifest SHA-256:
  `f1cbb3c6e8e2536e9bf5755773309a2c21113fa314af208358537b9728f062da`

## Fixed deployment inputs

- Compose file:
  `/home/go-stg/releases/r31-5-final-completion-20260906/GO_HYATT_DIRECT_BOOKING_R3_1_5_TEST_BOOTSTRAP_IDENTITY_FIX_20260906/deploy/docker-compose.r31-hk-staging.yml`
- Runtime environment file:
  `/home/go-stg/control/r317-five-star-completeness-20260828/runtime.env`
- Compose SHA-256:
  `7ef4ab181c1250d8cec0e348b29c24bfbb8e5dce4fc2a57f6faaa59363c26895`
- Environment SHA-256:
  `6682ff61f336fb8ff95a6585e9133c88c52a4eaa440a7aea6a6e06f771e607fc`
- Expected target image ID:
  `sha256:3a109d70e1e515173b89e0b510c5cbc5454d6b405760ce0ba69ec5811f314c88`

## Fixed target scope

Exactly eight services are in the controlled deployment scope:

1. `api`
2. `recovery-worker`
3. `outbox-worker`
4. `mobile-push-receipt-worker`
5. `reconciliation-worker`
6. `mobile-push-worker`
7. `mobile-engagement-worker`
8. `judgment-worker`

Redis and Caddy are not controlled deployment targets.

## Proven formal results

- Formal R4 DEPLOY E2E: `PASS`
- DEPLOY Task: `go-boss02-deploy-r4-20260909T131418835006Z`
- DEPLOY Task commit: `dfff0f8cdc957f00a6ef8f9393d6962d04009700`
- DEPLOY Evidence commit: `eb8c0dc060b51ced33188a0a4f16bed47a97f13b`
- Formal post-deploy VERIFY: `PASS`
- VERIFY Task: `go-boss02-post-deploy-verify-20260909T132251199297Z`
- VERIFY Task commit: `3a2e8ed7c081ddb9eadb8fd6e8d8c32949c3836c`
- VERIFY Evidence commit: `9c1c48917f5c85e1b0ac6815ebe7e4e9907f2bb3`
- Migration: forbidden
- Automatic rollback: forbidden
- Production: forbidden

This baseline is descriptive, not execution authority. Do not restore an old
baseline over current live state.
