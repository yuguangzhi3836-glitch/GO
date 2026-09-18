# Command Center V1 — Global Single-Flight / Deployment Flow Guard 会诊后修订稿

> Status: DESIGN REVIEW V2 / NOT IMPLEMENTED  
> Date: 2026-09-18  
> PR: #203  
> Purpose: 给 WorkBuddy / ChatGPT / 人工继续做技术会诊。本文是当前收敛方向，不是最终实现裁决，不是 Execution Authority，也不代表已经安装或部署。  
> Principle: 只补当前真实缺口；优先复用现有 Bridge / Ledger / Request Visibility；不把 Command Center 重做成通用 Workflow Engine。

---

## 0. 当前收敛结论（仍待 WorkBuddy 二次复核）

当前较有把握的方向：

1. 现有 request_id / plan_id / task_id / executor attempt 解决的是“同一对象不要重复消费”，不能阻止两个不同但合法的业务 Request 交叉。
2. 最小的 CC 侧保护仍倾向放在现有 ledger.json 顶层，复用 Ledger.transaction() + fcntl.flock()。
3. Boss / Eason 发起的业务动作应共享一个 business exclusive slot：
   - HK_STAGING_TEST_PR
   - HK_STAGING_CANARY
   - HK_STAGING_VERIFY
   - HK_STAGING_DEPLOY
   - HK_STAGING_ROLLBACK
4. CONTROL_PLANE_HEALTH 是自动观测探针，当前倾向不占 business slot，也不因 business slot 被拒绝；但其与 HK Agent / Evidence publication 的实际并发安全仍请 WorkBuddy 再核。
5. DEPLOY 是跨 Request 的业务流程：
   - external CANARY
   - external preflight VERIFY
   - external DEPLOY
   - internal automatic post-deploy VERIFY
6. ROLLBACK 是：
   - external ROLLBACK
   - internal automatic post-rollback VERIFY
7. 当前倾向不增加 flow_id 字段，先利用 active_flow 自己记录 owner / candidate / stage，并只接受“同 owner + 当前正确下一动作”的 continuation；是否足够安全，请 WorkBuddy 重点复核。
8. BUSY / EXPIRED / candidate changed 等拒绝信息不应新造 request-results 体系；当前倾向复用已安装的 command-center-request-visibility-v1 / REQUEST_REJECTED 链路，并补充结构化诊断上下文。
9. 本轮仍不建议顺手加 Redis / SQL / queue / preemption / generic workflow engine / 新 daemon。
10. HK executor 是否需要第二道环境级 mutex，本稿不下最终结论：当前补丁先以 CC gate 为最小范围；WorkBuddy 继续检查是否存在必须同期处理的执行侧并发窗口。

---

## 1. 基线：实现前必须重新核 live

本 PR 创建时 base：

- canonical main: dc34ee5cabed7c6e93507d178fdd3a62a426399e

2026-09-18 会诊现场确认：

- live Bridge SHA256 对应 9b932745
- live channel 为 version 4 / PERSISTENT
- allowed actions 为：
  - HK_STAGING_VERIFY
  - HK_STAGING_TEST_PR
  - HK_STAGING_DEPLOY
  - HK_STAGING_ROLLBACK
  - HK_STAGING_CANARY
  - CONTROL_PLANE_HEALTH

因此真正落码前必须重新确认：

1. 当前 canonical main；
2. 当前 live /usr/local/libexec/go-boss-request-bridge 实际字节；
3. 当前 ledger.json；
4. 当前 post-action VERIFY 行为；
5. 当前 request-visibility 安装状态；
6. 当前 liveness producer / transport；
7. 当前 HK Agent transport / executor。

本文只描述设计方向，不可被当作 live truth。

---

## 2. 为什么仍需要这个补丁

当前系统已经有很多“防重复”：

- duplicate_request_id
- already-seen PR head
- plan one-time consumption
- approval one-time binding
- task_id uniqueness
- nonce / executor attempt budget
- publish-time recheck
- host drift precheck

但它们没有表达：

> 当前 Command Center 已经有一个业务意图正在处理，第二个业务意图不得取得执行资格。

例如：

    Boss:  CANARY A
    Eason: CANARY B
    Boss:  VERIFY
    Eason: VERIFY

