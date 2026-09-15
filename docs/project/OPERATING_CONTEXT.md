# GO 项目角色与工作环境背景

> 更新时间：2026-09-12
>
> 本文用于帮助新的 ChatGPT / Codex / WorkBuddy 会话快速理解 GO 项目中“谁负责什么、谁可以做什么、两台工作站如何分工”。它是项目背景与协作约定，不是 Execution Authority，也不能替代实时状态、Human Approval、Signed Task、已安装产物、durable previous-state 或 Signed Evidence。

## 1. 人员角色

### 余总 / Boss

余总是 GO 的业务发起者、产品方向负责人和最终业务决策者。

主要职责：

- 决定 GO 要解决什么问题、产品往什么方向发展；
- 提出新的产品能力、业务规则和优先级；
- 使用自己的 ChatGPT / GPT 会话推进产品设计、代码候选和 PR；
- 对重大产品方向和最终业务取舍做决定。

重要边界：

- Boss 的决定代表产品意图，但并不自动等于某个分支、PR、镜像或部署已经通过技术验收；
- Boss GPT 创建的分支/PR仍然需要经过 lineage、测试、验收、兼容性和变更控制检查；
- Boss / Boss GPT 不因为“提出了需求或生成了代码”而自动拥有 HK-STAGING 或 Production 的执行权限。

### 陈震曦 / Eason

陈震曦是 GO 当前的技术执行、集成、审核和运行协调负责人。

主要职责：

- 把 Boss 的产品方向转成可执行的技术任务；
- 维护 GO 在 GitHub、两台本地工作站、Codex、WorkBuddy、Command Center、HK-STAGING 等环境之间的技术连续性；
- 审核 Boss GPT 或其他 AI 生成的分支/PR，确认它们是否真的延续了正确的产品 lineage；
- 处理本地 Git、开发环境、测试、打包、回归、部署准备、控制面、证据和故障排查；
- 决定一个任务交给哪台电脑、哪个 AI/Agent 执行；
- 在需要 Human Approval 的操作中承担实际的人类确认角色。

在 GO 项目中，Eason 不是单纯的“转发命令的人”，而是负责把产品开发结果和真实运行环境安全接起来的人。

## 2. AI / Agent 角色

### Eason 的 ChatGPT（本会话这一类角色）

主要定位：**技术协调、上下文保持、审核、任务拆解和决策辅助层**。

主要职责：

- 维护 GO 的项目背景和当前状态；
- 阅读 GitHub，区分产品开发、归档、基础设施、控制面和验收工作；
- 审核新 PR / 分支是否真的比现有产品基线更新；
- 发现 README、Runbook、项目索引等文档是否已经过时；
- 把 Eason 的意图整理成边界清楚的 Codex / WorkBuddy 工单；
- 协助分析代码、架构、测试、部署准备和故障；
- 在涉及 HK-STAGING / Command Center 时，要求重新读取当前 Runbook，而不是凭旧聊天记忆重构流程。

重要边界：

- 这个 ChatGPT 不是 GO 的产品 Owner；
- 不应该自行改变 Boss 的产品方向；
- 不应该因为“看到了更新的 PR”就自动把它当成 canonical；
- 不应该绕过 Human Approval、Signed Task、安装产物和 Signed Evidence 的控制面边界。

### Boss GPT

主要定位：**产品探索和产品开发 Agent**。

它主要帮助余总：

- 把业务想法快速变成产品设计和代码；
- 推进新的产品能力；
- 创建候选分支 / PR；
- 对产品缺口进行连续开发和修补。

重要边界：

- Boss GPT 的强项是推进产品，不是判断真实运行环境；
- 新创建的 PR 不一定天然优于较早但已独立验收的候选；
- 它不能因为 PR 编号更大、创建时间更新，就覆盖掉已经验证过的修复；
- 它生成的代码/PR属于 candidate，仍需 Eason 侧进行技术整合、回归、验收和运行边界检查。

### Codex

主要定位：**本地代码与技术执行 Agent**。

典型任务：

