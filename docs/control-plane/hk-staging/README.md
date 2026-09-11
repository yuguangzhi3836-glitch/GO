# HK-STAGING Control Plane operations

This directory is the descriptive operations entry point for the proven
HK-STAGING Control Plane as of 2026-09-11. It is not Execution Authority.

Read in this order before planning or executing an operation:

1. [Operations guide](HK_STAGING_OPERATIONS_GUIDE.md)
2. [Current baseline](HK_STAGING_DEPLOY_BASELINE.md)
3. The action-specific runbook: [DEPLOY](HK_STAGING_DEPLOY_RUNBOOK.md) or
   [ROLLBACK](HK_STAGING_ROLLBACK_RUNBOOK.md)
4. The matching machine-readable contract:
   [DEPLOY](DEPLOY_OPERATION_CONTRACT.json) or
   [ROLLBACK](ROLLBACK_OPERATION_CONTRACT.json)
5. [Troubleshooting](HK_STAGING_DEPLOY_TROUBLESHOOTING.md)

## Proven action chain

`Human Approval → Signed Task → HK Agent → narrow Executor → durable record
where applicable → read-only action or fixed-scope mutation → Signed Evidence
→ independent verification`

The formal action set proven on HK-STAGING is `VERIFY`, `CANARY`, `DEPLOY`,
and `ROLLBACK`. DEPLOY and ROLLBACK are fixed eight-service mutations;
VERIFY is read-only; CANARY is isolated from the business runtime.

Execution Authority remains the current live state, explicit Human Approval,
the fresh Signed Task, installed runtime bytes, durable records, and Signed
Evidence. Documentation, chat history, and an AI's memory never authorize an
operation.