即使每个 Request 单独都合法，也会造成两个业务意图串线。

本补丁要解决的是这个问题，而不是重做已有幂等体系。

---

## 3. 复用现有 Ledger，仍是当前首选

路径：

- control-plane/boss-deploy-request-v1/go-boss-request-bridge

现有：

- class Ledger
- Ledger.transaction()
- ledger.lock
- fcntl.flock(..., LOCK_EX)
- tmp + fsync + os.replace

当前倾向：

    {
      "version": 1,
      "requests": {},
      "active_flow": null
    }

有业务占用时可类似：

    {
      "active_flow": {
        "flow_type": "DEPLOY",
        "owner": "yuguangzhi3836-glitch",
        "candidate_image_id": "sha256:...",
        "candidate_contract_sha256": "...",
        "started_at": "...",
        "stage": "WAITING_FOR_PREFLIGHT_VERIFY",
        "current_task_id": "..."
      }
    }

字段应尽量少。

### 原子性原则

以下动作必须在同一 Ledger.transaction() / flock 里完成：

1. reconcile 现有 active_flow；
2. 检查是否可进入；
3. 必要时创建 / 推进 active_flow；
4. claim 当前 Request。

即使当前正常 tick 大多串行，也应防两个 Bridge tick / 人工进程重叠。

---

## 4. 业务独占 vs 观测探针

会诊后建议不再叫 MUTATING_ACTIONS，因为 CANARY / TEST_PR 并不修改业务环境。

### 4.1 BUSINESS_EXCLUSIVE_ACTIONS（当前倾向）

    HK_STAGING_TEST_PR
    HK_STAGING_CANARY
    HK_STAGING_VERIFY
    HK_STAGING_DEPLOY
    HK_STAGING_ROLLBACK

这些动作共享 business slot。

目标是：

> 同一时刻只允许一个人工 / GPT 业务意图推进，不允许另一条业务 Request 插队或串线。

### 4.2 OBSERVABILITY_ACTIONS（当前倾向）

    CONTROL_PLANE_HEALTH

会诊确认 live 有周期性的 liveness producer / transport。

如果 HEALTH 也拿长期 business slot，可能出现：

- 业务 flow 把探活 Request 拒绝；
- 探活先到时反过来把部署 Request 拒绝；
- 监控行为影响业务控制行为。

因此当前更倾向：

> HEALTH 不参与 active_flow 业务准入。

但这里仍需 WorkBuddy 二次核验：

- HEALTH 与 DEPLOY 在 HK Agent / Evidence push 层是否可能形成实际竞态；
- 现有 agent 是否天然顺序处理；
- 若有 Git push 竞争，是否已有机制处理。

本稿不把“HEALTH 一定可以完全并行”写死。

---

## 5. DEPLOY Flow：两种 VERIFY 必须明确区分

当前 DEPLOY 业务语义应写成：

    CANARY                         external Request
      ↓
    WAITING_FOR_PREFLIGHT_VERIFY
      ↓
    VERIFY                         external Request / preflight
      ↓
    WAITING_FOR_DEPLOY
      ↓
    DEPLOY                         external Request
      ↓
    POST_ACTION_VERIFY             Bridge internal continuation
      ↓
    terminal

### 5.1 external preflight VERIFY

这是 DEPLOY 前置条件。

当前 plan_derivation.py 会从 Bridge ledger 中选择新鲜、参数匹配的 VERIFY Task / Evidence 作为 preflight。

所以：

> 当一个 DEPLOY flow 已经存在时，不能让另一个 standalone VERIFY 随便插进来。

否则那个 VERIFY 可能成为后续 DEPLOY 派生计划时看到的“最新匹配 preflight”。

当前倾向：

- 没有 active deployment flow：standalone VERIFY 正常运行；
- 已有 active deployment flow：只接受当前 flow 期待的 VERIFY continuation；
- 其他 VERIFY Request：COMMAND_CENTER_BUSY。

### 5.2 internal post-action VERIFY

DEPLOY / ROLLBACK 成功后的 VERIFY 由 live Bridge 的 reconcile_post_action_verifies() 自动合成并发布。

它：