- 阅读和修改本地 GO 源码；
- Git 分支、提交、测试、打包；
- 根据明确工单进行修复和回归；
- 在获得明确授权且符合 Runbook 时执行受控的服务器/控制面操作。

Codex 能执行命令不代表它自动拥有部署权限。

### WorkBuddy

主要定位：**另一套本地开发/执行 Agent，与 Codex 并行使用**。

典型任务：

- 接管本地 GO 工作区；
- 使用配置的模型（当前计划可使用 DeepSeek V4 API）进行代码理解、修改、测试和 Git 工作；
- 作为 Eason 的另一套开发执行环境，降低对单一 Codex 会话/额度/环境的依赖。

WorkBuddy 同样受 Git 状态、项目文档、Runbook 和人工授权约束。

## 3. 两台固定工作站的归属与默认分工

两台电脑**都归陈震曦/Eason 管理**。AI/Agent 只是被分配在这些电脑上工作的执行工具，不拥有机器本身，也不独立决定任务方向。

### Eason-8845

默认角色：**Codex 主执行工作站**。

当前约定：

- 主要交给 Codex 做 GO 主线代码、修复、测试、Git 和需要较强本地执行能力的任务；
- Eason 说“让 8845 干”时，通常表示把这个任务交给这台机器上的 Codex / 本地执行环境；
- 对 HK-STAGING 和 GO Command Center 已验证存在直接 SSH 操作路径；
- 适合需要直接服务器诊断、主线修复或本地 Codex 长任务的工作。

### Eason-13490

逻辑工作站 ID：`Eason-13490`；当前观察到的 Windows 主机名：`EASON`。

默认角色：**WorkBuddy 主执行工作站 / 第二开发工作站**。

当前约定：

- WorkBuddy 的恢复与长期工作环境优先放在这台机器；
- 也可以运行 Codex 或其他本地工具，但 WorkBuddy 是当前计划中的主要开发 Agent；
- 对 GitHub 使用本地 HTTPS Git；
- 对 HK-STAGING 和 GO Command Center，已验证的主要 ECS 通道是 Alibaba Cloud Workbench CLI；
- direct SSH 在这台机器上属于次要诊断通道，不需要为了和 8845 对称而强行重建。

更详细的连接方式、身份、恢复命令和已验证状态请看：

- PR #49
- `docs/control-plane/access/CONNECTION_AND_IDENTITY_RUNBOOK.md`（PR #49 当前候选文档）

## 4. 默认任务流

```text
余总 / Boss
    |
    | 产品方向、业务需求、优先级
    v
Boss GPT
    |
    | 产品设计 / candidate code / candidate PR
    v
GitHub candidate branches / PRs
    |
    | 审核、lineage 对齐、验收、运行边界
    v
陈震曦 / Eason + Eason 的 ChatGPT
    |
    | 拆成明确执行任务
    +-------------------------+
    |                         |
    v                         v
Eason-8845                Eason-13490
Codex 主执行              WorkBuddy 主执行
    |                         |
    +-----------+-------------+
                |
                v
        测试 / Git / 打包 / 审核
                |
                v
      Control Plane / HK-STAGING
      （仅在当前 Runbook 和授权允许时）
```

## 5. 新 AI 会话必须理解的几条原则

1. **产品方向由 Boss 决定，技术整合和执行协调由 Eason 负责。**
2. **Boss GPT 是产品开发 Agent，不是运行环境权威。**
3. **Eason 的 ChatGPT 是协调/审核层，不应自行成为产品 Owner 或部署 authority。**
4. **Codex 和 WorkBuddy 是执行 Agent，不是决策 Owner。**
5. **Eason-8845 默认归 Codex 主执行；Eason-13490 默认归 WorkBuddy 主执行；两台机器最终都由 Eason 管理。**
6. **PR 更新 ≠ 产品已经 canonical；必须看 lineage、测试和验收。**
7. **PR 编号和 DEPTH 编号是两个不同体系。**
8. **服务器连接能力 ≠ 部署授权。**
9. **涉及 HK-STAGING / Command Center 时，必须读当前 Runbook，不能靠历史聊天和模型记忆。**
10. **任何 AI 都不应擅自复制私钥、凭据、AccessKey、runtime `.env` 或其他秘密到 GitHub。**

