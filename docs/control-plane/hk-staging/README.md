# HK-STAGING deployment control plane

This directory records the proven HK-STAGING deployment path as of
2026-09-09. It is a descriptive recovery and operations reference, not an
execution authority.

The proven chain is:

`Human Approval → CANARY Evidence validation → fresh live drift preflight →
fresh signed task → private GitHub tasks repository → HK Agent → narrow
Executor → Signed Evidence → replay proof → fresh formal VERIFY`.

Read the [runbook](HK_STAGING_DEPLOY_RUNBOOK.md) before planning or
troubleshooting a deployment, and the [baseline](HK_STAGING_DEPLOY_BASELINE.md)
before comparing live state. The [operation contract](DEPLOY_OPERATION_CONTRACT.json)
is a machine-readable summary only.

The current live state is authoritative. Never restore an older documented
container ID, image reference, Compose file, or environment file over live
state merely because it appears in this documentation.