- 不是 Boss GPT 的新 Request；
- 不走外部 Request 准入；
- 不应被 active_flow 自己挡住。

因此 active_flow 在：

    DEPLOY_RUNNING
    → POST_ACTION_VERIFY_RUNNING
    → terminal

之间保持占用。

---

## 6. 当前倾向不增加 flow_id，但保留为待复核项

初稿建议新增 flow_id。

会诊后认为：为了最小改动，可以先尝试不改 Request schema。

理由：

- 当前 Request schema 是 exact-set；
- 加 flow_id 会波及 Request contract、生成器、文档、测试；
- 整个 CC 本来就只允许一个 active business flow。

当前倾向用：

    active_flow.owner
    active_flow.candidate
    active_flow.stage

判断 continuation。

例如：

    active_flow:
      owner = yuguangzhi3836-glitch
      candidate = X
      stage = WAITING_FOR_PREFLIGHT_VERIFY

    新 Request:
      action = VERIFY
      GitHub author = yuguangzhi3836-glitch
      active candidate 仍 = X

    当前倾向：允许 continuation

否则拒绝。

### 6.1 必须让 WorkBuddy 复核的现实问题

当前 DEPLOY Request 路径会获取 GitHub PR metadata 里的 approval_identity。

但 CANARY / VERIFY / TEST_PR 是否已经同样取得 GitHub author，需要按 live 代码重新确认。

如果没有：

> 为了记录 owner 并验证 continuation，可能需要把“读取 PR author”的现有逻辑最小泛化到业务 Request。

请 WorkBuddy 比较：

A. 不改 schema，泛化 PR author lookup；  
B. 增加一个最小 flow / parent 字段。

当前偏向 A，但不是最终裁决。

### 6.2 同一账号两个 Chat 的边界

不加 flow_id 意味着：

- 同一个 GitHub author；
- 同一个 candidate；
- 正好发送当前期待的下一动作；

可能被视为 continuation，即便来自另一个聊天窗口。

对于当前“老板账号 + 手机 GPT”的使用方式，这可能是可接受的最小化取舍。

但请 WorkBuddy 评估是否存在实际误推进风险。

---

## 7. Candidate 从头绑定到尾

CANARY flow 创建时，candidate 应从 CC 自己信任的事实取得，不从调用方取得：

- current candidate / admission；
- candidate contract；
- candidate image；
- expected current image。

active_flow 记录最小 candidate identity。

每次 continuation 前重新核：

> 当前 active candidate 是否仍等于 flow candidate？

若发生变化，当前倾向：

- 不继续原 flow；
- 返回明确原因，例如 FLOW_CANDIDATE_CHANGED；
- 原 flow 终止 / 过期；
- 新部署重新从 CANARY 开始。

具体是立即清 slot，还是记录 terminal reason 后下一 tick 清，由 WorkBuddy 根据 ledger / reconciliation 结构决定。

---

## 8. 时间窗口：900 秒不等于整个 Flow 只能等 15 分钟

live Request validation 有：

    max_age_seconds = 900

这表示：

> 一条已经创建出来的 Request，从自己的 requested_at 起，最多约 15 分钟内要被 Bridge 接受。

它不等于：

> CANARY 完成以后，整个 flow 只能再等 15 分钟。

因为下一阶段是一个 fresh Request，会有新的 request_id 和新的 requested_at。

因此当前仍倾向直接复用现有证据时效：

- CANARY Evidence：30 分钟；
- preflight VERIFY Evidence：5 分钟。

例如：

    CANARY SUCCESS
    ↓
    20 分钟后 GPT 创建一个新的 VERIFY Request
    requested_at = 当前时间
    ↓
    该 VERIFY 自己再受 900 秒 Request max-age 约束

Scheduled Task 应在准备推进下一阶段时才创建下一 Request。

不应提前创建一个 VERIFY PR 然后让它在 GitHub 上等 20 分钟。

---

## 9. active_flow 生命周期（当前建议）

### 9.1 DEPLOY

    CANARY_RUNNING
    ↓ success
    WAITING_FOR_PREFLIGHT_VERIFY
    ↓ accepted
    PREFLIGHT_VERIFY_RUNNING
    ↓ success
    WAITING_FOR_DEPLOY
    ↓ accepted
    DEPLOY_RUNNING
    ↓ deploy success / Bridge post-verify created
    POST_ACTION_VERIFY_RUNNING
    ↓ terminal
    CLEAR

