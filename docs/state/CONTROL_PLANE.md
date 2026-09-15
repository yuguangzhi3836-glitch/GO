# CONTROL PLANE — CURRENT STATE

Baseline: `main@8ffcde66d36c1bbf849218529ef015f6e81725af` (refreshed 2026-09-14; previous baseline `286e294d`)

Truth classes: `CURRENT_MAIN_FACT` · `ACTIVE_CANDIDATE` · `UNKNOWN / HOLD / BLOCKERS` · `EVIDENCE / ENTRYPOINTS`

## CURRENT MAIN FACTS

- Control Plane and Business Runtime are separate GO axes.
- Control Plane-related repository areas include `command-center/`, `control-plane/` and the `hk-staging/source/{agent,executor}` material.
- Business runtime source is `application/`; the active business-runtime definition is under `deploy/hk-staging/`.
- Current operational procedures must be read from the current runbooks under `docs/control-plane/hk-staging/`; they must not be reconstructed from old chats or historical shell commands.
- HK deploy capability closeout is recorded in the repository: `docs/control-plane/PR51_DEPLOY_CAPABILITY_CLOSEOUT_20260913.md`.
- Documentation, repository access, or the ability to execute commands does not itself grant deployment/runtime authority.
- The presence of Control Plane code in a merged PR does **not** mean the corresponding capability is installed on any host. Installed state must be read from the live host, not from Git.

## CURRENT OPERATING BOUNDARY

Before HK-STAGING Control Plane operations or planning, follow the current repository runbook chain under:

- `docs/control-plane/hk-staging/README.md`
- `docs/control-plane/hk-staging/HK_STAGING_OPERATIONS_GUIDE.md`
- `docs/control-plane/hk-staging/HK_STAGING_DEPLOY_RUNBOOK.md`
- `docs/control-plane/hk-staging/HK_STAGING_ROLLBACK_RUNBOOK.md`

For Command Center work, use the current Command Center sources identified by `AGENTS.md` and `docs/control-plane/command-center/README.md`.

## ACTIVE CANDIDATES

- PR #49 is a **closed, unmerged** control-plane connection/identity documentation candidate. The runbook it proposes (`docs/control-plane/access/CONNECTION_AND_IDENTITY_RUNBOOK.md`) is **not present** on canonical main and must not be quoted as repository fact. The current access-channel state is recorded in `docs/project/OPERATING_CONTEXT.md` (section "服务器访问通道").
- PR #78, #89, #90 and #91 are open Draft operations/evidence candidates (`ASSIGNED_NO_ACK` dispatch, pointer rebind, runner canary, R3 worker ACK). Their internal claims are candidates.
- Other open governance/control-plane PRs exist; a higher PR number does not make them canonical.

## UNKNOWN / HOLD / BLOCKERS

- An open control-plane PR is not installed runtime authority.
- Historical `hk-staging/` business source snapshot (2026-09-11) must not be used to infer the active business runtime.
- Production remains a separate scope and is not authorized by this state card; `PRODUCTION` is `HOLD` on canonical main.
- The Control Plane's live configuration state is a live-host fact. Local audit notes about a specific host are **not** repository evidence and are not recorded here.
- Gate runs on canonical main record `hong_kong: NOT_ACCESSED` — no Control Plane acceptance run has touched HK.

## EVIDENCE / ENTRYPOINTS

- `AGENTS.md`
- `GO_REPOSITORY_INDEX.md`
- `docs/project/OPERATING_CONTEXT.md`
- `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`
- `docs/control-plane/PR51_DEPLOY_CAPABILITY_CLOSEOUT_20260913.md`
- `docs/control-plane/hk-staging/README.md`
- `docs/control-plane/hk-staging/HK_STAGING_OPERATIONS_GUIDE.md`
- `docs/control-plane/command-center/README.md`
- `command-center/`
- `control-plane/`

CONTROL_PLANE_STATE_STATUS=REFRESHED_AT_MAIN_8ffcde66
