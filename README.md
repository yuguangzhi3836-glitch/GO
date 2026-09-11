# GO

最新工程成果：[DEPTH18 · 媒体持久性与区域任务恢复](deliverables/CP11_DEPTH18_20260908/README.md)。

当前状态为 **HOLD**：完整回归 1370 项通过、6 项跳过，尚未全面完工或部署。代码、恢复脚本、母版对照与验收记录按版本保存，历史成果保留。

[累计 DEPTH17 源包与分卷](deliverables/CP11_DEPTH17_20260908/README.md) · [DEPTH18 审阅记录](deliverables/CP11_DEPTH18_20260908/GO_DEPTH18_REVIEW.md)

## GO Command Center source

The archived 2026-09-11 Command Center source and observed runtime configuration are under [`command-center/`](command-center/). This includes the unpacked web source and the exact installed Boss Request Bridge; private keys, runtime `.env` values, databases, and secrets are intentionally excluded.

Operational reference: [`docs/control-plane/command-center/README.md`](docs/control-plane/command-center/README.md).

## HK-STAGING source and operations

The observed 2026-09-11 HK-STAGING runtime source, Agent, Executor, Compose, systemd, Caddy configuration, sanitized configuration, and source/build identity evidence are archived under [`hk-staging/`](hk-staging/). This archive is descriptive evidence only and is not Execution Authority.

Before any HK-STAGING deployment, rollback, verification planning, execution,
or Boss GPT/mobile control request, read
[`docs/control-plane/hk-staging/README.md`](docs/control-plane/hk-staging/README.md)
and the action-specific guidance it links.

Boss ChatGPT/Codex sessions that need to submit an HK-STAGING request should
follow the linked **Boss GPT / mobile Request Channel** guide there. Do not
reconstruct the control-plane procedure from AI memory or prior chats.