### 9.2 ROLLBACK

    ROLLBACK_RUNNING
    ↓
    POST_ACTION_VERIFY_RUNNING
    ↓
    CLEAR

### 9.3 standalone single-step business action

例如：

- TEST_PR
- standalone CANARY
- standalone VERIFY

当前倾向：

    SINGLE_RUNNING
    ↓ terminal
    CLEAR

但 standalone CANARY 与“部署 flow 的第一步 CANARY”如何区分，仍是一个需要 WorkBuddy 再确认的协议问题。

可能选择：

1. Boss 的“部署”意图生成 CANARY 时，由 Bridge 根据当前规则把 CANARY 默认视为 deployment flow start；
2. 引入最小显式标记；
3. 取消 standalone CANARY 的独立语义，把 CANARY 一律视为 deployment preparation。

本稿不预先选死。

---

## 10. FAILURE / UNKNOWN：不能混为一谈

### 明确 terminal

若 CC 能从可信事实确认：

- SUCCESS
- 明确 FAILED
- flow evidence expired before next stage

可以进入 terminal / clear。

### Task 已发布，但执行结果未知

例如：

- Task 已签发；
- 没看到可信 terminal Evidence；
- publish / execution / evidence 状态存在歧义。

不能因为等了固定分钟数就假定没执行。

当前倾向：

    BLOCKED_REVIEW

并继续拒绝新的 business Request。

### 10.1 需要 WorkBuddy 特别核查

live HK Agent transport.py 的执行失败路径目前看起来会：

- claim_attempt()
- 本地 fail_attempt(...)

但并不一定为每一种执行失败都向 CC 发布 Signed failure Evidence。

如果这个事实成立：

> active_flow 不能假设“所有失败都会有 Signed Evidence”，否则某些真实失败会停在 UNKNOWN / BLOCKED_REVIEW。

请 WorkBuddy 核实：

1. 哪些 business action 的失败有远端可见 terminal Evidence；
2. 哪些只有 HK 本地 attempts DB；
3. 是否已有状态投影能把失败可靠带回 CC；
4. 若没有，本补丁是否接受“少数执行失败需要人工解除 slot”，还是需要一个极小的 failure-result 补强。

优先保持最小，不要因此直接扩成新状态平台。

---

## 11. Request rejection 可见性：优先复用 request-visibility-v1

会诊确认仓库已有：

- control-plane/command-center-request-visibility-v1/
- REQUEST_FACT_OBSERVATIONS
- REQUEST_REJECTED
- Bridge poll journal
- Phase 2 发布到 control bus / request-facts/live

其设计目的本来就是回答：

> 为什么我的 Request 没有变成 Task？

因此初稿建议的新 request-results 目录当前不再作为首选。

### 11.1 最小目标

新的 gate 至少需要产生机器可读 Reject token，例如：

- COMMAND_CENTER_BUSY
- FLOW_CANDIDATE_CHANGED
- FLOW_EXPIRED
- FLOW_CONTINUATION_MISMATCH
- FLOW_REQUIRES_OPERATOR_REVIEW

并确保现有 request-visibility contract 能分类 / 发布。

### 11.2 只有 reason token 可能不够

用户明确要求 BUSY 时告诉调用方：

- 当前在做什么；
- 当前触发人；
- 开始时间；
- 当前 Task；
- 为什么本 Request 没签发。

所以还需要 WorkBuddy 核：

> 当前 request fact schema 是否能携带结构化、非授权性的诊断上下文。

当前倾向类似：

    reason = COMMAND_CENTER_BUSY

    diagnostic:
      active_flow_type = DEPLOY
      active_owner = yuguangzhi3836-glitch
      active_stage = PREFLIGHT_VERIFY_RUNNING
      active_candidate_image_id = sha256:...
      active_started_at = ...
      active_task_id = ...

diagnostic 必须：

- 明确 non-authoritative；
- 不进入 Task 签名 / 执行；
- 不能反向影响 ledger；
- 只用于告诉 GPT / 人“为什么被拒绝”。

