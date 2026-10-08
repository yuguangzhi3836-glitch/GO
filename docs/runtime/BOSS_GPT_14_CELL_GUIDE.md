> **HISTORY** — 历史 / 取证材料，不是当前操作说明。
> **HISTORY** — historical / audit material, not current operating instructions.
>
> 当前入口：人（中文）[`README.md`](../../README.md) · AI（英文）[`AGENTS.md`](../../AGENTS.md)。
> Current entry points: [`README.md`](../../README.md) (Chinese, humans) and [`AGENTS.md`](../../AGENTS.md) (English, AI).
>
> 本文档不定义正常操作路径，不得作为当前操作依据。This document does not define the normal path; do not use it as current operating guidance.

---

# GO Persistent Runtime / 14 Cell — Boss GPT 完整交付说明

> **历史说明（不再是单一入口）。** 当前入口是仓库根 `README.md`（中文）与 `AGENTS.md`（英文）。
>
> 这份文档同时回答四个问题：
> 1. 我们这几天到底做了什么；
> 2. Persistent Runtime 为什么存在、原理是什么；
> 3. 14 个 Cell 现在怎么协作；
> 4. 老板以后到底怎么用。
>
> 正常链已经通过真实 LIVE E2E：**C01-C12 Formal Issue → Builder → Draft PR → 自动 C14 → 自动 C13 → round decision**。

---

# 1. 一句话先讲明白

以前的问题不是 AI 不会干活，而是：

```text
老板发任务
→ AI 跑一次
→ 中间进程退出 / GitHub run 结束 / 人离开
→ 谁记得这个任务现在走到哪？
→ 谁保证恢复后不会再付一次钱？
→ Builder 产出 PR 后谁继续送 C14 / C13？
```

Persistent Runtime 解决的是**持续状态和任务接力**，不是把 14 个模型搬到第三台 ECS。

最终形态：

```text
余总 / Boss GPT
        ↓ 只发一次正式任务
GitHub Formal Issue
        ↓
rt01 Persistent Runtime
  ├─ durable task state
  ├─ lease / attempt fencing
  ├─ deterministic execution identity
  ├─ durable dispatch outbox
  ├─ crash / restart recovery
  └─ result adoption / next-step enqueue
        ↓
GitHub Actions / gh-aw 临时 AI 执行
        ↓
Draft PR
        ↓
自动 C14
        ↓
自动 C13
        ↓
sealed round decision
        ↓
STOP
```

**AI 执行主要在 GitHub Actions / gh-aw。rt01 负责“记住、排队、保活、续接、收口”。**

---

# 2. 为什么叫 Persistent Runtime

“Persistent” 不是说模型永远在线，而是任务状态不会随着一次 AI 会话结束而消失。

## 2.1 Runtime 持久保存什么

Runtime 持久保存和约束：

- task identity；
- owner Cell；
- task kind；
- attempt；
- lease owner / lease deadline；
- deterministic execution request identity；
- 是否已经 dispatch；
- GitHub run / artifact 结果；
- Runtime 是否已经采纳结果；
- 下一段任务是否已经 enqueue。

所以一个任务即使跨越：

```text
AI 进程退出
Worker restart
rt01 service restart
GitHub workflow 长时间运行
网络短暂失败
人在晚上离开
```

也不应该靠聊天记忆继续，而是靠持久状态继续。

## 2.2 为什么不会因为恢复而重复花钱

核心不是“希望它别重复”，而是结构上限制：

1. **intent 先持久化**，再允许 dispatch；
2. 同一 execution identity 的 `dispatches_sent` 被 durable outbox 记录；
3. dispatch 结果不确定时，按 deterministic run name **lookup**，不允许第二次 POST；
4. Runtime task / attempt / lease 必须匹配，过期执行不能冒充当前执行；
5. 已经存在可采纳结果时，恢复路径优先采纳结果，不重新付一次 AI；
6. Review 类在真正会产生付费 dispatch 前再次确认 lease。

这就是 exactly-once paid-dispatch 语义的来源。

