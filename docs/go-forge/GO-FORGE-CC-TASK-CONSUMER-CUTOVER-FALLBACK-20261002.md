# GO Forge — Command Center Task Consumer Cutover / Fallback Plan

**Date:** 2026-10-02  
**Status:** DRAFT / DESIGN ONLY / DO NOT EXECUTE YET  
**Owner:** chenzhenxi1-sudo  
**Purpose:** 记录 GO Forge 完成验证后，现有 Command Center 应如何退出 Task 主消费路径，同时保留为独立兜底部署路径。

---

## 1. 为什么单独留这个 PR

GO Forge 的目标不是改造现有 Command Center，也不是让 Forge 套在 CC 前面继续走旧流程。

但当 Forge 真正达到上线条件以后，现有 GitHub Task 总线的**主消费者必须发生切换**：

~~~text
现在：
Boss GPT
  ↓
go-control-tasks
  ↓
Old Command Center consumer
  ↓
HK-STAGING
~~~

切换后：

~~~text
Boss GPT
  ↓
go-control-tasks
  ↓
GO Forge
  ↓
HK-STAGING
~~~

因此，“Forge 不改 CC”不能理解为永远不碰 CC。

准确原则是：

> **不重构、不侵入、不改写 CC 的内部部署逻辑；Forge 验证通过后，只在 Task consumer 边界做一次可逆切换。**

这个 PR 专门记录这件事，避免未来因为时间过去、晨报/上下文切换而遗忘。

---

## 2. 老板侧保持完全不变

这是硬要求。

老板仍然使用现在已经习惯的入口和任务方式，例如：

~~~text
DEPLOY PRxxx
~~~

任务仍然进入现有 GitHub Task 总线：

**chenzhenxi1-sudo/go-control-tasks**

不得要求老板：

- 改新的 Task 格式；
- 改新的仓库；
- 改新的入口；
- 学新的 Forge 指令；
- 在 Forge / CC 之间人工选择后端。

**后端换成 Forge 应对老板透明。**

---

## 3. 最终形态：两条独立部署路径

GO Forge 上线后，目标架构是：

~~~text
                         ┌── GO Forge ─────────────→ HK-STAGING
Boss → go-control-tasks ─┤        PRIMARY
                         │
                         └── Old Command Center ───→ HK-STAGING
                                  FALLBACK
                                  (normally detached)
~~~

关键点：

1. **Forge = Primary deployment path**
2. **Old Command Center = Fallback deployment path**
3. 两者不是串联关系。
4. Forge 不需要把正常任务再送回 CC。
5. CC 不需要为了 Forge 重写内部 Gate / candidate / deploy 逻辑。
6. 正常状态下，只有 Forge 消费新的部署任务。
7. 老 CC 的 Task consumer 默认断开，但 CC 本体保留完整。

禁止形成：

~~~text
Forge → Command Center → HK
~~~

那会重新引入旧流程，失去 Forge 的目的。

---

## 4. Cutover 的唯一核心改动

Forge 通过全部上线验收后，只做一件核心事情：

> **把 go-control-tasks 的主消费权从 Old Command Center 切换给 GO Forge。**

概念上：

~~~text
BEFORE

go-control-tasks
      ↓
CC consumer = ENABLED
Forge consumer = DISABLED / NOT LIVE


AFTER

go-control-tasks
      ↓
Forge consumer = ENABLED
CC consumer = DISABLED
~~~

这里的“DISABLED”必须是**可逆停用**，不能删除旧代码、旧服务、旧配置或旧状态。

当前现场已知 CC 侧存在 Task/Request 消费相关 service/timer，例如 go-boss-request-bridge.service / timer。

实施 cutover 时必须先重新核对真实 live consumer，再决定具体停哪个 unit / 配哪个开关。

**不得仅凭旧 manifest 或历史文档直接操作。**

---

## 5. 不允许为了 Cutover 做的事情

这个 PR 不授权以下改造：

- 重写 Command Center；
- 重写 candidate governance；
- 改 projection/publication；
- 修改 CC 的固定 Gate 语义；
- 修改 HK Agent 以适配 Forge；
- 修改 deployctl 内部逻辑；
- 重做 ledger；
- 重做 Evidence；
- 修改老板 PR；
- 修改老板 Task 生成方式；
- 为了 Forge 引入新的审批系统；
- 为了 Forge 引入新的权限中心；
- 把 Forge 塞回 CC workflow。

如果以后发现 Forge **必须**依赖某个 CC 内部改造才能上线：

~~~text
STOP
↓
单独提出原因
↓
单独 PR
↓
Owner 决策
~~~

不得以“接入 Forge”为理由顺手修改。

---

## 6. Forge 上线前置条件

Task consumer **不得提前切换**。

至少满足：

### A. 本地实现通过

Forge worker 在本地完成：

- Task intake
- AI tool loop
- GitHub
- SSH / Shell
- audit
- recovery tracking
- verify
- dedupe
- crash/restart behavior

### B. Prompt 校准通过

从较自由的 Prompt V0 开始。

只针对真实失败逐条增加约束。

每个新增规则必须记录：

~~~text
REAL_FAILURE_PREVENTED = <actual observed failure>
~~~

### C. 历史回放通过

至少用 PR298 等真实历史任务做 replay，确认 Forge 能：

- 正确理解 Candidate；
- 正确读取真实/历史状态；
- 给出合理执行路径；
- 保持 Candidate identity；
- 保持审计与恢复路径。

### D. HK-STAGING 真实试运行通过