具体应扩 Bridge stdout、request visibility exporter、schema 还是 state publication，交给 WorkBuddy 找最小落点。

---

## 12. HEALTH：当前建议作为业务锁例外，但不要写成绝对并行保证

会诊发现：

- liveness producer 周期运行；
- HEALTH Request 走同一个 Request channel；
- live 已有大量 HEALTH Task。

因此初稿“HEALTH 也拿 slot”容易产生自伤。

当前偏向：

    business active_flow exists
    +
    HEALTH arrives
    => HEALTH 仍按现有探活路径处理，不改变 active_flow

    HEALTH exists
    +
    business Request arrives
    => HEALTH 不构成 COMMAND_CENTER_BUSY 的理由

但这只是 CC business admission 层的规则。

不代表 HK 上保证两个进程可以真正并行执行。

实际 HK 调度是否顺序、Evidence push 是否有竞争，WorkBuddy 还需核。

---

## 13. HK 第二道 mutex：本轮不做最终判断

初稿曾倾向增加 HK environment flock。

第一轮 WorkBuddy 会诊认为“不需要”。

复核 live hk-staging/source/agent/hk_agent/transport.py 后，可以确认：

- MAX_EXECUTOR_ATTEMPTS_PER_TASK = 1
- claim_attempt(task_id, nonce) 防的是同 Task 重试；
- 它不能单独证明两个不同 Task 永远不会并行。

因此本稿不接受“HK 并发绝无可能”这种绝对结论。

但为了最小改动，当前仍倾向：

> #203 的第一阶段只补 CC business gate，不顺手改 HK executor。

请 WorkBuddy 继续核：

- 当前 HK Agent service / timer 是否可重入；
- 两个 run_once() 能否同时存在；
- 如果能，是否有真实证据表明需要同期修；
- 若只是低概率 defense-in-depth，建议拆到后续独立小补丁。

---

## 14. Scheduled Task 的边界

Boss GPT / Scheduled Task 负责编排，不是 Execution Authority。

它只做：

1. 发当前阶段 Request；
2. 到点检查 Request fact / Task / Signed Evidence；
3. SUCCESS 后创建下一 fresh Request；
4. PENDING 就继续等；
5. REJECTED / EXPIRED / FAILED / BLOCKED_REVIEW 就停止并报告。

禁止：

- 没看到结果就重复发当前阶段；
- 重用 request_id；
- 复活 expired flow；
- 绕过 BUSY；
- 自动 retry DEPLOY / ROLLBACK；
- 猜测结果。

---

## 15. 当前最小实现候选（不是最终文件清单）

### A. control-plane/boss-deploy-request-v1/go-boss-request-bridge

可能包含：

- ledger 顶层兼容 active_flow；
- business admission gate；
- active_flow reconcile；
- owner / candidate / stage continuation check；
- post-action VERIFY 与 active_flow 收尾；
- structured BUSY diagnostic；
- self-tests。

### B. request visibility contract / exporter（视现状）

只在现有 REQUEST_REJECTED 还不能表达 BUSY diagnostic 时扩。

不新造平行 result 系统。

### C. Boss GPT guide / architecture docs

写清：

- business BUSY；
- HEALTH 例外；
- DEPLOY preflight VERIFY 与 post-action VERIFY 的区别；
- Scheduled Task 如何推进；
- 被拒绝后不盲重试。

### 当前尽量不动

- go_deploy_request.py plan derivation（除非 WorkBuddy 证明 gate 需要最小绑定补强）
- plan_derivation.py
- HK deploy runtime
- HK rollback runtime
- Evidence signer
- execution window
- Docker scope

---

## 16. 建议测试矩阵（修订）

最少应讨论 / 覆盖：

