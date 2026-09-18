# Command Center V1 — Global Single-Flight / Deployment Flow Guard 设计会诊稿

> Status: DESIGN ONLY / NOT IMPLEMENTED  
> Date: 2026-09-18  
> Purpose: 给 WorkBuddy / ChatGPT / 人工审查做技术会诊，不是执行授权，不代表已经安装或部署。  
> Scope: 只讨论 Command Center 的“同一时刻只处理一个外部业务意图”与部署三段串联，目标是最小改动，不把 CC 重做成通用 Workflow Engine。

## 0. 先说结论

当前缺口不是“没有幂等”，而是：

1. 现有 ledger / request_id / plan_id / task_id / executor attempt 能防同一对象重复消费；
2. 但没有一个“整个 Command Center 当前被谁占用”的全局单通道；
3. DEPLOY 又需要 CANARY -> VERIFY -> DEPLOY 三个独立 Request；
4. 只锁单个 Request 会允许两个部署意图在三个阶段之间交叉穿插；
5. Bridge 的 Reject 原因目前主要停留在本机处理结果/日志，Boss GPT 若只看到“没有 Task”，无法知道为什么被拒绝。

建议最小修补方向：

- 复用现有 Ledger.transaction() + fcntl.flock()；
- 在现有 ledger 中增加一个很小的 active_flow / active_slot；
- 仅部署三段使用跨 Request 的 flow_id；
- 其他动作仍按单步生命周期处理；
- 任何非当前 flow 的外部 Request 在签发 Task 之前明确拒绝；
- 拒绝结果必须写到 Boss GPT 能从 GitHub 读取的位置；
- 不做排队、不做抢占、不做自动重试、不引入 Redis/SQL/新 daemon；
- 已签发但结果未知时 fail-closed，不因超时自动释放；
- DEPLOY / ROLLBACK 后现有自动 post-action VERIFY 属于内部 continuation，不应被自己的全局占用拦截。

## 1. 基线提醒：实现前必须重新核 live

本 PR 只新增设计文档，分支从创建时的 canonical main 建立。

创建本设计 PR 时看到：
- canonical main: dc34ee5cabed7c6e93507d178fdd3a62a426399e

但 2026-09-18 的只读 live 审计报告显示，实际安装的关键 Bridge / deploy 模块字节对应：
- origin/fix/hk-media-topology-v2-20260918 @ 9b932745

且 live channel 的 allowed_actions 已包含 6 项：
- HK_STAGING_VERIFY
- HK_STAGING_TEST_PR
- HK_STAGING_DEPLOY
- HK_STAGING_ROLLBACK
- HK_STAGING_CANARY
- CONTROL_PLANE_HEALTH

所以后续真正编码前，WorkBuddy 必须重新核：
1. 当前 canonical main 是否已经吸收 9b932745 或后续版本；
2. 当前 live /usr/local/libexec 实际字节；
3. 当前 ledger / post-action verify / rollback 行为；
4. 不得把本设计 PR 的 base snapshot 当 live execution authority。

## 2. 当前已有基础（尽量复用）

### 2.1 Ledger 已有进程间排他

路径：
- control-plane/boss-deploy-request-v1/go-boss-request-bridge

现有：
- class Ledger
- Ledger.transaction()

当前做法：
- ledger.lock
- fcntl.flock(..., LOCK_EX)
- ledger.json 原子替换 + fsync

这个锁已经适合保护“检查 active_flow + 占位 + claim Request”的原子读改写。

不建议再引入第二套 CC 侧锁服务。

### 2.2 当前 Request 已有 durable states

persistent_process() 已经有：
- prepared
- publishing
- published
- already_seen
- duplicate_request_id
- ambiguous_publish_requires_operator_review

DEPLOY 侧还有：
- plan/approval one-time consumption
- plan_id / approval idempotency
- publish 前重新核验
- task_id collision protection

HK 侧还有 executor attempt / nonce 一次性控制。

这些继续保留；active_flow 不是替代它们，而是补“不同合法 Request 之间不得交叉”的一层。

## 3. 用户期望的业务语义