## 2.3 为什么 Builder → C14 → C13 中途崩溃也不会断

两个关键顺序都一样：

```text
Builder 完成时：
先 enqueue C14
再 Runtime.complete(Builder)

C14 完成时：
先 enqueue C13
再 Runtime.complete(C14)
```

如果恰好在两步中间 crash：

```text
restart
→ 再执行相同 deterministic enqueue
→ Runtime idempotency 返回同一个 task
→ 不生成第二个 C14 / C13
→ 然后完成上一段
```

没有新增事务协调器、第二队列或 verifier-of-verifier。

---

# 3. Runtime 不是什么

Persistent Runtime **不是**：

- 14 个模型常驻在 ECS；
- Command Center；
- 产品经理；
- C13/C14 的替代品；
- Release Authority；
- 自动 merge 服务；
- 自动部署 Production 的服务；
- 为了“架构完整”再造的一套治理平台。

它的职责只有：

```text
queue / state / lease / attempt fencing
→ dispatch
→ evidence/result adoption
→ recovery
→ deterministic next-step handoff
```

产品是否正确由产品与审核判断；部署是否正确由部署链/Evidence 判断；Runtime 只保证任务执行链不因一次会话结束而丢失。

---

# 4. 14 个 Cell 现在是什么关系

| Cell | 正式职责 | 老板正常直接派任务？ |
| --- | --- | --- |
| C01 | Hotel AI Operations | 是 |
| C02 | Flight AI Operations | 是 |
| C03 | Rail AI Operations | 是 |
| C04 | Rental AI Operations | 是 |
| C05 | Ride AI Operations | 是 |
| C06 | Attraction AI Operations | 是 |
| C07 | Traveler Intelligence | 是 |
| C08 | GO AI Planning & Execution | 是 |
| C09 | GO Judgment & Trust | 是 |
| C10 | Unified Trips | 是 |
| C11 | Transaction & Finance | 是 |
| C12 | Platform / Security / Model Gateway | 是 |
| C13 | Independent QA & Release | **否，Runtime 自动推进** |
| C14 | AI Constitutional, Legal & Regulatory Control | **否，正常链由 Runtime 自动推进** |

## 4.1 C01-C12

C01-C12 是 Builder / 业务与平台工作 Cell。

一个 generic Builder worker 服务 C01-C12；不是 12 个 daemon，不是 12 个 outbox，也不是 12 套 Runtime。

## 4.2 C14

C14 是规则、权限、法律/合规、AI 行为边界等 control-only review。

它不负责“再写一遍业务代码”，也不拥有部署权限。

## 4.3 C13

C13 是 Independent QA & Release review：实现质量、focused machine tests、回归/恢复/安全/验收证据。

C13 不能由老板直接创建普通任务。**只有一个已封存且允许继续的 C14，才能产生 C13。**

## 4.4 顺序

```text
C01-C12 Builder
→ Draft PR
→ C14
→ 如果 C14 prerequisite admits
→ C13
→ round decision
```

审核执行成功和审核结论是两回事：

- `Runtime SUCCEEDED` = 这次审核正确执行并被 Runtime 采纳；
- `PASS / FAIL / BLOCKED` = 审核本身的结论。

一个 C13 `FAIL` 仍然可以是一次完全成功交付的 Runtime execution。

---

# 5. 这些天我们到底做了什么：10 月 1 日 → 10 月 4 日

下面只按 live GitHub / 当前 Evidence 能确认的 lineage 写。

## Phase A — 10/01：先把第三台 ECS 的角色搞对

早期 #292–#297 是 Runtime Host 的堆叠探索线：真机验证、续期/常驻、Git 快照、外部任务桥、过期任务恢复。

这些 PR **没有直接进入今天的 canonical main**，它们的价值是把真实环境、Runtime kernel、lease/recovery、Agent/Bridge 边界摸清。

### #300 — 架构纠偏

#300 明确了后来一直坚持的方向：