1. 两个 Bridge tick / 进程重叠抢空闲 slot，只能有一个 business flow 成功占位；
2. Boss CANARY flow 运行中，Eason CANARY -> BUSY；
3. Boss CANARY SUCCESS 后，Eason CANARY -> 仍 BUSY；
4. 当前 owner 的 expected preflight VERIFY -> 允许；
5. 其他 owner VERIFY -> BUSY；
6. 同 owner 但 candidate 已变化 -> 不继续；
7. active DEPLOY flow 时 standalone VERIFY 不能插入成为新的 preflight；
8. preflight VERIFY SUCCESS 后超 5 分钟才 DEPLOY -> flow 不再继续；
9. CANARY proof 超 30 分钟 -> flow 不再继续；
10. fresh Request 自己仍受 900 秒 max-age；
11. old Scheduled Task 不能复活已结束 / expired flow；
12. DEPLOY Task 已发布但 outcome unknown -> 不自动清 slot；
13. explicit terminal failure 的实际回传路径确认；
14. automatic post-deploy VERIFY 不被外部 gate 拦；
15. ROLLBACK + automatic post-rollback VERIFY 占用到最终 terminal；
16. TEST_PR / standalone VERIFY / standalone CANARY 作为单步 business action 时互斥；
17. HEALTH 不获取 business slot；
18. HEALTH 与 business action 的实际 HK / transport 共存行为不会制造新的执行风险；
19. BUSY Request 不产生 Signed Task；
20. Request Visibility 能让 Boss GPT 读到 reject reason、current owner、current action/stage、started_at、current task 和 human-readable message；
21. Bridge 重启后 active_flow 从 durable state 恢复；
22. prepared / publishing / ambiguous publish 时 fail-closed；
23. active_flow 不依赖内存锁；
24. 同 GitHub owner 的另一个 Chat 在“正确下一阶段”是否会被误认为 continuation，要有明确产品决定。

---

## 17. WorkBuddy 第二轮会诊问题

请基于当前 live 重新回答，不要把本稿当最终设计：

1. active_flow 放现有 Bridge ledger 是否仍是最小改法？
2. BUSINESS_EXCLUSIVE_ACTIONS 与 CONTROL_PLANE_HEALTH 例外是否会在 HK Agent / Evidence push 侧产生真实竞态？
3. standalone VERIFY 在 active deployment flow 中是否必须拦截？请用 plan_derivation.latest_pair() 的实际选择规则证明。
4. 不加 flow_id，只靠 owner + candidate + expected stage，是否足够？如果不够，最小补充字段是什么？
5. CANARY / VERIFY / TEST_PR 当前如何取得 GitHub author？泛化现有 PR metadata lookup 的改动面多大？
6. standalone CANARY 与 deployment-start CANARY 如何最小区分？
7. active_flow reconcile 应复用哪些现有 evidence / helper，哪些语义不能复用？
8. HK business action 失败是否都有 CC 可见的 terminal fact？没有的话，最小 recovery 是什么？
9. request-visibility-v1 是否能直接承载 structured BUSY diagnostic？最小需要改哪些文件？
10. 900 秒 Request max-age 与 30min CANARY / 5min VERIFY proof freshness 的实际组合，请给出时序测试确认。
11. HK executor 是否需要第二道 mutex？不要给绝对结论，按 live service / timer / transport 的可重入事实回答。
12. 最后给出最小文件变更清单，并指出哪些改动可以拆成第二阶段。

---

## 18. 验收口径（产品层）

如果最终实现成立，产品体验应接近：

> Command Center 同一时刻只推进一个人工 / GPT 业务意图。部署从 CANARY 开始后，只有该流程合法的下一阶段可以继续，其他业务 Request 在 Task 签发前被明确拒绝，并能从现有 GitHub 可见性链看到“当前谁在做什么、从什么时候开始”。CONTROL_PLANE_HEALTH 不应因为这个业务锁而破坏现有探活。流程过期不会自动继续，已签发但结果未知时不会被误认为 IDLE。

这是当前目标描述，不是对具体实现细节的最终裁决。

---

## 19. 明确不做

除非第二轮会诊证明“不做就无法满足上述目标”，否则本补丁不引入：

- Redis
- SQL 新状态库
- Job Queue
- FIFO 排队
- 优先级队列
- 抢占
- 自动取消
- 通用 Workflow Engine
- 新后台 daemon
- 自动 retry DEPLOY / ROLLBACK
- ChatGPT 持有签名权限
- 任意 shell / Docker 参数扩权

核心原则仍然是：

> 能复用现有 ledger / visibility / evidence 链，就不要再造一套系统。
