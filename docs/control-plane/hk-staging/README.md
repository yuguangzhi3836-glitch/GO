# HK-STAGING Control Plane operations

This directory is the descriptive operations entry point for the current proven
HK-STAGING Control Plane. It is not Execution Authority.

For the current Command Center architecture, read
[`../command-center/CURRENT_ARCHITECTURE.md`](../command-center/CURRENT_ARCHITECTURE.md)
first. The primary control path is GitHub-native: Request PR -> Command Center
validation/policy/signing -> Signed Task -> HK Agent -> narrow Executor ->
Signed Evidence.

The observed 2026-09-11 HK-STAGING source/configuration snapshot is archived at
[`../../../hk-staging/`](../../../hk-staging/). That directory is historical
evidence/source reference. It must not be treated as the current business
runtime definition or as a complete current capability inventory.

Read in this order before planning or executing an operation:

1. [Current Command Center architecture](../command-center/CURRENT_ARCHITECTURE.md)
2. [Operations guide](HK_STAGING_OPERATIONS_GUIDE.md)
3. [Boss GPT / mobile Request Channel](BOSS_GPT_REQUEST_GUIDE.md) when the request is being initiated from ChatGPT through GitHub
4. [Current baseline](HK_STAGING_DEPLOY_BASELINE.md)
5. [Current deployment topology V1](DEPLOYMENT_TOPOLOGY_V1.json) and [topology change policy](TOPOLOGY_CHANGE_POLICY.md) when reasoning about runtime service scope
6. The action-specific runbook: [DEPLOY](HK_STAGING_DEPLOY_RUNBOOK.md) or
   [ROLLBACK](HK_STAGING_ROLLBACK_RUNBOOK.md)
7. The matching machine-readable contract:
   [DEPLOY](DEPLOY_OPERATION_CONTRACT.json) or
   [ROLLBACK](ROLLBACK_OPERATION_CONTRACT.json)
8. [Troubleshooting](HK_STAGING_DEPLOY_TROUBLESHOOTING.md)

Repository changes are governed by [`../../governance/CHANGE_CONTROL_POLICY.md`](../../governance/CHANGE_CONTROL_POLICY.md): planned permanent changes use a short-lived branch and Pull Request; normal work must not write directly to `main`.

## Boss GPT / Mobile Request Channel

Boss GPT submits an **untrusted Request PR** to
`chenzhenxi1-sudo/go-control-tasks`. Command Center alone validates that
request, derives the formal Task, and signs it with the existing Command Center
signer. Boss GPT does not create a Signed Task and does not merge the Request PR.

Current confirmed Boss Request classification:

- `HK_STAGING_VERIFY` — **SUPPORTED / PROVEN**.
- `HK_STAGING_TEST_PR` — **SUPPORTED / PROVEN**. PR #50 recorded live install,
  successful E2E, and an independent blind retest.
- `HK_STAGING_DEPLOY` — capability is **INSTALLED but DISABLED / FAIL-CLOSED**.
  PR #57 records `deployment_requests_enabled=false`; capability presence is not
  deployment authorization.
- `HK_STAGING_CANARY` — **REQUESTABLE** since channel revision
  `1.6.0-canary-channel`. The Request carries the five common fields and nothing
  else; the candidate image, its sealed package and the expected current image come
  from the Command Center's root-owned canary authority file. It mutates no business
  runtime, so it needs no plan and no switch, and a plan cannot be registered
  without a canary for the same candidate.
- ROLLBACK — no current Boss Request schema should be invented merely because the
  underlying Control Plane has that operation path.

See [BOSS_GPT_REQUEST_GUIDE.md](BOSS_GPT_REQUEST_GUIDE.md) for the exact current
VERIFY and TEST_PR request schemas and boundaries.

## Proven action chain

`Human Approval -> Signed Task -> HK Agent -> narrow Executor -> durable record
where applicable -> read-only action or fixed-scope mutation -> Signed Evidence
-> independent verification`

The underlying formal HK-STAGING action set includes proven VERIFY, CANARY,
DEPLOY, and ROLLBACK paths. This underlying action set is distinct from which
actions are currently exposed through the Boss GPT Request Channel.

The current approved/proven business topology is
`HK_STAGING_BUSINESS_TOPOLOGY` version `1`: one shared business image across
exactly eight business service roles, with `redis` and `caddy` as protected
non-targets. The installed Executor still enforces that fixed eight-service
scope. This is the current proven topology, not a permanent architectural limit
for GO.

A candidate that requires a different service topology must not be routed
through ordinary DEPLOY. It requires a separately reviewed topology version
upgrade under [TOPOLOGY_CHANGE_POLICY.md](TOPOLOGY_CHANGE_POLICY.md). Callers
must never supply an arbitrary expanded service list.

VERIFY is read-only; TEST_PR uses isolated source-bound validation and does not
deploy the application. CANARY is isolated from the business runtime.

Execution Authority remains the current live state, explicit Human Approval,
the fresh Signed Task, installed runtime bytes, durable records, and Signed
Evidence. Documentation, chat history, a Request PR, and an AI's memory never
authorize an operation.
