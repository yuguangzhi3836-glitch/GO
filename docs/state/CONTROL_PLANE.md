# CONTROL PLANE — CURRENT STATE

Baseline: `main@286e294d92df4b7d1c0073116a8e628734abec6c`

## CURRENT MAIN FACTS

- Control Plane and Business Runtime are separate GO axes.
- Control Plane-related repository areas include `command-center/`, `control-plane/` and HK Agent/Executor material.
- Business runtime source is `application/`; active HK business-runtime definition is under `deploy/hk-staging/`.
- Current operational procedures must be read from the current runbooks identified by `AGENTS.md`; they must not be reconstructed from old chats or historical shell commands.
- Documentation, repository access or the ability to execute commands does not itself grant deployment/runtime authority.

## CURRENT OPERATING BOUNDARY

Before HK-STAGING Control Plane operations or planning, follow the current repository runbook chain under:

- `docs/control-plane/hk-staging/`

For Command Center work, use the current Command Center baseline/runbook sources identified by `AGENTS.md`.

## ACTIVE CANDIDATES

- PR #49 is an open Draft control-plane connection/identity documentation candidate at this context baseline.
- Other open governance/control-plane PRs may exist; their higher PR number does not make them canonical.

## UNKNOWN / HOLD / BLOCKERS

- An open control-plane PR is not installed runtime authority.
- Historical `hk-staging/` business source snapshot must not be used to infer the active business runtime.
- Production remains a separate scope and is not authorized by this state card.

## EVIDENCE / ENTRYPOINTS

- `AGENTS.md`
- `GO_REPOSITORY_INDEX.md`
- `docs/project/OPERATING_CONTEXT.md`
- `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`
- `docs/control-plane/hk-staging/README.md`
- `docs/control-plane/hk-staging/HK_STAGING_OPERATIONS_GUIDE.md`
- `command-center/`
- `control-plane/`

CONTROL_PLANE_STATE_STATUS=V1_CANDIDATE