### 3.1 总原则

Command Center 同一时刻只允许一个“外部业务意图”占用执行通道。

如果已有一个任务/流程正在处理：
- 后来的外部 Request 不排队；
- 不自动延迟执行；
- 不静默丢弃；
- 不签发正式 Task；
- 必须返回明确 BUSY 原因，告诉调用方当前在做什么、谁触发、何时开始。

### 3.2 不等于“只锁单个 JSON Request”

DEPLOY 的业务意图是一个整体：

CANARY -> VERIFY -> DEPLOY -> automatic post-deploy VERIFY

如果 CANARY 完成就完全释放全局占用，则可能出现：

Boss flow A: CANARY SUCCESS  
Eason flow B: CANARY SUCCESS  
Boss flow A: VERIFY SUCCESS  
Eason flow B: VERIFY ...

虽然任何一秒只有一个 Request 在执行，但两个部署意图已经串线。

因此 DEPLOY 必须有“跨三段 Request 的占用”。

## 4. 建议的最小数据结构

不新增数据库。

直接在现有 ledger.json 顶层增加一个可空对象：

```json
{
  "version": 1,
  "requests": {},
  "active_flow": {
    "flow_id": "deploy-...",
    "flow_type": "DEPLOY",
    "owner": "yuguangzhi3836-glitch",
    "candidate_id": "...",
    "started_at": "...",
    "stage": "CANARY_RUNNING",
    "current_task_id": "...",
    "stage_expires_at": "..."
  }
}
```

字段只保留判断所需最小集合。

建议不要把几十个业务字段复制进去。

## 5. flow_id：建议只解决部署三段关联

### 5.1 为什么需要显式 flow_id

仅靠：
- GitHub author
- candidate
- action 顺序

无法可靠区分“同一个老板账号的另一个 ChatGPT 对话”是否是原流程的 continuation。

所以建议给部署链三段 Request 增加一个很小的关联标识：
- flow_id

同一次部署：
- CANARY: flow_id=A
- VERIFY: flow_id=A
- DEPLOY: flow_id=A

每一段仍有自己的 fresh request_id。

### 5.2 不建议用 request_id 命名约定偷偷编码关联

例如靠前缀解析：
- deploy-A-canary-...
- deploy-A-verify-...

虽然少一个字段，但协议隐式、易误判、后续更难审计。

显式 flow_id 更小、更直观。

### 5.3 WorkBuddy 需要会诊的实现细节

当前 Request schema 对字段集合做 exact-set 校验：
- 普通动作五字段
- TEST_PR 六字段

因此增加 flow_id 会改 Request contract。

请会诊：
- flow_id 是否只对 CANARY/VERIFY/DEPLOY 的 deployment-flow 形态允许；
- standalone CANARY / standalone VERIFY 是否继续保持旧五字段；
- 或是否用一个更小的 parent_request_id 方案。

目标优先级：
1. 不误把另一个 Chat 识别成 continuation；
2. schema 变更尽量局部；
3. 不破坏 standalone VERIFY / TEST_PR / HEALTH。

## 6. 最小状态，不做通用状态机

只需要以下业务阶段：

### DEPLOY flow

1. CANARY_RUNNING
2. WAITING_FOR_VERIFY
3. VERIFY_RUNNING
4. WAITING_FOR_DEPLOY
5. DEPLOY_RUNNING
6. POST_VERIFY_RUNNING
7. terminal -> active_flow cleared

不需要：
- PAUSED
- RESUMING
- PRIORITY
- QUEUED
- PREEMPTED
- RETRYING

### ROLLBACK flow

1. ROLLBACK_RUNNING
2. POST_VERIFY_RUNNING
3. terminal -> clear

### 单步外部动作

- TEST_PR
- standalone VERIFY
- standalone CANARY（如果保留）
- CONTROL_PLANE_HEALTH

这些只在 Task 未终结期间占用；结束即释放，不跨 Request 保留。

## 7. 核心准入规则

在 persistent_process() 内、现有 Ledger.transaction() 的同一排他事务里做：

