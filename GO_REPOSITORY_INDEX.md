> **HISTORY** — 历史 / 取证材料，不是当前操作说明。
> **HISTORY** — historical / audit material, not current operating instructions.
>
> 当前入口：人（中文）[`README.md`](README.md) · AI（英文）[`AGENTS.md`](AGENTS.md)。
> Current entry points: [`README.md`](README.md) (Chinese, humans) and [`AGENTS.md`](AGENTS.md) (English, AI).
>
> 本文档不定义正常操作路径，不得作为当前操作依据。This document does not define the normal path; do not use it as current operating guidance.

---

# GO 候选归档索引

## 历史状态（本文件已降为 HISTORY；当前入口见仓库根 README.md / AGENTS.md）

HK-STAGING 自 2026-09-13 起运行 **DEPTH48 业务运行时**。本仓库**不再**发布运行时指针：
`docs/canonical-baseline/CURRENT_HK_RUNTIME.json` 已于 2026-10-08 退役（仓库里的声明文件无法
如实说明一台机器在跑什么，且它与现场发生过漂移）。运行身份以**最新一条签名 VERIFY Evidence**
为准（证据仓 `chenzhenxi1-sudo/go-control-evidence`）。

- 业务源码：`application/`；构建定义：`application/Dockerfile`（`docker build -t <tag> application/`）
- 运行 Compose：`deploy/hk-staging/docker-compose.business-runtime.yml`（8 个业务服务）
- 环境契约：`deploy/hk-staging/RUNTIME_ENV_CONTRACT.md`（仅键名，无值）
- **运行中**数据库 head：`0133_flight_change_plan`（PostgreSQL 18.4，551 表）
- 保护非目标：caddy、redis、PostgreSQL/RDS 业务数据、媒体卷、HK Agent、Executor、签名密钥、Task/Evidence/ledger、Control Plane、SSH

> 上表描述的是**运行中的** DEPTH48 运行时。repository 侧事实（canonical main SHA、`main:application` tree/文件数/源码指纹、**repository** migration head、gate/release 状态、open candidate PR）见
> [`docs/project/GO_CURRENT_STATE.md`](docs/project/GO_CURRENT_STATE.md) 与 [`docs/project/CONTEXT_CHECKPOINT.json`](docs/project/CONTEXT_CHECKPOINT.json)。
> 2026-09-14 刷新后：运行中 DB revision 仍为 `0133_flight_change_plan`，而 repository migration head 已是 `0134_flight_status_width`（尚未在 HK 执行）。两者不是同一个东西。

`CP11_DEPTH48_SOURCE_COMPOSITE_PARENT_20260913` 是**源码输入／装配件**，其内层镜像不是业务运行镜像。
`CP11_DEPTH46_CONSOLIDATED_PARENT_20260913` 与旧 R3.x 香港运行时均为**已被取代的历史运行时**。
`hk-staging/`（2026-09-11）是**历史快照**，不是当前运行定义。

历史候选：[DEPTH09 · 酒店建库准确性与复制复核](deliverables/CP11_DEPTH09_20260907/README.md)。

其前一历史冻结候选：[DEPTH08 · 14 单元持久执行与恢复](deliverables/CP11_DEPTH08_20260907/README.md)。

DEPTH09 在 DEPTH08 上增加酒店身份、明确官网房型关系采集、逐房型照片核对、可靠页面版本切换、
批次真实完成统计和管理写权限。更广一键建库流水线仍待完成。

FINAL_RELEASE_GATE=HOLD；HOTEL_REPLICATION_GATE=HOLD。以上均为工程复核归档。

## GO Command Center

2026-09-11 现役 Command Center 源码与运行配置归档：[`command-center/`](command-center/)。

该目录包含 Web Command Center 源码、现役 Boss Request Bridge 1.2.0、去敏配置、systemd/nginx 基线与源文件 SHA-256；不包含私钥、`.env` 实值、数据库、Token 或密码。

**Control Plane 与 Business Runtime 是两条不同轴线。** 本目录与 `control-plane/`、`hk-staging/source/{agent,executor}` 属于 Control Plane；业务运行时看 `application/` + `deploy/hk-staging/`。

## HK-STAGING

2026-09-11 现役 HK-STAGING 源码与运行配置归档：[`hk-staging/`](hk-staging/)。

该目录区分当前运行镜像中的真实源码与服务器 host-side build context，包含现役 HK Agent、Executor 及四个 runtime、Compose、systemd、Caddy、去敏配置与 SHA-256 基线。它是源码/配置归档，不是 Execution Authority。

> **该目录是上一代香港运行时的历史快照。** 业务运行时的当前定义在
> [`deploy/hk-staging/`](deploy/hk-staging/)；运行身份以最新一条签名 VERIFY Evidence 为准
> （本仓库不再发布运行时指针）。

Before any HK-STAGING deployment planning or execution, read
[`docs/control-plane/hk-staging/HK_STAGING_DEPLOY_RUNBOOK.md`](docs/control-plane/hk-staging/HK_STAGING_DEPLOY_RUNBOOK.md).
Do not reconstruct the deployment procedure from AI memory or prior chats.