```text
RUNTIME_ROLE = COORDINATION_ONLY
AI_EXECUTION = GITHUB_HOSTED_EPHEMERAL
OPENAI_KEY_ON_RT01 = NO
```

也就是：**不把 OpenAI/14 个 AI Worker 常驻塞进 rt01；模型调用外置，rt01 只负责持续协调。**

#300 自身是历史 candidate，后来被 canonical 实现吸收，并未作为今天的合并点。

## Phase B — 10/01：把 Runtime → GitHub → Runtime 真正闭环

### #304 — execution loop

把之前分开的两半接起来：

```text
Runtime claim
→ durable outbox
→ GitHub workflow
→ sealed result
→ Runtime.complete
```

同时把 lease renewal、ambiguous dispatch lookup、结果收养/恢复等语义放进统一 loop。

### #305 — resident C1 worker

让闭环不再只是库函数：增加常驻 worker，真正有人 claim 任务并推进。

同时保持 Agent / Bridge 边界：

- root Agent 不直接打开 Runtime DB；
- Bridge 仍不是 worker；
- worker 以 `go-runtime` 身份运行；
- worker 有 Runtime state 权限和必要网络，但不拿模型 secret。

## Phase C — 10/02：从 smoke 变成“真正能接任务”

### #321 — real task contract

此前 `AI_WORK_V1` 是固定 smoke。#321 增加真实任务类 `AI_TASK_V1`：payload 里有真实 objective/scope，prompt 从 payload 派生，而不是写死一句 HELLO。

### #322 — 第一次 live real task 暴露问题并修掉

第一次真实任务把两个问题暴露出来：

- GitHub run 失败后的终态结算不能让 Runtime 永久续租；
- 真实任务输出预算不能沿用 smoke 的极小值。

因此失败执行被正确结算，真实任务输出预算与 smoke 分开。

这一阶段证明：**Persistent Runtime 可以真实发出一次模型任务、拿回结果并收口，而不是只有 stub。**

## Phase D — 10/03～10/04：从“能调模型”转成“真的能写代码的 Builder”

我们随后验证 gh-aw / GitHub Agentic Workflow，目标不是再造 AI framework，而是复用 GitHub 里的临时执行环境完成 inspect / edit / test / Draft PR。

### #381 — 正式 gh-aw executor / outbox 边界

建立 `GHAW_BUILDER_V1`：

- 一个 gh-aw Builder executor；
- 一个独立 durable outbox；
- 与旧 Responses executor 的 kind 完全隔离；
- 共用同一套 execution loop，而不是复制 exactly-once 状态机；
- 正式确认 Runtime `claim()` 是 queue/scheduler 语义，执行身份只能来自真正 claim 到的 task。

### #386 — workflow 正式注册 + transport 绑定

修掉“请求里写着 gh-aw，但真实 POST 仍可能打到旧 Responses workflow”的风险。

从这一轮开始，executor 自己绑定 workflow target；target 不一致会在 POST 前 fail closed。

### #387 — Builder 真正 inspect / edit / test / Draft PR

让 gh-aw Builder 不再只是 HELLO smoke，而是能读取仓库、修改代码、跑测试，并通过安全输出只创建一个 Draft PR。

## Phase E — 10/04：从 C01 泛化到 C01-C12

### #389 — 一个 Builder 服务 12 个业务/平台 Cell

把已经验证的 C01 Builder 最小泛化到 C01-C12：

```text
GHAW_BUILDER_V1 -> C01 ... C12
AI_WORK_V1 / AI_TASK_V1 -> legacy C1 Responses path only
```

没有造 12 个 worker、12 个 DB 或 12 套 workflow。

### #391 — C12 live proof 发现 cell identity bug

真实非 C1 执行暴露：lookup run name 时不能默认 C1，必须从 stored request 读真实 owner Cell。

这是 live proof 找到的真实缺陷，修后非 C1 的 crash/recovery identity 才可靠。

### #392 — Formal Issue source freshness

老板从 GitHub Issue 派任务时，Issue 声明的 `Canonical source` 必须等于当时 current main；workflow 在真正付费执行前还会再核执行 SHA。