1. reconcile 当前 active_flow；
2. 判断新 Request 是否可进入；
3. 必要时创建/推进 active_flow；
4. 再 claim / prepare 当前 Request。

伪规则：

```text
if no active_flow:
    accept one legal external request
    if it starts deployment flow:
        create active_flow
else:
    if request is the exact allowed continuation
       of active_flow
       (same flow_id + same owner + correct next action + same candidate binding):
        accept
    else:
        reject COMMAND_CENTER_BUSY
        do not sign Task
```

### 必须原子

“检查空闲”和“设置 active_flow”必须在同一次 ledger flock 事务里。

禁止：
- 先无锁检查 idle
- 后面再另一次写 active_flow

否则两个并发 Request 仍可能同时通过检查。

## 8. active_flow 怎么推进：不要新 daemon

不建议加后台 workflow worker。

最小做法：
- 在 Bridge 每次 tick / 每次处理 Request 前，调用一个小 helper，例如 reconcile_active_flow()；
- 使用现有 Evidence 读取/签名验证能力判断 current_task_id 是否已有 terminal Evidence。

例如：

CANARY_RUNNING:
- 无 terminal Evidence -> 仍 BUSY
- SUCCESS -> WAITING_FOR_VERIFY
- FAILED -> flow FAILED，清 slot
- task 已签发但结果不明/证据异常 -> BLOCKED_REVIEW，不清 slot

WAITING_FOR_VERIFY:
- 只允许同 flow 的 VERIFY
- 超过 CANARY 证据现有有效期 -> FLOW_EXPIRED，清 slot

VERIFY_RUNNING:
- 同理

WAITING_FOR_DEPLOY:
- 只允许同 flow 的 DEPLOY
- 超过 VERIFY 证据现有 5 分钟有效期 -> FLOW_EXPIRED，清 slot

DEPLOY_RUNNING:
- 无 terminal Evidence -> BUSY
- SUCCESS -> 进入/等待既有 automatic post-deploy VERIFY
- FAILED -> terminal
- ambiguous -> BLOCKED_REVIEW

这样没有新 service，也没有“CC 自己自动发 CANARY/VERIFY/DEPLOY”的工作流引擎。

Boss GPT 仍然负责三段 Request 的编排。

## 9. 超时原则

### 9.1 只对“等待下一段 Request”使用现有证据有效期

现有规则：
- CANARY evidence: 30 分钟
- VERIFY evidence: 5 分钟

可以直接复用，不再发明新 lease 时间。

例如：
- CANARY SUCCESS 后 30 分钟内没等到同 flow VERIFY -> flow expired，释放；
- VERIFY SUCCESS 后 5 分钟内没等到同 flow DEPLOY -> flow expired，释放。

过期以后：
- 旧 Scheduled Task 再来不得复活旧 flow；
- 必须重新从 CANARY 开始。

### 9.2 已签发 Task 但结果未知，不能靠时间自动释放

这是关键安全边界。

如果正式 Task 已发布，CC 不知道 HK 到底执行没执行：
- 不得因为“过了 10/20/30 分钟”自动把 slot 当空闲；
- 标记 BLOCKED_REVIEW / UNKNOWN；
- 新外部业务 Request 继续明确拒绝；
- 等 signed terminal Evidence 或人工会诊。

UNKNOWN != IDLE。

## 10. Candidate 必须从头绑定到尾

部署 flow 创建时记录 candidate identity。

后续 VERIFY / DEPLOY 必须仍指向同一候选事实。

若 active candidate / candidate contract 已变化：
- 拒绝 continuation；
- reason: CANDIDATE_CHANGED / FLOW_CANDIDATE_CHANGED；
- 旧 flow 作废；
- 重新从 CANARY 开始。

禁止：
- CANARY 测 X
- 中间 candidate 变 Y
- DEPLOY Y

## 11. CONTROL_PLANE_HEALTH

当前 live action contract 包含 CONTROL_PLANE_HEALTH。

设计建议保持最简单：

