# GO

GO 主项目仓库。

本 README 只负责**导航、事实来源和工作边界**，不保存容易变化的 runtime 版本号、PR 清单、migration revision 或 image tag。

> **开始任何实质性 GO 工作前，先重新读取 live state。不要从 README、旧 PR、旧 Evidence 或历史聊天直接推断当前状态。**

## Start here

按下面顺序获取当前事实：

1. **GitHub 当前 `main`**
2. 当前任务对应的 **PR / branch / commit / diff**
3. [GO Update Log](docs/project/UPDATE_LOG.md) — 最近重大变化的短时间线
4. [OPERATING_CONTEXT.md](docs/project/OPERATING_CONTEXT.md) — 人员、职责和工作方式
5. [GO_CURRENT_STATE.md](docs/project/GO_CURRENT_STATE.md) — 项目状态快照；注意其 checkpoint 日期，可能落后
6. [CONTEXT_CHECKPOINT.json](docs/project/CONTEXT_CHECKPOINT.json) — current-state 快照实际绑定的 main
7. 涉及 HK-STAGING 时，再读对应的 live runtime / deploy / Evidence / Runbook

### 当前 HK runtime 去哪里看

不要从 README 的文字、PR 编号或历史部署记录猜。

机器可读入口：

- [CURRENT_HK_RUNTIME.json](docs/canonical-baseline/CURRENT_HK_RUNTIME.json)

业务运行定义：

- [deploy/hk-staging/README.md](deploy/hk-staging/README.md)
- `application/`
- `application/Dockerfile`
- `deploy/hk-staging/docker-compose.business-runtime.yml`
- `deploy/hk-staging/RUNTIME_ENV_CONTRACT.md`

Control Plane / HK 操作入口：

- [docs/control-plane/hk-staging/README.md](docs/control-plane/hk-staging/README.md)

如果仓库指针与真实机器 / 当前 Evidence 冲突，以更直接的 live Evidence 为准，并记录 reconciliation；不要静默把历史改成今天的样子。

## Truth priority

GO 的事实优先级：

```text
GitHub live state / real environment / current Evidence
>
repository current-state documents
>
historical PR / README / old handoff
>
AI memory / historical conversation
```

未知事实写成 `UNKNOWN`，不要自动补齐。

## Three things that must stay separate

### 1. Source

GitHub 中当前源码、PR、branch、commit、tree。

**Merged into main ≠ 已经部署。**

### 2. Candidate / delivery

被选中的 candidate、构建产物、image、migration plan、deploy Evidence。

**Candidate READY / CI PASS ≠ 已经在真实环境运行。**

### 3. Runtime / business acceptance

真实 HK-STAGING 或 Production 正在运行的 artifact，以及产品功能是否通过业务验收。

**Runtime 正常 ≠ 产品已经完成验收。**

同样：

**Product correctness** 和 **Delivery correctness** 是两件事。

部署链负责证明指定 Candidate 是否被正确安装；它不会自动证明业务逻辑、UI、支付行为或性能已经符合产品要求。

## Main project vs GO Forge

**GO** 是主产品项目。

**GO Forge** 是部署辅助子项目，不等于 GO 主项目本身。

在 GO 仓库中，只保留与 Forge 对 GO 的部署接口、candidate / runtime reconciliation 等必要上下文。Forge 自身源码、Forge Task、Forge rebuild、Forge notifier 等工作应在 GO Forge 的专用工作空间中处理。

不要为了接入 Forge 而把 GO 主项目重新包成一套新的治理体系。

## Repository map

| Path | Purpose |
| --- | --- |
| `application/` | GO 业务应用源码 |
| `deploy/hk-staging/` | HK-STAGING 业务运行定义 |
| `docs/canonical-baseline/CURRENT_HK_RUNTIME.json` | 当前 HK runtime 的机器可读指针 |
| `docs/project/UPDATE_LOG.md` | 最近重大变化时间线 |
| `docs/project/` | 项目上下文、current-state、decision、handoff |
| `docs/state/` | 模块级状态快照 |
| `command-center/` | Command Center 相关源码/归档 |
| `control-plane/` | Control Plane 源码与契约 |
| `hk-staging/` | 历史/控制面相关 HK 快照；不要把它当当前业务 runtime 定义 |
| `ci/` | 测试、gate、candidate/retention 相关定义 |
| `evidence/`, `journey-evidence/` | 与原始 commit / scope 绑定的历史 Evidence |
| `deliverables/` | 历史交付物 / archive |
| `packaging/` | candidate / package / restore 相关材料 |

历史索引可从 [GO_REPOSITORY_INDEX.md](GO_REPOSITORY_INDEX.md) 进入，但其中带具体版本号的段落必须结合其更新时间阅读，不能天然视为今天状态。

## People and authority

- **Boss / 余总** — 产品 Owner；决定产品方向、业务需求、优先级和最终业务取舍。
- **Eason / 陈震曦** — 技术执行、集成、审核和运行协调负责人。
- **Eason's ChatGPT** — technical coordination + review + context + task decomposition。
- **WorkBuddy / Codex** — 执行 Agent。

能 Shell / Git / SSH 不等于拥有 merge、deploy 或 Production mutation authority。

完整职责背景：

- [OPERATING_CONTEXT.md](docs/project/OPERATING_CONTEXT.md)
- [AGENTS.md](AGENTS.md)

## PR ownership

严格区分 PR Owner。

### `chenzhenxi1-sudo`

可以在 Eason 自有 branch / PR 内：

- 修改
- 推送
- 复核
- 整合
- 准备 candidate

### `yuguangzhi3836-glitch`

Boss-owned PR：

- 可以读取
- 可以审核
- 可以定位问题
- 可以给出建议

但不直接接管、push、rewrite 或替 Boss 修改。

如果 Boss PR 的内容需要我方修复，优先在我方 branch / PR 中处理，并明确来源。

PR 编号不是产品 generation，也不能用“编号更新”判断哪个 candidate 更正确。

## Mutation boundary

调查、分析、审核、对比、设计默认 **read-only**。

真实 mutation 前至少确认：

1. **TARGET**
2. **SCOPE**
3. **RECOVERY / ROLLBACK**
4. **AUDIT / EVIDENCE**
5. **AUTHORIZATION**

未经明确授权，不自动：

- merge PR
- 部署 HK
- 执行 migration
- 修改 Production
- 接管 Boss PR
- 新增长期基础设施
- 重写历史 Evidence

## Engineering principle

GO 不追求流程最多、服务最多或控制最多。

长期原则：

```text
Simple
Traceable
Reversible
```

新增长期控制前先回答：

```text
REAL_FAILURE_PREVENTED = ?
```

优先复用已有 capability，不因为已有一个旧 workflow 就继承整个旧流程。

不要重复：

```text
process
-> verifier
-> verifier of verifier
-> more governance
```

安全也遵循同一原则：能力或暴露面变化时重新评估；只有真实风险或高价值资产需要时，才增加最小必要控制。

## Historical evidence

历史的：

- parent
- sealed package
- snapshot
- old Evidence
- old Candidate
- old runtime pointer

用于审计和理解历史。

它们不是 current authority，也不应该为了与今天一致而被改写。

## Quick rule for new sessions

如果你只能记住一句：

> **先读 live state，再判断 Source、Candidate、Runtime 分别是什么；不要从 PR 数字、README 旧快照或 AI 记忆推断当前真实环境。**
