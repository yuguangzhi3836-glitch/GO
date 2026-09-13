# GO repository operating instructions

## Read project operating context first

Before taking over GO work, read:

1. `README.md`
2. `docs/project/OPERATING_CONTEXT.md`

Treat these as the current project-context entry point before reasoning about who owns product direction, who reviews/integrates work, which AI/agent is acting, or which workstation should execute a task.

### Human / AI responsibility model

- **余总 / Boss** is the product owner and final business-direction decision maker.
- **Boss GPT** is a product exploration/development agent. Its branches and PRs are candidates, not automatically canonical and not Execution Authority.
- **陈震曦 / Eason** is the technical operator, integrator, reviewer, and execution coordinator. He decides which workstation/agent receives a task and is responsible for connecting product candidates to real Git/test/package/control-plane/runtime work.
- **Eason's ChatGPT** is a coordination, context, review, and task-decomposition layer. It is not product owner and is not deployment authority.
- **Codex and WorkBuddy** are execution agents under Eason's control. Command execution capability does not grant deployment or Production authority.

### Fixed workstation convention

- **Eason-8845**: default **Codex main execution workstation**. Use it for local mainline/source work, testing, Git, and tasks that benefit from its verified direct SSH paths to HK-STAGING and GO Command Center.
- **Eason-13490** (observed Windows hostname `EASON`): default **WorkBuddy / second development workstation**. Its verified primary ECS path is Alibaba Cloud Workbench CLI; direct SSH is secondary/non-primary.
- Both workstations are operated by Eason. A branch is not owned by a workstation merely because it was created there.
- Before continuing work on either workstation, verify repository, branch, HEAD, working-tree state, and remote state. Never assume uncommitted state from the other workstation exists locally.

Detailed workstation connection identities and recovery commands are maintained through PR #49 and `docs/control-plane/access/CONNECTION_AND_IDENTITY_RUNBOOK.md` when that documentation is being used/reviewed.

### Product-lineage rule

Do not infer product generation from Pull Request number. In particular:

- PR #40 is an HK-STAGING archive, **not DEPTH40**.
- Current source work is DEPTH48, integrated through PR52; DEPTH46 remains the latest complete self-contained parent. Check current main and the live PR state before continuing.
- Newer PR or higher DEPTH number does not automatically mean canonical. Check lineage, retained fixes, tests, acceptance evidence, deployment compatibility, and explicit HOLD/PASS boundaries.

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

## Repository change control

All planned permanent changes to GO are subject to [`docs/governance/CHANGE_CONTROL_POLICY.md`](docs/governance/CHANGE_CONTROL_POLICY.md). This rule applies equally to humans, ChatGPT, Codex, and other automation.

For normal work, use:

`current main -> short-lived branch -> commits/tests -> Pull Request -> review -> merge`

Do not write directly to `main`, including for probes, convenience edits, temporary test files, documentation fixes, product changes, deployment-contract changes, or AI-generated changes. A Pull Request is a proposal/review boundary and is not Execution Authority. Do not merge unless explicitly authorized by the responsible human.

Any change that adds/removes/renames runtime service roles, introduces another business image family, changes protected non-targets, or otherwise alters HK-STAGING deployment topology must be classified as a topology change and follow [`docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md`](docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md). Normal DEPLOY must not accept an arbitrary caller-supplied service list or silently expand topology.


## Unified application source

PR52 merged DEPTH47/DEPTH48 source repairs at `9a056e255374d4254208d519462e7cd5b693a78f`; PR53 ledger checks were included. The application tree is `ad7d1de1190f86ad29d1c6cdafbcedd592e27206`. See `docs/canonical-baseline/DEPTH48_ORDERED_REPAIRS.md`. DEPTH46 remains the latest complete parent; visible three-end acceptance, PostgreSQL, frozen-runtime CI and a new self-contained parent remain unfinished. On 2026-09-13 the user explicitly authorized uploading the new parent, source, workflows and subsequent fixes to this repository, running isolated CI, and merging the PR. Perform the source review, exact-source validation and conflict resolution before merging. This source-merge authorization does not authorize installation or Hong Kong/Production deployment. After merge, start subsequent work from application/ on current main using short-lived branches and reviewable PRs. Historical evidence remains bound to its original commit and scope.
