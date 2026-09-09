# GO Command Center development authority

The user's explicit decision on 2026-09-09 is recorded in
`docs/governance/COMMAND_CENTER_AUTHORITY_20260909.md`.

All system development is owned by GO Command Center, including payment
providers/executors, business logic, frontend/native clients, migrations,
and deployment tooling code. Hong Kong is an operations role: it must not
develop a parallel payment system, patch source or runtime code, or independently
change the implementation. It may operate and configure approved artifacts only
within its existing, explicit task authority.

Any Hong Kong-side development already produced must be preserved and returned
with its source/diff/evidence for Command Center review. Do not delete it,
overwrite runtime with it, or automatically merge it. An existing deployment-time
plugin/delegate extension point is not authority to implement code in Hong Kong.

This user decision supersedes earlier conflicting divisions of development work.
It does not authorize merging, deployment, permission changes, new sources,
production access, or contacting other people.

# HK-STAGING Control Plane instructions

Before any `HK_STAGING_DEPLOY`, HK-STAGING deployment planning,
deployment troubleshooting, or deployment retry, read:

1. `docs/control-plane/hk-staging/README.md`
2. `docs/control-plane/hk-staging/HK_STAGING_DEPLOY_RUNBOOK.md`
3. `docs/control-plane/hk-staging/HK_STAGING_DEPLOY_BASELINE.md`

Do not reconstruct the HK-STAGING deployment procedure from AI memory,
prior conversations, or historical shell commands. Use the current proven
runbook and verify live state before acting.

Documentation is **not** Execution Authority. Execution Authority remains:

- current live state;
- Human Approval;
- Signed Task;
- installed artifact;
- durable previous-state record; and
- Signed Evidence.

This documentation does not authorize deployment, rollback, migration,
production access, signing, or changes to runtime credentials.
