# GO

> Status refreshed 2026-09-12. This README is the repository entry point for current product lineage, project operating context, and operational-source boundaries. It is descriptive project context, not Execution Authority.

## Project operating context

Before taking over GO work, read [`docs/project/OPERATING_CONTEXT.md`](docs/project/OPERATING_CONTEXT.md).

It defines the current human / AI / workstation responsibilities:

- **余总 / Boss** — product owner and final business-direction decision maker.
- **Boss GPT** — product exploration/development agent that creates candidate designs, branches, and PRs; its output is not automatically canonical or deployment-authorized.
- **陈震曦 / Eason** — technical operator, integrator, reviewer, and execution coordinator who connects product candidates to real Git, test, packaging, Control Plane, and HK-STAGING work.
- **Eason's ChatGPT** — technical coordination, context, review, and task-decomposition layer; not product owner or execution authority.
- **Codex / WorkBuddy** — local execution agents under Eason's control.
- **Eason-8845** — default Codex main execution workstation; direct SSH paths to HK-STAGING and Command Center are verified.
- **Eason-13490** (Windows hostname `EASON`) — default WorkBuddy / second development workstation; Alibaba Cloud Workbench CLI is the verified primary ECS path.

Both fixed workstations are operated by Eason. A workstation or AI agent does not independently own a branch, decide product direction, or gain deployment authority merely because it can execute commands.

Detailed connection identities and recovery paths are being maintained through PR #49 and its control-plane access runbook.

## Important: PR numbers are not DEPTH numbers

**PR #40 is not “DEPTH40”.** These are two different numbering systems and must not be treated as equivalent.

- **PR #40** (`archive: add canonical HK-STAGING source snapshot`) is an archive of the observed HK-STAGING runtime/source state. It is **not a new GO product version**.
- **DEPTH40** is a product-candidate generation in the application lineage. Its sealed P0.3 parent was validated separately and later received deployment-compatibility/package work.
- Product generations advanced through DEPTH45 source repairs and the DEPTH46 consolidated parent; PR47 is now merged. DEPTH47 repairs continue from that merged main.

Do not infer product generation from a Pull Request number.

## Current product working baseline — refreshed 2026-09-13

本轮源码集成记录为 [PR52](https://github.com/yuguangzhi3836-glitch/GO/pull/52)，已纳入 DEPTH47 额度期限、DEPTH48 酒店金额与多航段改签、PR53 独立资金审计。当前应用树为 `ad7d1de1190f86ad29d1c6cdafbcedd592e27206`，1323 文件。本地 1796 项后端通过／6 项 PostgreSQL 跳过、270 项前端通过；六模块同单三角色接口、刷新／重登及独立 SQL 通过。详见 [本轮修复和明确边界](docs/canonical-baseline/DEPTH48_ORDERED_REPAIRS.md)。完整三端可见页面、固定运行时 CI 及新父包仍待完成。下列 DEPTH46 身份只描述已生成的历史父包，不代表本轮源码已进入该 ZIP。

PR47 was merged as `1c9847c82725b888d239686572f1f44b6dafc2cc` after isolated checks. DEPTH46 is the current independently restorable parent. DEPTH47 source repairs continue from that main commit; see [current module work](docs/canonical-baseline/DEPTH47_MODULE_BOUNDARIES.md) for its separate source identity and evidence.

- DEPTH46 packaged application source: `a09a32e8cc6da10785e8bcf6be025013aec50931`.
- Application Git tree: `365b848d419ca5517b2cf711c271694bde346e33`; 1311 files.
- Source SHA256 tree: `0b2c140ae8edf532704b022d345da8892e7863947f4ff5b34e3a0a40a7000077`.
- Business rules: hotel date changes have zero change fee, a fixed 365-day period from original booking, higher-price differences payable and lower-price differences forfeited. Cancellation uses the accepted refund terms.
- Exact-source isolated CI 34703772217: 1751 Python passes and 6 PostgreSQL skips; 254 frontend, 34 compatibility and 148 HTTP checks; 53 browser scenarios with independent original-payment and hotel-change money audits.
- Current artifacts and unresolved scopes: [candidate](docs/canonical-baseline/CURRENT_CANDIDATE.json), [remaining work](docs/canonical-baseline/REMAINING_GAPS.md), [DEPTH46 build](packaging/depth46-consolidated-parent/README.md).

The new parent combines the unchanged DEPTH45 application with a rebuilt, source-bound image and an independently preserved PR51 deployment-entry supplement. The supplement remains disabled and uninstalled. Package build/restore and archive results are recorded separately from application CI. DEPTH46 package build and restore passed; its 314,723,816-byte ZIP has SHA256 `cc9b16be9555a2499db29a9ce0ebc25879fedd2953577bedc1f5e6e833451ce9`. All 16 archive parts were read back. Build run 34718705172 succeeded at the build step and failed later because the branch moved; independent archive run 34719241031 succeeded. [Parent identity](docs/canonical-baseline/CURRENT_PARENT.json) records these separately.

Full three-end UX, physical devices, PostgreSQL, complete Sealed Node and external provider/bank acceptance remain separate unfinished scopes. Source integration is not final release acceptance. Hong Kong and Production remain HOLD; their running source differs from this application candidate. PR48 is historical source/evidence and is not a parallel development baseline.

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
| [#47](https://github.com/yuguangzhi3836-glitch/GO/pull/47) | **DEPTH46 consolidated parent** | Merged at `1c9847c82725`; fixed application, rebuilt image, PR51 supplement and complete restore receipts. |
| [#48](https://github.com/yuguangzhi3836-glitch/GO/pull/48) | DEPTH41 acceptance / product fix | Cross-end journey acceptance and business-depth repair; selected changes are folded into #47. |
| [#49](https://github.com/yuguangzhi3836-glitch/GO/pull/49) | Control-plane connection documentation | Workstation / Git / ECS access and identity recovery documentation; not application product progression. |

## Source integration status

PR47 is merged at `1c9847c82725b888d239686572f1f44b6dafc2cc` under the user's explicit repository/CI/PR-merge authorization. New work starts from current main `application/`; PR48 remains historical. Earlier DEPTH17/18 and DEPTH40/41 packages remain historical artifacts with their own recorded source and runtime identities.

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