旧任务不能因为一直 open 就在新 main 上“复活”。

## Phase F — 10/04：把 C14 / C13 接进同一个 Persistent Runtime

### #395 — ONE review worker / ONE review outbox

把已有 C14/C13 Lite 审核接入 Runtime：

```text
C14_REVIEW_V1
→ one review worker
→ existing C14 workflow
→ sealed C14
→ if prerequisite admits: enqueue C13_REVIEW_V1
→ same review worker
→ existing C13 workflow
→ sealed C13 + round decision
```

刻意没有新增 Runtime kernel、第二 scheduler、第二 queue、第二 review rules。

同时确立一个非常重要的语义：

> **Review delivery success ≠ review verdict PASS。**

FAIL/BLOCK 可以是一次正确交付的审核。

### #396 — 第一次真实 C14 dispatch 暴露 undeclared input

真实 C14 round 发现 Runtime 把 C13 专用 `machine_inventory` 也发给 C14 workflow；GitHub 对未声明 workflow_dispatch input 直接拒绝。

当时 `dispatches_sent=0`，所以没有付费，但审核起不来。

修复后按 review kind 只发送接收方真正声明的输入。

### #397 — 第一次真实 C14 round 暴露“失去 lease 仍付费派发”

诊断 #396 期间任务 lease 过期并被 Runtime 正确 escalated；worker 恢复后如果只看 outbox，可能仍然 POST 一次付费 review，而 Runtime 已经不会接受结果。

因此 review 类在真正 dispatch 前必须再次向 Runtime 确认 lease；没有 lease 就 abandon，不花这笔钱。

## Phase G — 10/04：把人工搬运彻底去掉

### #398 — Formal Review Issue ingress

先消掉了“人工运行 `deliver_review_round.py`”这一步。

老板可以用：

```text
C14 · REVIEW · <description>
Candidate PR: #...
Candidate SHA: <frozen head>
```

同一个 resident consumer 直接 enqueue C14。没有第二 consumer、第二 DB、第二去重机制。

这一阶段已经证明 C14 → C13 自动，但 Builder PR 还需要人决定“现在送审”。

### #402 — 最后一段：Builder 完成后自动 C14 → 自动 C13

这是最终闭环。

Builder 自己产生 Draft PR 后，Runtime 不再要求人创建 Review Issue。

它从**这次 Builder GitHub run 自己的 safe-output record**读取真实 `create_pull_request` 结果，再只读核验：

- PR number；
- Draft 状态；
- base == main；
- exact head SHA；
- exact application tree；
- changed test inventory。

明确不允许：

- 按 PR 标题猜；
- 找最新 `[Builder]` PR；
- 按 branch 名猜；
- 从模型回答文字里解析 PR。

验证通过后：

```text
Runtime.enqueue(C14)
→ Runtime.complete(Builder)
→ C14
→ Runtime.enqueue(C13)
→ Runtime.complete(C14)
→ C13
→ round decision
```

本轮新增常驻实体数量：**0**。

## Phase H — 真实最终 E2E

Validation Issue #403：

```text
C12 · V72-R1-C12-01 · workbench cell-role table regression
```

完整跑出了：

| Leg | Runtime task | GitHub run | dispatches | 结果 |
| --- | --- | ---: | ---: | --- |
| Builder C12 | `rt_c82ea8e5a6a64da5a51df521452312a6` | `37194602268` | 1 | SUCCEEDED |
| 自动 C14 | `rt_7f92f4c6fe07455d991dcff452416ba2` | `37194968153` | 1 | SUCCEEDED / PASS_SCOPED |
| 自动 C13 | `rt_36633ba4140f4b448f04f8bcbb023c25` | `37195017030` | 1 | SUCCEEDED / PASS_SCOPED |

Builder 真实产出 Draft PR #404，head `fe788be4b30f3ba87c47c2447cda9a28c649092d`；自动 C14 审的就是这个 head。

最终：