- CC 空闲时，HEALTH 可作为普通单步只读任务执行；
- HEALTH 一旦开始，也占用当前 slot，直到 terminal；
- 如果业务 flow 已占用，新的 HEALTH Request 直接拒绝/跳过，不排队；
- 如果 HEALTH 已经先开始，此时来了 DEPLOY/CANARY/VERIFY 等，也不抢占 HEALTH，明确 BUSY 拒绝；
- HEALTH 不创建跨阶段 active_flow；
- liveness producer 后续自己下一个 bucket 再探活即可。

不做“健康检查低优先级抢占”系统。

## 12. TEST_PR / standalone VERIFY / standalone CANARY

这些保持单步：

Request accepted -> Task published -> terminal Evidence -> release

它们不应占用一个“等待下一 Request”的 deployment flow。

但在它们执行期间：
- 其他外部 Request 一律 BUSY reject。

这样满足“CC 同时只干一件事”。

## 13. ROLLBACK

live revision 已有 HK_STAGING_ROLLBACK，并且 ROLLBACK 后会自动 post-action VERIFY。

建议把它视为一个短 flow：

ROLLBACK -> automatic post-rollback VERIFY -> terminal -> release

ROLLBACK 不排队、不抢占当前 DEPLOY flow。

如果已有 active flow：
- 新 ROLLBACK 也 BUSY reject。

不做“回滚优先级高于部署”的抢占规则，除非以后明确提出。

## 14. Automatic post-action VERIFY 必须绕过外部 BUSY gate

现有 Bridge 的 DEPLOY / ROLLBACK 成功后会内部合成并发布 VERIFY。

这是当前 flow 的内部 continuation，不是新的外部 Request。

因此：
- 不得走“有 active_flow 就 reject”的外部准入规则；
- 仍须保留它原有的签名、Evidence 绑定和 idempotency；
- active_flow 直到这个 post-action VERIFY terminal 后才最终释放。

否则会发生“DEPLOY 自己把自己的自动 VERIFY 挡掉”。

## 15. 明确拒绝：这是本补丁的功能要求，不是日志优化

Boss GPT 不能只看到：
- Request PR 存在
- 但没有 Signed Task

它必须知道为什么没签发。

建议增加一个 GitHub 可读的 Request Result 对象，例如：

```
request-results/<request_id>.json
```

示例：

```json
{
  "schema_version": "1",
  "request_id": "...",
  "status": "REJECTED",
  "reason": "COMMAND_CENTER_BUSY",
  "message": "Command Center 当前已有流程正在执行，本次请求未签发，请等待当前流程结束后重新提交。",
  "active_flow": {
    "flow_id": "...",
    "flow_type": "DEPLOY",
    "owner": "yuguangzhi3836-glitch",
    "stage": "VERIFY_RUNNING",
    "candidate_id": "...",
    "started_at": "...",
    "current_task_id": "..."
  }
}
```

要求：
- 这是回执，不是 Signed Task；
- 不具备执行授权；
- 不得让调用者通过 result 写入影响 active_flow；
- 同 request_id result 幂等，不覆盖不同内容；
- Scheduled Task / Boss GPT 能从 GitHub 直接读到。

WorkBuddy 请会诊：
- 使用同一个 go-control-tasks 仓库的 request-results/ 是否最小；
- 是否能复用现有 tasks writer key / publish helper，而不增加新 credential；
- 是否更适合 PR comment（若需要新 API write token，则通常反而更复杂）。

偏向：复用现有 Git writer，在同控制仓库写结果文件。

## 16. Scheduled Task 的边界

Scheduled Task 只负责：
1. 重新醒来；
2. 查 Request Result / Signed Task / Signed Evidence；
3. 当前阶段 SUCCESS 时创建下一合法 Request；
4. PENDING 时继续等；
5. FAILED / REJECTED / EXPIRED 时停止并报告。

禁止 Scheduled Task：
- 因为没看到结果就重复提交同一阶段；
- 重用旧 request_id；
- 复活 expired flow；
- 绕过 BUSY；
- 自动 retry DEPLOY。

## 17. 明确不做

本补丁不应引入：

