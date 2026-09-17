# Proven HK-STAGING baseline

This baseline describes verified state; it is **not** Execution Authority and
must never be restored over live state.

## Installed Control Plane identity

- Environment: `HK-STAGING-01`
- Agent: `0.5.7-rebuilt`, revision `R3-final-parser-audit-closure`
- Agent source commit: `616ed797bc077dc8b3b1b2d76219f7b2db729e58`
- Agent artifact SHA-256: `b47378ea811ba81e7e8a6ffbd97751541d9a3dca8b998f33a5e83c9566f2479c`
- Agent manifest SHA-256: `e07286d1053df06443c219017ffd017506d90660b20fb46bad979526e1bbc047`
- Installed Agent transport SHA-256: `4301a7e920fc25d98ea8403ac00ebbdb6a864bcb092d33caf343ad28603ff490`
- Executor: `0.4.3-rollback-runtime`, revision `R11-release-binding-schema-correction`
- Executor source commit: `79740475e3e6e6678b939525378e1a9ef1e2f28c`
- Executor artifact SHA-256: `4e29e83058713faf12e3f734d1e6207b738765cf4964d2eed64cd8e5247b5533`
- Executor manifest SHA-256: `8865af36ab6f13a2ac30b5c416d60a5f652640b49b240b26c2350ee36b3a0ae3`
- Installed Executor main SHA-256: `f0804521437a4d43db79aafd96928a15978f1d79393b1376be17b7a3907f37c0`
- Installed Executor collector SHA-256: `dff91265a5e3e80704277664f1952129ff19c6c7174d78e9b3e66125b9618ccc`
- Executor revision pin: `EXPECTED_REVISION=0133_flight_change_plan`, the DEPTH48 schema head

Installed 2026-09-16 by the controlled VERIFY baseline migration to DEPTH48
(`CC-CHANGE-20260916T0440Z-VERIFY-BASELINE-MIGRATION-DEPTH48`); the previous main
digest `323c30a7…` described the retired R3.1.5 runtime. Backups and the
before/after digests are in `/var/backups/HK-CHANGE-20260916T050020Z-verify-baseline-depth48/`
on HK-STAGING-01. This records what is installed, not a verification outcome.Both were replaced again on 2026-09-17 by the controlled canary-delivery change,
which gave the two production runners the calling convention the sealed-artifact
reader calls them through; that change's before/after digests and backup are in
its own change record. This records what is installed, not a verification outcome.

## Current approved/proven topology

- Topology ID: `HK_STAGING_BUSINESS_TOPOLOGY`
- Topology version: `1`
- Machine-readable description: `DEPLOYMENT_TOPOLOGY_V1.json`
- Current release model: one shared business image across eight business service roles.
- Installed Executor enforcement: fixed eight-service scope; dynamic topology loading is not implemented/proven.
- A topology mismatch is not a normal deployment. It requires a separately reviewed topology upgrade under `TOPOLOGY_CHANGE_POLICY.md`.
- The number eight is the current proven topology, not a permanent GO architectural limit.

## Fixed inputs and scope

- Compose path: `/home/go-stg/releases/r31-5-final-completion-20260906/GO_HYATT_DIRECT_BOOKING_R3_1_5_TEST_BOOTSTRAP_IDENTITY_FIX_20260906/deploy/docker-compose.r31-hk-staging.yml`
- Compose SHA-256: `7ef4ab181c1250d8cec0e348b29c24bfbb8e5dce4fc2a57f6faaa59363c26895`
- Runtime environment path: `/home/go-stg/control/r317-five-star-completeness-20260828/runtime.env`
- Runtime environment SHA-256: `6682ff61f336fb8ff95a6585e9133c88c52a4eaa440a7aea6a6e06f771e607fc`
- Exactly eight targets in topology V1: `api`, `recovery-worker`, `outbox-worker`,
  `mobile-push-receipt-worker`, `reconciliation-worker`, `mobile-push-worker`,
  `mobile-engagement-worker`, and `judgment-worker`.
- `redis` and `caddy` are protected non-targets in topology V1.
- Scoped deployment is `NOT_IMPLEMENTED` / `NOT_PROVEN`.

## HK Agent polling runtime

`go-hk-agent.timer` starts `go-hk-agent.service` with `OnBootSec=60s`,
`OnUnitActiveSec=60s`, and `Persistent=false`. The Agent outbound-pulls the
private GitHub Tasks repository. The nominal 60-second cadence is operational
behavior, not a strict SLA or Execution Authority.

## Final proven E2E chain

- DEPLOY: `go-boss02-final-deploy-20260911T025420Z`; Task commit
  `824768bb4613c80fef640f72b872f478dc032a90`; Evidence commit
  `87dfa03e777159a07e9a44627d4bfb4f6f9aae39`; DEPLOY_RECORD_V2 ID
  `452c36840f065f5448ed3f077e7830aee40b145504cd3d413a0339aef9a12b7f`,
  SHA-256 `b04cac062f7ec1243798499900473efa80a5b01467593f696db9d9d230af341a`.
- ROLLBACK: `go-boss02-final-rollback-20260911T071232Z`; Task commit
  `31d0a1ea17734c58461f4e5d855039e62d94db00`; Evidence commit
  `5d2838f0a3a829d7ea049f0c9813793b5c59fcf0`; rollback record
  ID `f6f7b64f63723f430e7bab1224abf93842d77ab45fe4f6697ef1bdd8b843131c`,
  SHA-256 `b0c0d78c5e78e1f73f4fc3acdaba7af504711486ef387359134b3ce249827fce`.
- Post-rollback VERIFY: `go-boss02-post-rollback-verify-20260911T071429Z`; Task commit
  `8d4b95dc63c6b502c265930f4cc083b2729df154`; Evidence commit
  `2dbbdefaf7996e5f9222669929eee79eefabae56`.

The final chain proved `ROLLBACK_OK`, Signed Rollback Evidence, and `VERIFY_OK`.
It recreated exactly eight topology-V1 targets; Redis and Caddy remained unchanged. No
Migration, Production action, automatic retry, or automatic recovery occurred.