## 6. 当前业务运行状态速查（新会话 5 分钟上手）

> 2026-09-13 起生效。唯一机器可读指针：
> [`docs/canonical-baseline/CURRENT_HK_RUNTIME.json`](../canonical-baseline/CURRENT_HK_RUNTIME.json)。
> 本节是导航，不是 Execution Authority。
>
> 2026-09-14 刷新：本节继续只描述**运行中**的运行时的导航；repository 侧事实已拆到 [`GO_CURRENT_STATE.md`](GO_CURRENT_STATE.md)。运行中的 DB revision（`0133`）与 repository migration head（`0134`）是两件事。

| 问题 | 答案 |
| --- | --- |
| 当前业务源码在哪里 | `application/` |
| 当前 HK 运行的是什么 | **DEPTH48** 业务运行时（2026-09-13 上线） |
| Dockerfile 在哪里 | `application/Dockerfile`，构建上下文就是 `application/` |
| Compose 在哪里 | `deploy/hk-staging/docker-compose.business-runtime.yml` |
| 当前 **live HK** DB revision | `0133_flight_change_plan`（PostgreSQL 18.4，551 表）—— 这是**运行中**数据库的版本 |
| 当前 **repository** migration head | `0134_flight_status_width`（canonical main 源码 head，**尚未**在 live HK 执行） |
| 当前 repository 源码身份 | canonical main `8ffcde66…`，`main:application` = `dd815baf…`（1365 文件）—— 详见 [`GO_CURRENT_STATE.md`](GO_CURRENT_STATE.md) |
| 当前 8 个业务服务 | `api` + `outbox-worker` / `recovery-worker` / `reconciliation-worker` / `judgment-worker` / `mobile-engagement-worker` / `mobile-push-worker` / `mobile-push-receipt-worker` |
| 哪些是 protected non-target | `caddy`、`redis`、PostgreSQL/RDS 业务数据、媒体持久卷、HK Agent、Executor、签名密钥、Task/Evidence/ledger、Control Plane authority、SSH、Production |
| 怎么从 GitHub build | `docker build -t <tag> application/` |
| 基本 smoke | `curl -fsS http://127.0.0.1:8000/health`；worker 模块可导入；运行镜像内 `alembic heads` = `0133_flight_change_plan` |
| 怎么运行 / 切换 | `deploy/hk-staging/README.md`（`--no-deps` + 显式 8 服务列表） |
| 哪些已 superseded | DEPTH46 历史父包、旧 R3.x 香港运行时、`hk-staging/`（2026-09-11 快照） |
| 什么不是 current authority | `deliverables/`、`evidence/` 中的历史证据；`CP11_DEPTH48_SOURCE_COMPOSITE_PARENT_20260913` 的内层镜像（只是源码载体，不是可运行镜像） |
| 两条轴线 | **Control Plane** = `command-center/`、`control-plane/`、`hk-staging/source/{agent,executor}`；**Business Runtime** = `application/` + `deploy/hk-staging/`。不要互相推断。 |
| 三条 HOLD | `HK_DEPLOY` / `FINAL_RELEASE` / `PRODUCTION` 在 canonical main 上均为 `HOLD`，不会因为 merge 或 context 刷新而解除 |

> 本表只描述**运行中**的运行时的导航。repository 侧（main SHA、application tree、源码指纹、repository migration head、gate/release 状态、open candidate PR）一律以 [`GO_CURRENT_STATE.md`](GO_CURRENT_STATE.md) 与 [`CONTEXT_CHECKPOINT.json`](CONTEXT_CHECKPOINT.json) 为准。**运行中的 DB revision 不等于 repository migration head。**

不要从 PR 编号猜当前状态，也不要把历史 parent / sealed package / 归档快照当成 active runtime。
