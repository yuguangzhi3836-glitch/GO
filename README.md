# GO

> Status refreshed 2026-09-12. This README is the repository entry point for current product lineage and operational-source boundaries. It is descriptive project context, not Execution Authority.

## Important: PR numbers are not DEPTH numbers

**PR #40 is not “DEPTH40”.** These are two different numbering systems and must not be treated as equivalent.

- **PR #40** (`archive: add canonical HK-STAGING source snapshot`) is an archive of the observed HK-STAGING runtime/source state. It is **not a new GO product version**.
- **DEPTH40** is a product-candidate generation in the application lineage. Its sealed P0.3 parent was validated separately and later received deployment-compatibility/package work.
- The newest active product work has now moved to **DEPTH41**, primarily through PR #47 and PR #48.

Do not infer product generation from a Pull Request number.

## Current product working baseline

The current unified development / repair / acceptance starting point is **DEPTH41 PR #47**:

- PR: [#47 · DEPTH41 unified parent](https://github.com/yuguangzhi3836-glitch/GO/pull/47)
- Branch: `fix/canonical-parent-retention-20260912`
- Parent package: `CP11_DEPTH41_UNIFIED_PARENT_V1_20260912`
- PR head / archive commit: `2d15536d2b65484e5a1c00067871387cefdfb235`
- Tested source/build commit: `62fdde3cabe72b92fa5dc1b37b7652395fe3aba5`
- Application Git tree: `a73b9b53a59c88ab995d0f9b123c9fb79e87e60d`
- Application file count: **1300**
- Source SHA-256 tree: `928468ed31550195dfa8f121832e91b8d08aa9d5c15cef1381d903f76c9f97b3`

PR #47 consolidates the latest DEPTH40 compatibility parent, retained valid DEPTH36R3 / DEPTH37 / DEPTH37R2 fixes, and the selected supplier-operations fix from PR #48 into one self-contained parent.

Verified on the tested source/build commit:

- Python: 1710 collected; **1704 passed**, 6 PostgreSQL tests skipped, 0 failed, 0 errors.
- Frontend: **244/244**.
- Deployment-compatibility regression: **34/34**.
- Isolated HTTP gate: 148 checks / 87 requests passed.
- Package restore, image/source identity, dependency binding, and archive reconstruction passed.
- Mobile type/basic contract/native-module linkage checks passed, but this is **not physical-device journey acceptance**.

### Current hold boundary

DEPTH41 is **not yet the final canonical/release source**.

PR #47 remains Draft and explicitly records `CANONICAL_SOURCE_RECOMMENDATION=REJECT` until the remaining acceptance gaps are closed. Outstanding items include hotel refund/final-ledger confirmation, supplier same-order reconciliation, the remaining vertical refund/final-money and three-end states, complete three-end UX, physical-device coverage, six PostgreSQL checks, Sealed Node coverage, and final release gates.

Therefore:

- `MERGE=NO`
- `DEPLOYMENT=NO`
- `PRODUCTION=HOLD`
- HK-STAGING currently running source is **not identical** to this DEPTH41 parent.

PR [#48 · DEPTH41 cross-end journey acceptance](https://github.com/yuguangzhi3836-glitch/GO/pull/48) remains a Draft acceptance/fix branch. Its selected result has been incorporated into PR #47, while its original evidence remains bound to its own tested commit and must not be promoted into a broader PASS claim.

## PR #40 and later: classification

| PR | Classification | Product-line meaning |
| --- | --- | --- |
| [#40](https://github.com/yuguangzhi3836-glitch/GO/pull/40) | HK-STAGING archive | **Not a product version.** Captures observed HK runtime/source/configuration. |
| [#41](https://github.com/yuguangzhi3836-glitch/GO/pull/41) | Governance / topology | Versioned deployment-topology and change-control proposal; not product-feature progression. |
| [#42](https://github.com/yuguangzhi3836-glitch/GO/pull/42) | DEPTH40 source consolidation | Materializes the DEPTH40 P0.3 application source directly under `application/`; an earlier consolidation candidate, not a new feature generation by itself. |
| [#43](https://github.com/yuguangzhi3836-glitch/GO/pull/43) | DEPTH40 deployment compatibility | Runtime/deployment compatibility and rollback-safety repair; business source identity remains DEPTH40. |
| [#44](https://github.com/yuguangzhi3836-glitch/GO/pull/44) | DEPTH40 packaging | Builds a self-contained DEPTH40 P0.3 compatibility-V2 parent. |
| [#45](https://github.com/yuguangzhi3836-glitch/GO/pull/45) | Artifact archive | Persists the verified DEPTH40 parent bytes/evidence; not product progression. |
| [#46](https://github.com/yuguangzhi3836-glitch/GO/pull/46) | Control Plane | Candidate-only `HK_STAGING_TEST_PR` chain; not application product progression. |
| [#47](https://github.com/yuguangzhi3836-glitch/GO/pull/47) | **DEPTH41 unified product parent** | **Current unified product working baseline**, still Draft/HOLD. |
| [#48](https://github.com/yuguangzhi3836-glitch/GO/pull/48) | DEPTH41 acceptance / product fix | Cross-end journey acceptance and business-depth repair; selected changes are folded into #47. |
| [#49](https://github.com/yuguangzhi3836-glitch/GO/pull/49) | Control-plane connection documentation | Workstation / Git / ECS access and identity recovery documentation; not application product progression. |

## `main` is not the latest product tree yet

The current `main` branch contains the merged operational archives and historical repository material, including PR #40. The newest DEPTH41 product parent is still on Draft PR #47 and has **not** been merged into `main`.

For product development/review, do not treat the old root `deliverables/CP11_DEPTH18_20260908` entry as the latest engineering result. DEPTH17/18 remain historical evidence only.

For current product work, begin with PR #47 and its `application/` tree, then verify the exact branch/SHA and current acceptance status before making changes.

## Historical deliverables

Historical DEPTH17/DEPTH18 restoration and evidence remain preserved under `deliverables/` and should not be deleted merely because the product lineage has advanced.

- [DEPTH17 archive](deliverables/CP11_DEPTH17_20260908/README.md)
- [DEPTH18 archive](deliverables/CP11_DEPTH18_20260908/README.md)

## GO Command Center source

The archived 2026-09-11 Command Center source and observed runtime configuration are under [`command-center/`](command-center/). This includes the unpacked web source and the exact installed Boss Request Bridge; private keys, runtime `.env` values, databases, and secrets are intentionally excluded.

Operational reference: [`docs/control-plane/command-center/README.md`](docs/control-plane/command-center/README.md).

## HK-STAGING source and operations

The observed 2026-09-11 HK-STAGING runtime source, Agent, Executor, Compose, systemd, Caddy configuration, sanitized configuration, and source/build identity evidence are archived under [`hk-staging/`](hk-staging/). This archive is descriptive evidence only and is not Execution Authority.

Before any HK-STAGING deployment, rollback, verification planning, execution, or Boss GPT/mobile control request, read [`docs/control-plane/hk-staging/README.md`](docs/control-plane/hk-staging/README.md) and the action-specific guidance it links.

Boss ChatGPT/Codex sessions that need to submit an HK-STAGING request should follow the linked **Boss GPT / mobile Request Channel** guide there. Do not reconstruct the control-plane procedure from AI memory or prior chats.
