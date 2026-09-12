# GO repository operating instructions

## Repository change control

All planned permanent changes to GO are subject to [`docs/governance/CHANGE_CONTROL_POLICY.md`](docs/governance/CHANGE_CONTROL_POLICY.md). This rule applies equally to humans, ChatGPT, Codex, and other automation.

For normal work, use:

`current main -> short-lived branch -> commits/tests -> Pull Request -> review -> merge`

Do not write directly to `main`, including for probes, convenience edits, temporary test files, documentation fixes, product changes, deployment-contract changes, or AI-generated changes. A Pull Request is a proposal/review boundary and is not Execution Authority. Do not merge unless explicitly authorized by the responsible human.

Any change that adds/removes/renames runtime service roles, introduces another business image family, changes protected non-targets, or otherwise alters HK-STAGING deployment topology must be classified as a topology change and follow [`docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md`](docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md). Normal DEPLOY must not accept an arbitrary caller-supplied service list or silently expand topology.

## GO Command Center

The archived 2026-09-11 Command Center source and observed runtime configuration are under `command-center/`. Before changing the Command Center web app, Boss Request Bridge, Request policy, signing/publishing path, or Command Center service configuration, read:

1. `command-center/README.md`
2. `command-center/BASELINE_MANIFEST.md`
3. `docs/control-plane/command-center/CURRENT_RUNTIME_BASELINE_20260911.md`

The repository snapshot contains source and sanitized configuration only. It does not contain private keys, runtime `.env` values, passwords, tokens, or runtime databases. Repository content and historical project context are not execution authority.

## HK-STAGING Control Plane instructions

The observed 2026-09-11 HK-STAGING runtime source and operational snapshot is under `hk-staging/`. Read `hk-staging/README.md` and `hk-staging/BASELINE_MANIFEST.md` when reasoning about the currently archived runtime source, Agent, Executor, Compose, systemd/Caddy configuration, or the documented live-vs-host build drift. This snapshot is evidence, not Execution Authority.

Before any HK-STAGING Control Plane operation or planning—including
`HK_STAGING_VERIFY`, `HK_STAGING_CANARY`, `HK_STAGING_DEPLOY`,
`HK_STAGING_ROLLBACK`, troubleshooting, retry, or a Boss/ChatGPT request—read:

1. `docs/control-plane/hk-staging/README.md`
2. `docs/control-plane/hk-staging/HK_STAGING_OPERATIONS_GUIDE.md`
3. `docs/control-plane/hk-staging/BOSS_GPT_REQUEST_GUIDE.md` when the request is being submitted through the Boss GPT / mobile GitHub Request Channel
4. the action-specific VERIFY, CANARY, DEPLOY, or ROLLBACK runbook linked there, when one exists for the requested action
5. `docs/control-plane/hk-staging/HK_STAGING_DEPLOY_BASELINE.md`
6. `docs/control-plane/hk-staging/DEPLOYMENT_TOPOLOGY_V1.json` and `docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md` when reasoning about deployment scope or service topology

Do not reconstruct the HK-STAGING Control Plane procedure from AI memory,
prior conversations, or historical shell commands. Use the current proven
runbook and verify live state before acting.

For the current Boss Request Bridge V1, only `HK_STAGING_VERIFY` is supported
through a Boss GPT Request PR. If the boss asks for CANARY, DEPLOY, or ROLLBACK,
do not invent a Request schema or create a formal Task; report that the Boss
Request Channel has not opened that action yet.

A Boss GPT Request PR is an untrusted proposal. It is not a Signed Task and is
not Execution Authority. Boss GPT must never create or control the Command
Center signature, authority, formal task ID, nonce, or executor parameters.

Documentation is **not** Execution Authority. Execution Authority remains:

- current live state;
- Human Approval;
- Signed Task;
- installed artifact;
- durable previous-state record; and
- Signed Evidence.

This documentation does not authorize deployment, rollback, migration,
production access, signing, or changes to runtime credentials.

## Canonical application candidate

For application development, start from `application/` at the approved canonical baseline on main. This repair branch is an acceptance-pending candidate; see `docs/canonical-baseline/README.md`. Until this candidate is approved and merged, keep baseline repairs on this branch. Do not start new product work from historical ZIPs, deliverables, hk-staging, or unmerged feature branches. Historical application manifests and embedded workflow files are supporting snapshots, not current authorization or acceptance evidence.