- `round_decision = ACCEPT`；
- C13 prerequisite root == Runtime 实收 C14 sealed root；
- independence = true；
- focused machine inventory 真正执行成功；
- 三条腿各只 dispatch 1 次；
- 人工 C14 Review Issue = 0；
- `deliver_review_round.py` = 0；
- PR #404 仍是 Draft、未 merge；
- merge / deploy 授权仍然是 0。

到这里 Persistent Runtime 才真正满足：**老板派一次活，系统自己持续跑到独立审核收口。**

---

# 6. 哪些 PR 才是今天的 canonical Runtime lineage

## 6.1 已进入 main 的核心主线

```text
#304  execution loop
#305  resident C1 worker
#321  real task contract
#322  failed-run settlement / real output budget

#381  gh-aw executor/outbox + claim semantics
#386  gh-aw workflow registration + target binding
#387  inspect/edit/test + Draft PR
#389  C01-C12 generic Builder
#391  non-C1 run identity fix
#392  Formal Issue source freshness

#395  C14→C13 review transport
#396  review undeclared-input live fix
#397  review paid-dispatch lease confirmation
#398  Formal Review Issue ingress
#402  Builder→C14→C13 full auto bridge

#400/#401/#405  current-state / owner README / delivery closeout
#406  本文：给 Boss / Boss GPT 的单一最终交付入口
```

## 6.2 历史探索，不应该为了“PR 都合上”硬 merge

### #292–#297

这些是 10/01 的 stacked Runtime Host 探索 PR，base 是当时的实验 branch，而不是今天的 main。后来核心能力已经通过上面的 canonical lineage 重新收敛并进入 main。

**结论：历史证据保留，但不要重新 merge。**

### #300

这是非常重要的架构纠偏 candidate，但最终实现通过后续 canonical PR 落地。

**结论：保留设计历史，不需要重新 merge #300。**

### Boss #383

Boss-owned 的 per-cell 自动入口候选。它与后来 ONE generic Builder + ONE review worker 的最终架构并不是同一 lineage。

**结论：不接管、不 push、不替 Boss merge。**

### #388 / #390 / #394 / #404 等 Builder/Smoke Draft PR

它们用于验证 Builder、Issue ingress、Review ingress 或最终自动链。

验证成功不等于这些产品/测试 candidate 自动取得 merge 权限。

**结论：保持 Draft/历史证据，按各自产品价值单独判断。**

---

# 7. 老板以后怎么用

老板正常只需要做一件事：**讲需求。**

Boss GPT 负责选择一个 C01-C12 Cell，并创建一张 Formal Task Issue。

## 7.1 Boss GPT 选哪个 Cell

- **C01 Hotel**：酒店产品、库存、预订、酒店供应连接、酒店业务服务。
- **C02 Flight**：航班搜索、供应连接、航班订单。
- **C03 Rail**：铁路 / 火车业务。
- **C04 Rental**：租车。
- **C05 Ride**：接送 / 网约车。
- **C06 Attraction**：景点 / 门票。
- **C07 Traveler Intelligence**：旅客画像、身份、偏好。
- **C08 GO AI Planning & Execution**：跨业务规划、执行编排、routing。
- **C09 GO Judgment & Trust**：判断、推荐可信度、trust。
- **C10 Unified Trips**：统一行程 / Journey。
- **C11 Transaction & Finance**：支付、交易、补偿。
- **C12 Platform / Security / Model Gateway**：平台、安全、可观测性、autonomy、workbench、Model Gateway。

横跨多个领域时，选“最终负责这个能力结果”的主 Cell，不要为了看起来像多 Agent 而重复发多个任务。

## 7.2 Formal Task Issue 格式

标题：

```text
Cxx · V<number>-R<number>-Cxx-<number> · <scope>
```

正文至少：

```text
Task: <真实任务>

Canonical source: <创建 Issue 当时 current main 的完整 40 位 SHA>
```

规则：

- Cell 和 task id 必须一致；
- 必须现场读取 current main；
- 新任务用新 task id / 新 Issue；
- 不要复制历史 Issue 的 SHA；
- Issue 创建完成后 Boss GPT 停止，不直接改 Runtime。

