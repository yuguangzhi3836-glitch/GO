# HK-STAGING Control Plane operations

This directory is the descriptive operations entry point for the proven
HK-STAGING Control Plane as of 2026-09-11. It is not Execution Authority.

The observed 2026-09-11 HK-STAGING source/configuration snapshot is archived at
[`../../../hk-staging/`](../../../hk-staging/). That archive contains the source recovered from the currently running business image, the current HK Agent and Executor, Compose, systemd/Caddy configuration, sanitized configuration, SHA-256 manifests, and the documented one-file live-vs-host build-context drift. It is evidence and a source reference, not authority to execute.

Read in this order before planning or executing an operation:

1. [Operations guide](HK_STAGING_OPERATIONS_GUIDE.md)
2. [Boss GPT / mobile Request Channel](BOSS_GPT_REQUEST_GUIDE.md) when the request is being initiated from the boss's ChatGPT through GitHub
3. [Current baseline](HK_STAGING_DEPLOY_BASELINE.md)
4. [Current deployment topology V1](DEPLOYMENT_TOPOLOGY_V1.json) and [topology change policy](TOPOLOGY_CHANGE_POLICY.md) when reasoning about runtime service scope
5. The action-specific runbook: [DEPLOY](HK_STAGING_DEPLOY_RUNBOOK.md) or
   [ROLLBACK](HK_STAGING_ROLLBACK_RUNBOOK.md)
6. The matching machine-readable contract:
   [DEPLOY](DEPLOY_OPERATION_CONTRACT.json) or
   [ROLLBACK](ROLLBACK_OPERATION_CONTRACT.json)
7. [Troubleshooting](HK_STAGING_DEPLOY_TROUBLESHOOTING.md)

Repository changes are governed by [`../../governance/CHANGE_CONTROL_POLICY.md`](../../governance/CHANGE_CONTROL_POLICY.md): planned permanent changes use a short-lived branch and Pull Request; normal work must not write directly to `main`.

## Boss GPT / Mobile Request Channel

Boss GPT submits an **untrusted Request PR** to
`chenzhenxi1-sudo/go-control-tasks`. Command Center alone validates that
request, derives the formal Task, and signs it with the existing Command Center
signer. The Boss GPT does not create a Signed Task and does not need to merge
the Request PR.

Current Boss Request Bridge V1 supports only `HK_STAGING_VERIFY` for
`HK-STAGING-01`. The underlying Control Plane has proven VERIFY, CANARY, DEPLOY,
and ROLLBACK, but Boss Request V1 has not yet opened CANARY, DEPLOY, or ROLLBACK.
See [BOSS_GPT_REQUEST_GUIDE.md](BOSS_GPT_REQUEST_GUIDE.md) for the exact current
request workflow and schema.

## Proven action chain

`Human Approval -> Signed Task -> HK Agent -> narrow Executor -> durable record
where applicable -> read-only action or fixed-scope mutation -> Signed Evidence
-> independent verification`

The formal action set proven on HK-STAGING is `VERIFY`, `CANARY`, `DEPLOY`,
and `ROLLBACK`. The current approved/proven business topology is
`HK_STAGING_BUSINESS_TOPOLOGY` version `1`: one shared business image across
exactly eight business service roles, with `redis` and `caddy` as protected
non-targets. The installed Executor still enforces that fixed eight-service
scope. This is the current proven topology, not a permanent architectural limit
for GO.

A candidate that requires a different service topology must not be routed
through ordinary DEPLOY. It requires a separately reviewed topology version
upgrade under [TOPOLOGY_CHANGE_POLICY.md](TOPOLOGY_CHANGE_POLICY.md). Callers
must never supply an arbitrary expanded service list.

VERIFY is read-only; CANARY is isolated from the business runtime.

Execution Authority remains the current live state, explicit Human Approval,
the fresh Signed Task, installed runtime bytes, durable records, and Signed
Evidence. Documentation, chat history, a Request PR, and an AI's memory never
authorize an operation.