必须至少有真实 HK-STAGING 部署试验。

验收重点不是“是否按固定步骤走”，而是：

- Candidate 正确；
- 环境最终健康；
- mutation 全部可审计；
- recovery path 真实存在；
- final verify 可信；
- Production 未触碰；
- boss PR 未修改。

只有满足这些条件，才进入 consumer cutover。

---

## 7. Cutover 执行原则

实际切换当天：

### STEP 1 — Freeze

确认：

- Forge 无测试残留；
- CC 当前无 in-flight mutation；
- HK-STAGING 无进行中的部署；
- Task bus 没有一条任务被两套系统同时领取。

### STEP 2 — Detach Old CC Consumer

以**最小、可逆方式**停止旧 CC 对新 Task 的消费。

优先级：

1. disable/stop 对应 consumer timer/service；
2. 或使用一个明确的 consumer enable/disable 配置；
3. 不删除 unit；
4. 不删除代码；
5. 不删除 ledger；
6. 不清空历史状态。

### STEP 3 — Enable Forge Consumer

启用 forge-worker.service，让 Forge 从同一个 go-control-tasks 接收新任务。

### STEP 4 — Prove Single Consumer

必须证明：

~~~text
new Task
  ↓
Forge sees it
CC does NOT consume it
~~~

这是 cutover 成功的关键判据。

### STEP 5 — Run First Production-Like HK-STAGING Task

执行一条真实部署任务。

确认：

- Boss 输入方式未改变；
- Task repo 未改变；
- Forge 完成任务；
- CC 没有抢任务；
- HK 无双 mutation；
- audit/evidence 完整。

---

## 8. Fallback：老 CC 怎么救场

Old Command Center 保持完整的目的，就是 Forge 出现严重问题时可以人工切回。

切换顺序必须是：

~~~text
1. STOP / DISABLE Forge consumer
2. 确认 Forge 当前无 in-flight mutation
3. 确认 HK-STAGING 达到一个已知状态
4. ENABLE Old CC consumer
5. 再允许新 Task 进入旧 CC 路径
~~~

禁止：

~~~text
Forge 正在改 HK
+
CC 同时开始改 HK
~~~

### FALLBACK 原则

> **Fallback 是 consumer ownership 的切换，不是两套系统同时抢任务。**

---

## 9. 恢复 Forge 后怎么切回来

Old CC 救场结束后：

~~~text
1. 先停止新 Task
2. 等 CC 当前任务 terminal
3. DISABLE CC consumer
4. 确认 HK 无 mutation
5. ENABLE Forge consumer
6. 发一条测试 Task 验证单消费者
7. 恢复正常 Task 流量
~~~

同样不需要老板改变任何操作。

---

## 10. 两道保险的正式定义

### Primary

**GO Forge Autonomous AI Operator**

特点：

- fresh AI session / clean context；
- 自己调查 Candidate 与真实环境；
- 自己选择工具和执行方式；
- 强制 audit；
- 强制 recovery；
- hard red lines；
- 以工程判断完成部署。

### Fallback

**Existing GO Command Center**

特点：

- 保留当前已有实现；
- 平时不消费新 Task；
- Forge 不可用时人工切回；
- 不要求为了 Forge 持续跟随改造。

---

## 11. 为什么不做 Active/Active

明确不做：

~~~text
Forge consumer = ON
CC consumer = ON
~~~

原因不是把 AI 当敌人，而是这个方案没有现实收益，却引入：

- 同一 Task 双消费；
- 同一环境并发 mutation；
- attempt budget 消耗；
- 两套状态机互相看不懂；
- recovery source 被另一条路径消耗；
- 排障时无法确定“谁改了现场”。

因此：

> **两道保险 = 两套独立能力 + 单一当前 owner。**

不是两个 owner 同时工作。

---

## 12. 实施时需要留下的开关

最终实现必须让当前主消费者一眼可见。

例如形成一个简单的 operational fact：

~~~text
TASK_CONSUMER_OWNER = FORGE
~~~

或：

~~~text
TASK_CONSUMER_OWNER = COMMAND_CENTER
~~~

具体实现方式在 cutover 前根据 live system 选择。

要求只有三个：

1. 人能快速看懂；
2. 切换可逆；
3. 不需要修改老板入口。

不要为了这个 fact 新建数据库或审批系统。

---

## 13. Rollback of Cutover

如果 Forge 上线后发现问题：

~~~text
ROLLBACK TARGET:
Task consumer ownership only
~~~

不是回滚整个 GO 系统。

最小回滚：

~~~text
stop forge-worker
↓
verify no in-flight Forge mutation
↓
restore old CC consumer
↓
verify one Task enters CC
~~~

因为 CC 内部没有被 Forge 改造，所以 fallback 能保持低成本。

---

## 14. 当前状态

截至本 PR 创建时：

~~~text
FORGE_READY_FOR_CUTOVER = NO
CUTOVER_AUTHORISED      = NO
CC_CONSUMER_CHANGE      = NOT EXECUTED
HK_CHANGE               = NONE
PRODUCTION_CHANGE       = NONE
~~~

本 PR 只是一个未来实施提醒和设计冻结点。

**不得因为这个 PR 存在就提前切流。**

---

## 15. 最终一句话

> **老板与 GitHub Task 入口保持不变；GO Forge 验证成熟后，在 Task 总线下面把主消费者从旧 Command Center 切到 Forge。旧 CC 不删除、不重构，平时断开，Forge 出问题时人工切回，且任何时刻同一环境只能有一个 mutation owner。**