## 7.3 创建以后

```text
Formal Issue
→ Runtime
→ C01-C12 Generic Builder
→ inspect / edit / test
→ Draft PR
→ automatic C14
→ automatic C13
→ sealed round decision
→ STOP
```

老板不用：

- 登录 rt01；
- 手工 dispatch workflow；
- 手工给 Builder PR 创建 C14 Issue；
- 手工创建 C13；
- 手工运行 `deliver_review_round.py`；
- 盯着某个 AI 会话不能关。

---

# 8. 什么时候才手工创建 C14 Review Issue

只有一个场景：**要单独审核一个不是 Runtime Builder 刚产出的既有 PR。**

例如历史 PR、人工写 PR、Boss GPT 直接写出来的独立 candidate、或需要重新审某个 frozen head。

格式：

```text
C14 · REVIEW · <description>

Candidate PR: #<number>
Candidate SHA: <exact current PR head>
```

Runtime 自动完成 C14 → C13。

仍然不要手工创建 C13。

---

# 9. 最终停在哪里

即使：

```text
Builder = SUCCEEDED
C14 = PASS_SCOPED
C13 = PASS_SCOPED
round_decision = ACCEPT
```

也只代表：

```text
Draft PR + independent review evidence ready
```

不会自动：

- merge；
- deploy HK-STAGING；
- deploy Production；
- migration；
- 覆盖产品 Owner 的业务判断。

这是刻意保留的边界，不是 Runtime 未完成。

---

# 10. Boss GPT 推荐固定提示词

余总以后可以直接说：

```text
按 GO Persistent Runtime / 14 Cell 正式入口处理这个需求。

先读取 yuguangzhi3836-glitch/GO 当前 live main，
再读取 docs/runtime/BOSS_GPT_14_CELL_GUIDE.md。

根据需求选择最合适的一个 C01-C12 Cell，
创建一张新的 Formal Task Issue。

必须使用创建 Issue 当时的 current main 40 位 SHA。
不要直接改代码，不要手工创建 C13/C14 普通任务，
不要手工 dispatch Runtime。

Issue 创建完成后停止。
后续 Builder → Draft PR → C14 → C13 由 Persistent Runtime 自动推进。

需求：
<这里写需求>
```

---

# 11. 当前不阻断老板使用的已知项

这些都**不是交付 blocker**：

1. resident Issue consumer 每轮对 Builder-shaped open Issues 有有界处理数量；正常使用应把已完成验证/任务 Issue 关闭，避免长期堆积大量 open Formal Issues；
2. review worker 的 `--check` 有一个旧的单 target 展示字段可能显示 Responses workflow 名称，但实际 C14/C13 dispatch target 由 `workflow_files` 正确绑定；
3. 10/01 的历史 credential 文档描述的是当时只需要 Actions 权限的旧阶段；Builder 自动 review 以后 current client 还需要 Pull Requests Read + Contents Read。当前 rt01 已实测满足。

这些技术债不影响余总现在开始使用。

---

# 12. 最终交付状态

```text
Persistent Runtime                         DELIVERED
C01-C12 Formal Issue ingress              LIVE
C01-C12 Generic Builder                   LIVE / PROVEN
Builder → Draft PR                         LIVE / PROVEN
Builder → automatic C14                   LIVE / PROVEN
C14 → automatic C13                       LIVE / PROVEN
Crash/restart durable recovery            PROVEN
Exactly-once paid dispatch                PROVEN
Manual task handoff in normal path        0
Automatic merge / deploy                  NO (by design)
```

# Boss 一句话版本

> **告诉 Boss GPT 需求即可。Boss GPT 选 C01-C12 并创建一张 Formal Task Issue；后面的 Builder、Draft PR、C14、C13 全由 Persistent Runtime 自动完成。rt01 负责持续状态和恢复，不是常驻 14 个模型。最终 merge / deploy 仍然单独决定。**
