# GO repository operating instructions

## Current active runtime — read this before reasoning about HK-STAGING

HK-STAGING runs the **DEPTH48 business runtime** since 2026-09-13. The single
machine-readable pointer is `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`.

Answer these from that file plus `deploy/hk-staging/README.md`, not from PR
numbers, historical parents, or prior chat context:

1. Business source: `application/`
2. Active HK runtime generation: DEPTH48
3. Build definition: `application/Dockerfile` (`docker build -t <tag> application/`)
4. Compose: `deploy/hk-staging/docker-compose.business-runtime.yml`
5. Database head: `0133_flight_change_plan` (PostgreSQL 18.4)
6. Business services (8): `api`, `outbox-worker`, `recovery-worker`,
   `reconciliation-worker`, `judgment-worker`, `mobile-engagement-worker`,
   `mobile-push-worker`, `mobile-push-receipt-worker`
7. Protected non-targets: `caddy`, `redis`, PostgreSQL/RDS business data, media
   volumes, HK Agent, Executor, signing keys, Task/Evidence/ledger, Control
   Plane authority data, SSH access, Production
8. Build: see `deploy/hk-staging/README.md`
9. Smoke: `curl -fsS http://127.0.0.1:8000/health`, worker entrypoints, `alembic heads`
10. Superseded: DEPTH46 parent, old R3.x HK runtime, `hk-staging/` 2026-09-11
    snapshot, and the `CP11_DEPTH48_SOURCE_COMPOSITE_PARENT_20260913` image
    (source input only, not a runnable business image)
11. `deliverables/` and `evidence/` are historical evidence bound to their
    original commit — not current authority
12. **Control Plane and Business Runtime are two different axes.** Control Plane:
    `command-center/`, `control-plane/`, `hk-staging/source/{agent,executor}`.
    Business runtime: `application/` + `deploy/hk-staging/`.

## Read project operating context first

Before taking over GO work, read:

1. `README.md`
2. `docs/project/OPERATING_CONTEXT.md`
3. `docs/project/GO_CURRENT_STATE.md`
4. `docs/project/ACTIVE_DECISIONS.md`
5. the relevant module state file under `docs/state/`
6. `docs/project/CONTEXT_CHECKPOINT.json`
7. `docs/project/CONTEXT_HANDOFF_PROTOCOL.md` when synchronizing or handing off project context

Treat these as the current project-context entry point before reasoning about who owns product direction, who reviews/integrates work, which AI/agent is acting, which workstation should execute a task, or what the project currently believes to be true.

**Do not synchronize GO by replaying every historical Pull Request by default.** Use the current-state layer plus the context checkpoint, then inspect changes after the checkpoint. Older PRs remain available for audit, provenance, conflict investigation, rollback/lineage questions, or an explicit historical request.

An open PR/branch is a candidate and must not be silently promoted into current project truth merely because it is newer or contains more code.

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
- Current source work is DEPTH48, integrated through PR52. DEPTH48 is now also the **active HK-STAGING business runtime**; its runtime definition is `application/Dockerfile` + `deploy/hk-staging/`. DEPTH46 is a **superseded historical** parent, not the current runtime. Check `docs/canonical-baseline/CURRENT_HK_RUNTIME.json` for live runtime state.
- Newer PR or higher DEPTH number does not automatically mean canonical. Check lineage, retained fixes, tests, acceptance evidence, deployment compatibility, and explicit HOLD/PASS boundaries.

## GO Command Center

The archived 2026-09-11 Command Center source and observed runtime configuration are under `command-center/`. Before changing the Command Center web app, Boss Request Bridge, Request policy, signing/publishing path, or Command Center service configuration, read:

1. `command-center/README.md`
2. `command-center/BASELINE_MANIFEST.md`
3. `docs/control-plane/command-center/CURRENT_RUNTIME_BASELINE_20260911.md`

The repository snapshot contains source and sanitized configuration only. It does not contain private keys, runtime `.env` values, passwords, tokens, or runtime databases. Repository content and historical project context are not execution authority.

## HK-STAGING Control Plane instructions

The observed 2026-09-11 HK-STAGING runtime source and operational snapshot is under `hk-staging/`. Read `hk-staging/README.md` and `hk-staging/BASELINE_MANIFEST.md` when reasoning about the currently archived runtime source, Agent, Executor, Compose, systemd/Caddy configuration, or the documented live-vs-host build drift. This snapshot is evidence, not Execution Authority.

`hk-staging/` is a **historical snapshot of the previous HK runtime generation**. The **active** business runtime definition is `application/Dockerfile` + `deploy/hk-staging/docker-compose.business-runtime.yml`; see `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`. Do not read the current business image, business source, or business service set from `hk-staging/`.

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