- Redis
- SQL 状态库
- Job Queue
- FIFO 排队
- 优先级队列
- 抢占
- 自动取消别人任务
- 通用 Workflow Engine
- 新后台 daemon
- 多环境资源调度
- 自动重试 DEPLOY / ROLLBACK
- 任意 shell / executor 参数扩权
- ChatGPT 持有签名权限

## 18. 最小改动位置建议（只给方向，不预设最终函数名）

主要候选：
- control-plane/boss-deploy-request-v1/go-boss-request-bridge
  - Ledger 结构兼容
  - persistent_process() 外部准入
  - reconcile active flow
  - BUSY result publish
  - post-action VERIFY 与 active_flow 的生命周期衔接

可能需要小改：
- Request schema validation（若采用 flow_id）
- tests/test_deploy_entry.py / Bridge self-tests
- BOSS_GPT_REQUEST_GUIDE.md
- 当前 architecture / contract 文档

尽量不动：
- HK executor runtime
- Docker 部署实现
- Evidence signer
- existing plan derivation 逻辑

除非 WorkBuddy 证明只做 CC gate 仍存在无法接受的执行侧并发漏洞。

## 19. 必须有的测试场景

最少覆盖：

1. 两个进程同时抢空闲 slot -> 只有一个接受；
2. Boss flow A CANARY 运行时，Eason CANARY B -> B 明确 BUSY；
3. A CANARY SUCCESS 后，B CANARY -> 仍 BUSY；
4. A 同 flow VERIFY -> 允许；
5. 错 flow_id VERIFY -> 拒绝；
6. 同 flow 但错 owner -> 拒绝；
7. 同 flow 但 candidate 已变化 -> 拒绝；
8. VERIFY SUCCESS 后超 5 分钟再 DEPLOY -> FLOW_EXPIRED；
9. 旧 Scheduled Task 不能复活 expired flow；
10. DEPLOY Task 已发布但 Evidence unknown -> slot 不释放；
11. explicit FAILED Evidence -> 正确 terminal / release；
12. automatic post-deploy VERIFY 不被 BUSY gate 拦；
13. ROLLBACK + post-verify 占用到 terminal；
14. HEALTH 在业务 flow 中 -> 明确拒绝/跳过；
15. HEALTH 已运行时新业务 Request -> 明确 BUSY；
16. rejected Request 没有 Signed Task；
17. GitHub-visible rejection result 内容包含：
    - reason
    - active flow/action
    - owner
    - started_at
    - current task
    - human-readable message
18. Bridge 进程重启后 active_flow 仍可恢复/重算，不出现“内存锁丢失”。

## 20. WorkBuddy 会诊问题

请不要直接按本文编码，先回答：

1. 在当前最新 live / current branch 上，active_flow 放现有 ledger 是否确实是最小、安全方案？
2. active flow reconciliation 最适合复用哪个现有 Evidence reader / post-action verify helper？
3. flow_id 最小 schema 改法是什么，如何保持 standalone VERIFY/CANARY 兼容？
4. GitHub-visible rejection result 最小实现是 result file 还是 PR comment？
5. 当前 liveness producer 是否会因 BUSY rejection 产生不可接受的噪音？
6. active_flow 在 prepared / publishing / ambiguous publish 崩溃场景如何保持 fail-closed？
7. 是否真的需要 HK executor 再加物理 mutex？若不需要，请给出现有单 executor / transport 的事实依据；若需要，说明能否作为独立第二阶段，不扩大本 PR 设计范围。
8. 当前 main 与 live 9b932745/后续版本的差异中，哪些会改变本设计？
9. 给出“最小文件变更清单”，避免顺手重构。

## 21. 验收口径

补丁完成后，产品层应能用一句话描述：

> Command Center 同一时刻只服务一个外部业务意图。部署从 CANARY 开始后，直到 VERIFY、DEPLOY 和自动部署后 VERIFY 完成，其他外部请求都不会取得执行资格；它们会在 Task 签发前被明确拒绝，并从 GitHub 得到“当前谁在做什么、从什么时候开始”的可读原因。流程过期不会自动继续，已签发但结果未知时不会误释放。

这就是本设计稿的边界。不要把它扩成通用调度平台。
