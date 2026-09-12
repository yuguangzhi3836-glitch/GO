# GO 统一新父包

唯一开发待验起点：PR47 的 `application/`。新父包：**CP11_DEPTH41_UNIFIED_PARENT_V1_20260912**，包含完整统一源码、对应的新兼容镜像及审查资料。[父包下载与核验说明](packaging/depth41-unified-parent/README.md) · [逐文件对齐和验收缺口](docs/canonical-baseline/README.md)。PR48 保留为历史证据；最终验收、合入 main 与部署状态分别记录。

# GO

**唯一待验源码：PR47 的 application/**，已与 PR48 逐文件对齐。[来源选择、历史证据与剩余缺口](docs/canonical-baseline/README.md)。PR48 保留历史旅程记录；完整跨端验收仍 HOLD。

开发基线修复候选：[`application/`](application/)，从最新父包 `CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912` 保留并补齐有效历史修订。

**当前为候选，尚未完成全部验收，尚未合并或部署。** 状态、遗漏修复与统一开发流程见 [源码基线说明](docs/canonical-baseline/README.md)。历史 PASS 不代表本候选通过；HK-STAGING 运行快照不是这套开发源码。

历史工程成果：[DEPTH18 · 媒体持久性与区域任务恢复](deliverables/CP11_DEPTH18_20260908/README.md)。

该历史版本状态为 **HOLD**：完整回归 1370 项通过、6 项跳过，尚未全面完工或部署。代码、恢复脚本、母版对照与验收记录按版本保存，历史成果保留。

[累计 DEPTH17 源包与分卷](deliverables/CP11_DEPTH17_20260908/README.md) · [DEPTH18 审阅记录](deliverables/CP11_DEPTH18_20260908/GO_DEPTH18_REVIEW.md)

## Repository change control

All planned permanent changes to product behavior, source, tests, build logic, deployment topology/contracts, Control Plane components, infrastructure configuration, and operational documentation follow [`docs/governance/CHANGE_CONTROL_POLICY.md`](docs/governance/CHANGE_CONTROL_POLICY.md).

Normal workflow: `current main -> short-lived branch -> commits/tests -> Pull Request -> review -> merge`. Direct writes to `main` are prohibited for normal work, including AI-generated changes and probes. Pull Requests are review records, not Execution Authority.

## GO Command Center source

The archived 2026-09-11 Command Center source and observed runtime configuration are under [`command-center/`](command-center/). This includes the unpacked web source and the exact installed Boss Request Bridge; private keys, runtime `.env` values, databases, and secrets are intentionally excluded.

Operational reference: [`docs/control-plane/command-center/README.md`](docs/control-plane/command-center/README.md).

## HK-STAGING source and operations

The observed 2026-09-11 HK-STAGING runtime source, Agent, Executor, Compose, systemd, Caddy configuration, sanitized configuration, and source/build identity evidence are archived under [`hk-staging/`](hk-staging/). This archive is descriptive evidence only and is not Execution Authority.

The currently proven business deployment topology is versioned as `HK_STAGING_BUSINESS_TOPOLOGY` V1: one shared business image across eight business roles, with Redis and Caddy protected as non-targets. Eight is the current proven topology, not a permanent GO architectural limit. See [`docs/control-plane/hk-staging/DEPLOYMENT_TOPOLOGY_V1.json`](docs/control-plane/hk-staging/DEPLOYMENT_TOPOLOGY_V1.json) and [`docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md`](docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md).

Before any HK-STAGING deployment, rollback, verification planning, execution,
or Boss GPT/mobile control request, read
[`docs/control-plane/hk-staging/README.md`](docs/control-plane/hk-staging/README.md)
and the action-specific guidance it links.

Boss ChatGPT/Codex sessions that need to submit an HK-STAGING request should
follow the linked **Boss GPT / mobile Request Channel** guide there. Do not
reconstruct the control-plane procedure from AI memory or prior chats.
