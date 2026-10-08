# GO

> **本文件是 GO 仓库唯一的人类 CURRENT 入口。**
> AI 的操作入口是同目录的 [`AGENTS.md`](AGENTS.md)。
> 除这两个文件以外的 Markdown 全部属于 **HISTORY**（历史 / 取证 / break-glass），不再作为当前正常操作入口，见 [§10](#10-history-在哪里)。HISTORY 不等于“里面每句话都失效”：Evidence、治理约束、回滚资料或被机器按字节绑定的组件说明仍可能有效，但不能推翻根 README / AGENTS 的当前路线。
>
> 本文件**不写死会快速变化的值**（commit SHA、镜像 id、迁移 head、服务运行状态）。这些事实请现场重读：
> 运行身份以**最新一条签名 VERIFY Evidence** 为准；仓库侧身份以 `main` 现场为准。

---

## 1. 这个项目是什么

GO 是一个**酒店 / 机票 / 火车票 / 租车 / 用车 / 景点**多业态的在线交易与履约平台，同时它更重要的身份是：

> **一个「AI 可以在受控边界内真实部署」的工程系统。**

平台上运行着三套彼此独立的系统：

| 系统 | 干什么 | 现在怎么操作 |
|---|---|---|
| **业务运行时**（Business Runtime） | 真正在跑的业务服务，部署在香港测试机 HK-STAGING-01 | 通过 **GO Forge** 部署（见 §5） |
| **GO Forge** | 常驻的自主部署操作员：把「授权候选」部署到 HK 并与真实运行状态对账 | 老板发一句话 / 一个 Task JSON（见 §4） |
| **Persistent Runtime（C01–C14）** | 老板派开发任务 → 自动写代码 → 出 Draft PR → 自动 C14/C13 审核 | 老板发一张 GitHub Issue（见 §7） |

**这三套是三条不同的轴，不要互相代入。** 尤其：仓库 `main` 领先现场是常态，仓库不等于现场字节。

## 2. 现在总体架构是什么

```text
        老板 / 老板GPT / ChatGPT
                 │
     ┌───────────┴────────────┐
     │                        │
【部署轴】GO Forge          【开发轴】Persistent Runtime
     │                        │
  tasks/<id>.json          GitHub Issue
  authority=GO-FORGE       Cxx · <task-id> · <scope>
     │                        │
  forge-worker.service     rt01 上的 Runtime
     │                        │
  HK 密封执行器              Builder（gh-aw）
  go-hk-deployctl            → 恰好一个 Draft PR
     │                        → 自动 C14 → 自动 C13
  HK-STAGING-01            　（审核只出证据，不 merge、不 deploy）
     │
  签名 Evidence + 企业微信通知
```

- **两条轴互不干涉**：部署轴用 Forge，开发轴用 Issue。同一件事**不要两条路一起走**。
- **最后一步永远要人**：Forge 部署后给的是 `READY`，**merge 由老板自己做**；C13/C14 也只停在证据。
- **旧 Command Center（Old CC）已经不在正常路径上**（2026-10-08 起其请求桥与 Web 服务已停止并 disabled，周期 timer 已退役）。它的源码留在树里只作 **break-glass 历史**。

## 3. 当前有哪些主要系统

| 系统 | 位置 | 状态 |
|---|---|---|
| 业务源码 | `application/` | **ACTIVE** |
| 业务运行定义 | `deploy/hk-staging/`（compose + 环境键契约） | **ACTIVE** |
| 业务镜像构建 | `application/Dockerfile` | **ACTIVE** |
| GO Forge 操作员 | `chenzhenxi1-sudo/go-control-tasks` → `forge-operator/source/` | **ACTIVE**（canonical source） |
| Forge 任务总线 | 同上 → `tasks/`（入）/ `receipts/`（运行账） | **ACTIVE** |
| 签名证据 | `chenzhenxi1-sudo/go-control-evidence` → `evidence/` | **ACTIVE** |
| Persistent Runtime | 运行时在 `go-runtime-test-01`；仓库侧源码在 `control-plane/runtime-host-channel-v1/`（部分组件只在分支，见 §12） | **ACTIVE** |
| 旧 Command Center | `command-center/`、`control-plane/` 下的旧 CC 组件、`hk-staging/source/{agent,executor}` | **退役，不在正常路径**；只保留有历史 / break-glass 价值的内容。注意：`control-plane/` 不是整体退役，Persistent Runtime 等当前能力仍在其中 |
| `deliverables/`、`evidence/`、`hk-staging/`（2026-09-11 快照）、各 DEPTH 父包 | 仓库内归档 | **HISTORY**，绑定其原始 commit，不是当前权威 |

**保护非目标（任何业务切换都不得停止、删除或重建）**：
`caddy` · `redis` · PostgreSQL/RDS 业务数据 · 媒体持久卷 · HK Agent · Executor · 签名密钥 · Task/Evidence/ledger · Control Plane 权威数据 · SSH 访问与密钥材料 · Production。

## 4. 老板现在怎么派活

老板 GPT 负责**把老板的意图写成 GO-FORGE Task，提交到 `chenzhenxi1-sudo/go-control-tasks` 的 `main/tasks/`，再跟踪结果并向老板汇报**；不接管 Forge 的执行。

GO Forge 收到 Task 后，自己负责查 PR、找候选、读真实运行状态、部署、检查、回滚、找对应文件和发布 Evidence。老板 GPT 不需要知道这些实现细节。

### A. 要部署一个 PR

老板说：

```text
Deploy PR 558 to HK-STAGING.
```

老板 GPT 提交：

```json
{
  "authority": "GO-FORGE",
  "action_id": "FORGE_DEPLOY",
  "environment": "HK-STAGING-01",
  "target_pr": 558,
  "schema_version": "1",
  "task_id": "forge-deploy-pr558-<unique>",
  "issued_at": "<UTC ISO-8601>",
  "nonce": "<unique random string>",
  "parameters": {}
}
```

提交后**不要自己部署**。GO Forge 负责执行；老板 GPT 按下文查看 Receipt / Evidence，再向老板报告结果。

### B. 要检查某个 PR / 某次部署

老板说：

```text
Inspect PR 558 on HK-STAGING.
```

提交同样的 Task，只把：

```json
"action_id": "FORGE_INSPECT",
"target_pr": 558
```

`FORGE_INSPECT` 只检查、只报告，不授权部署。

### C. 要看 HK 现在实际跑什么、对应什么文件

老板可以直接说：

```text
看看 HK-STAGING-01 现在实际跑的是哪个版本，对应哪些 source / image / 关键文件，把结果给我。
```

这也是一个 `FORGE_INSPECT` Task；这种纯现场检查**不需要先指定 PR**。把要看的内容放进 `parameters`：

```json
{
  "authority": "GO-FORGE",
  "action_id": "FORGE_INSPECT",
  "environment": "HK-STAGING-01",
  "schema_version": "1",
  "task_id": "forge-inspect-<unique>",
  "issued_at": "<UTC ISO-8601>",
  "nonce": "<unique random string>",
  "parameters": {
    "request": "查看 HK-STAGING-01 当前实际运行版本、对应 source/image/关键文件路径与 Evidence，并返回结果。"
  }
}
```

GO Forge 会去读真实现场和 Evidence，找到对应版本 / 文件 / 路径并把结果返回。**不要让老板 GPT 自己猜现场版本。**

### D. 提交 Task 后怎么查结果

**Task 提交成功不等于任务完成。Boss GPT 负责读结果、汇报，不负责写 Evidence。**

1. 保存刚提交的 `task_id`，后续查询只用这个任务编号。
2. 查看 `chenzhenxi1-sudo/go-control-tasks` 的 `main/receipts/<task_id>.json`，确认 `RECEIVED` / `FINAL` 及其记录的结果、Evidence 位置。
3. 如果还没出现 `FINAL`，向老板说明当前状态，之后继续按同一 `task_id` 查询；**不要因为暂时没结果就重复提交部署 Task**。
4. 出现终局结果后，打开 `chenzhenxi1-sudo/go-control-evidence` 的 `evidence/` 中**本次任务对应的正式 Evidence**，核对结果和失败原因，再向老板汇报，并给出 Evidence 链接。
5. 如果只有通知或 Receipt、尚无可核实的正式 Evidence，如实说明“正式结果尚未确认”，不要声称部署成功。

**正式 Evidence 由 GO Forge 写入。老板 GPT 只读取、引用和汇报，绝不代写或伪造 Evidence。**

### Task 规则

- Task 文件路径：`chenzhenxi1-sudo/go-control-tasks` → `main/tasks/<task_id>.json`
- `authority` 必须是 `GO-FORGE`
- 部署用 `FORGE_DEPLOY`
- 检查 / 查版本 / 查文件用 `FORGE_INSPECT`
- `environment` 是 `HK-STAGING-01`
- `task_id`、`issued_at`、`nonce` 只需要唯一 / 当前即可
- 不要自己提供 source commit、candidate id、artifact、image id、migration head、compose 路径、TEST_PR 参数、deployctl 命令；这些都是 GO Forge 的工作
- 正常模式不要发 `HK_STAGING_TEST_PR / CANARY / VERIFY / DEPLOY`，也不要走 Old Command Center
- 结果先看同仓 `receipts/<task_id>.json`，最终权威结果看签名 Evidence

### 派开发任务（开发轴）

在 GO 仓库新建一张 **GitHub Issue**，格式见 §7。

## 5. 怎么部署 HK

**正常路径只有一条：GO Forge。**

```text
Boss / Boss GPT
  -> GitHub Task（一份 JSON，落在 chenzhenxi1-sudo/go-control-tasks）
  -> GO Forge（Command Center 主机上的常驻操作员，用户 go-forge，forge-worker.service）
  -> HK 密封执行器 /usr/local/libexec/go-hk-deployctl（verify | canary | deploy | rollback）
  -> HK-STAGING-01
  -> 签名 Evidence + 企业微信通知
```

Forge 自己会做：
```text
读 PR 的现场状态（head commit 是权威）
确定不可变源码身份
找到该 head 的候选（没有就准备一个）
检查 HK 真实运行状态
在改动前先验证一条真实可用的恢复路径
跑密封 CANARY，再跑密封 DEPLOY，逐步验证
某步验证不通过就自动回滚
发布签名 Evidence，然后通知企业微信
```
步骤顺序由 Forge 自己决定，且允许中途按现场修正计划——**修正会被记录，不会被隐藏**。

终端结果只有这几种，**Forge 报事实，不做解释**：

| 结果 | 含义 |
|---|---|
| `DEPLOY_SUCCESS` | 已部署，并已对真实运行系统验证通过 |
| `FAILED_ROLLBACK_SUCCESS` | 部署失败，环境已还原，需要人 |
| `FAILED_NEEDS_HUMAN` | Forge 遇到一个阻止它继续的事实，Evidence 里写明了是什么 |
| `PASS` | 不产生改动的动作（例如 `FORGE_INSPECT`）完成 |
| `STOPPED_BY_HUMAN` | `FORGE_STOP` 被接受 |

**`READY` 不等于交接 merge。** Forge 永不 merge、永不评论 PR、永不关闭 PR、永不推进任何 baseline 声明——这些在工具层就被拒绝，不只是提示里劝阻。老板自己 review、自己 merge。

**正常运行 Forge 模式时不要做**：
```text
不要手发 HK_STAGING_TEST_PR / HK_STAGING_CANARY / HK_STAGING_VERIFY / HK_STAGING_DEPLOY
不要提供 image/artifact/package 摘要、migration 命令、docker 命令、compose 路径
不要同时走 Forge 与 Old Command Center 两条路
```

**Fallback**：Old CC 源码保留在树里，可以**刻意**重建，但它只是 fallback —— 仅在老板**明确**要求切到 fallback 模式时使用，不是因为部署不顺就切。

## 6. 怎么查看 HK

用同一条轴：`FORGE_INSPECT`。

```text
Inspect HK-STAGING for the current runtime identity.
```

`FORGE_INSPECT` **不授权任何改动**，是检查环境的安全方式；它会跑一次真实检查、发布 Evidence、发企业微信。

想看**版本 / migration head / 服务是否健康**这类问题，统一收口到 `FORGE_INSPECT` —— 不要自己去 HK 上敲命令，也不要发 `HK_STAGING_VERIFY`。

## 7. Persistent Runtime / 14 Cells 是干什么的

**开发轴**，与部署轴无关，跑在 `go-runtime-test-01` 上。

### 派一个开发任务（C01–C12）

新建 GitHub Issue，标题固定：

```text
Cxx · <task-id> · <scope>
```
例如 `C08 · V71-R1-C08-01 · improve trip-planning handoff`。

正文至少写：

```text
Task: <要做什么，必须有测试可验证>

Canonical source: <创建 Issue 当时 GO current main 的完整 40 位 SHA>
```

规则要点：
- `Cxx` 只能是 **C01–C12**；task id 里的 Cell 必须与标题一致。
- `Canonical source` 必须是**创建 Issue 当时**的 current main 完整 SHA，**不要**从旧 Issue / 聊天 / README 示例里抄一个旧 SHA。
- 解析器只把 `Task:` 后**第一个连续段落**当作 objective（空行后的说明不会自动进载荷）；所有范围、限制、验收写进这一段，最长 4000 字符。
- 新一轮任务新建 Issue / 新 task id，不要只在旧 Issue 评论里改。

创建后的链路（**不需要人再做任何事**）：

```text
Formal Issue
-> Persistent Runtime
-> C01-C12 Generic Builder
-> GitHub Agentic Workflow
-> inspect / edit / test
-> 恰好一个 Draft PR
-> 自动：C14 审核轮
-> 自动：C13 审核轮
-> 密封轮次结论，由 Runtime 采纳
```

### 单独审核一个既有 PR（可选）

只有要审的 PR **不是** Runtime Builder 刚产出的时候才需要手工发起：

```text
C14 · REVIEW · <description>

Candidate PR: #<PR_NUMBER>
Candidate SHA: <创建这张 Issue 时该 PR 的精确 head SHA>
```

- **不要创建 `C13 · REVIEW` Issue**——Issue 只能启动 C14；只有 C14 密封结论允许继续时，Runtime 才自动建 C13。
- Candidate SHA 必须等于**创建这张 Issue 时**该 PR 的 head；PR 之后又 push 了新 commit 就作废，请对新 head 新建一张。
- C13/C14 只审核和出证据，**不 merge、不 deploy**。

### C01–C14 分别是什么

| Cell | 职责 | | Cell | 职责 |
|---|---|---|---|---|
| C01 | Hotel AI Operations | | C08 | GO AI Planning & Execution |
| C02 | Flight AI Operations | | C09 | GO Judgment & Trust |
| C03 | Rail AI Operations | | C10 | Unified Trips |
| C04 | Rental AI Operations | | C11 | Transaction & Finance |
| C05 | Ride AI Operations | | C12 | Platform / Security / Model Gateway |
| C06 | Attraction AI Operations | | **C13 / C14** | **control-only 审核单元，不接受普通 Builder task** |
| C07 | Traveler Intelligence | | | |

> **「14 个 worker」是错误读法。** 14 指的是 C01–C14 这 14 个 **Cell**；其中 C13/C14 是 control-only。
> 现在真正在跑的 executor 只有两个：Builder 链和 C13/C14 审核链。

**一句话**：C01–C12 发 Formal Task Issue，剩下的 Builder → Draft PR → C14 → C13 由 Runtime 自己走完；需要单独审一个现成 PR 时发 C14 Formal Review Issue。**只有最后的 merge / deploy 仍需独立授权。**

## 8. Evidence 在哪里

| 内容 | 位置 |
|---|---|
| HK 运行身份（**唯一权威**） | `chenzhenxi1-sudo/go-control-evidence` → `evidence/`，取**最新一条签名 VERIFY** |
| Forge 每次任务的结果 | 同上，每个终态任务恰好发布一份文档 |
| Forge 运行账 | `chenzhenxi1-sudo/go-control-tasks` → `receipts/` |
| 企业微信 | 每个被接受的任务一条消息，发到 owner 单聊 |
| C13/C14 轮次结论 | Runtime / GitHub Actions sealed artifacts（未合并的轮次产物在 `docs/runtime/` 有历史记录） |

**仓库里没有任何文件声明「某台机器在跑什么」。** 曾经的 `docs/canonical-baseline/CURRENT_HK_RUNTIME.json` 已于 2026-10-08 退役删除——仓库里的声明文件无法如实说明一台机器在跑什么，且它确实发生过漂移。现在只有**最新签名 VERIFY Evidence** 能回答这个问题。

## 9. 仓库主要目录

| 目录 / 文件 | 是什么 |
|---|---|
| `README.md` | **本文件**，人类 CURRENT 入口 |
| `AGENTS.md` | **AI CURRENT 操作入口** |
| `application/` | 业务源码（Python + alembic + 前端 + workers） |
| `deploy/hk-staging/` | 业务运行定义（compose + 环境键契约）。**运行定义**，不是计划、不是候选、不是历史 |
| `control-plane/` | Control Plane 组件（含 Persistent Runtime 的仓库侧源码） |
| `command-center/` | 旧 Command Center 归档（退役，break-glass） |
| `hk-staging/` | 2026-09-11 上一代 HK 运行时快照（**历史**） |
| `deliverables/`、`evidence/` | 历史交付与证据，绑定其原始 commit（**历史**） |
| `docs/` | 见 §10。**绝大多数是 HISTORY** |
| `packaging/`、`ci/` | 打包与 CI 相关定义 |

## 10. HISTORY 在哪里

**除根 `README.md` 与根 `AGENTS.md` 之外的所有 Markdown 都是 HISTORY（即：不是 CURRENT 操作入口）。** HISTORY 文件中的某些 Evidence、约束或机器绑定事实仍可能有效；只是它们不能自行定义当前正常路线。

它们可以读、可以查证、可以拿来做取证，但**不能再指导当前正常操作**。典型：

| 位置 | 内容 |
|---|---|
| `docs/control-plane/**` | 旧 Command Center / HK-STAGING `HK_STAGING_*` 运行手册与指南（含 break-glass 参考） |
| `docs/project/**`、`docs/state/**` | 早期的 project-context / startup 体系（已被本文件取代） |
| `docs/runtime/**` | Persistent Runtime 的历史设计与验证文档（**老板日常派活以本文件 §7 为准**） |
| `docs/go-forge/**` | Forge 的历史设计与取证文档（**契约以本文件 §4/§5 + `AGENTS.md` 为准**） |
| `docs/audits/**`、`docs/reviews/**`、`docs/canonical-baseline/**` | 审计、评审、历史基线 |
| `docs/governance/**` | 仍然有效的治理规则（**变更控制**等）——属于流程规则，不是操作入口 |
| `control-plane/**/README.md`、`packaging/**`、`ci/**` | 各组件自己的历史说明 |

判断标准只有一条：**任何 HISTORY 文件都不应让一个零上下文的 AI 误以为它是当前操作入口。**

## 11. 安全边界

**能连上 ≠ 被授权。** 能 SSH、能用 Docker、能访问 GitHub、能调 Control Plane 命令，都不代表这次操作被允许。

- **真实生产 / HK 正式变更 / 部署 / 重大配置变化，必须由真人明确授权。** 建议、权限、证据、CI 全绿都**不等于**授权。
- **Production 一律禁止**，除非 owner 当次明确书面授权。
- **文档不是 Execution Authority。** 执行权威仍然是：现场状态 · 人工批准 · Signed Task · 已安装产物 · 可用的回滚记录 · 签名 Evidence。
- 不改主机权威文件、不改 systemd、不改网络/代理/DNS、不动 Production 数据。
- **密钥、token、私钥、运行 `.env` 实值永不进 Git / PR 正文 / 对外文档 / 日志。**
- **老板的 PR 一律不碰**（分支 / 提交 / 合并 / 关闭都不碰）。
- 服务器默认**只读**：任何写操作逐次重新授权。
- 历史证据（`deliverables/`、`evidence/`）绑定其原始 commit，不要因为产品线前进了就删。

## 12. 遇到问题应该从哪里开始查

1. **先问「这是哪条轴」**：部署/查看 → Forge；开发/审核 → Persistent Runtime；业务代码 → `application/`。
2. **不要从 AI 记忆、旧聊天、旧 PR 顺序重建流程。** 用本文件 + `AGENTS.md`。
3. **要「现在到底在跑什么」** → 读最新一条签名 VERIFY Evidence，不要读仓库里的任何声明文件。
4. **要「仓库 main 现在是什么」** → 现场读 `main`，不要相信文档里写死的 SHA。
5. **要「某条命令为什么被拒」** → 先确认 `authority` / `action_id` / 身份字段是否齐备；系统原则是**身份不确定就不执行**，不会偷偷修成「差不多对」。
6. **要「某个能力有没有代码」** → 注意**仓库里的候选 ≠ 现场已装**。Persistent Runtime 的部分组件（`runtime.py`、runtime-host-agent、runtime bridge）在 `main` 上**没有字节**，其 source-of-record 在保留分支上；`main` 声明 3 个单元而现场实际启用更多。**这类不一致只报告、不当场修。**
7. **要翻历史** → 从 §10 的目录表找对应区域，并记住它已经不是当前操作说明。

---

## 相关链接

- AI 操作入口：[`AGENTS.md`](AGENTS.md)
- 变更控制规则：[`docs/governance/CHANGE_CONTROL_POLICY.md`](docs/governance/CHANGE_CONTROL_POLICY.md)
- Forge 任务总线（另一仓库）：`chenzhenxi1-sudo/go-control-tasks`
- 签名证据（另一仓库）：`chenzhenxi1-sudo/go-control-evidence`
