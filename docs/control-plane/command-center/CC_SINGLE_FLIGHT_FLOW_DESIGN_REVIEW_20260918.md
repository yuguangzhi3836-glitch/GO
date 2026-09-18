# Command Center V1 — Single-Flight / Deployment Flow Guard 最终设计收口稿

> Status: DESIGN CLOSED EXCEPT ONE PRODUCT CHOICE / NOT IMPLEMENTED
> Date: 2026-09-18
> PR: #203
> Scope: 设计与技术会诊记录。不是 Execution Authority，不代表已经安装、部署或修改 live。
> Goal: 用最小改动阻止不同业务 Request 串线；复用现有 Bridge / Ledger / Request Visibility；不造通用 Workflow Engine。

## 0. 结论

经过两轮完整会诊和一次窄范围复核，以下事实已足够支撑实现设计：

1. active_flow 放现有 Bridge ledger.json 顶层，继续复用 Ledger.transaction() + fcntl.flock()，是当前最小方案。
2. 不新增 Redis、SQL、Queue、新 daemon、抢占、优先级或自动重试。
3. 不新增通用 flow_id。业务 continuation 当前采用 GitHub verified author + CC 自己派生的 candidate identity + expected stage。
4. CANARY / VERIFY / TEST_PR 需要最小泛化现有 GitHub PR metadata / author lookup；Request JSON schema 本身不因此改变。
5. DEPLOY flow 必须区分 external CANARY、external preflight VERIFY、external DEPLOY、internal automatic post-action VERIFY。
6. active DEPLOY flow 中，其他 standalone VERIFY 必须被阻止；plan_derivation.latest_pair() 会选最新匹配 VERIFY，允许插入会污染 preflight lineage。
7. CONTROL_PLANE_HEALTH 不进入 business active_flow。
8. live HK Agent 正常生产入口已通过约 41 小时 journal 证明并发深度恒为 1；当前不新增 HK mutex。
9. BUSY / EXPIRED 等第一阶段先复用现有 request-visibility-v1 的 REQUEST_REJECTED / reason token。
10. 现有 request fact schema 无位置承载 structured BUSY diagnostic；“当前谁、哪个 Task、哪一阶段”等详细诊断拆为第二阶段，不扩大核心补丁。
11. fresh Request 自己受 900s max-age；这不缩短 CANARY 30min proof freshness。preflight VERIFY proof freshness 仍为 5min。
12. 已签发但 outcome 不明时 fail-closed；不能因超时把 UNKNOWN 当 IDLE。

只剩一个产品选择尚未替用户决定：

standalone CANARY 与 deployment-start CANARY 在当前 Request / Task / 关联层完全不可区分。若不改 schema，最省代码的规则是“所有 CANARY 都开启 deployment flow”；但这会让仅想跑一次 CANARY 的场景也占住业务 slot 等待下一阶段。是否接受这个行为，需要产品侧明确决定。详见第 8 节。

## 1. Live 基线事实

设计 PR 创建时 base：

- main @ dc34ee5cabed7c6e93507d178fdd3a62a426399e

2026-09-18 会诊时 live Bridge 字节对应：

- 9b932745

live allowed actions：

- HK_STAGING_VERIFY
- HK_STAGING_TEST_PR
- HK_STAGING_DEPLOY
- HK_STAGING_ROLLBACK
- HK_STAGING_CANARY
- CONTROL_PLANE_HEALTH

真正落码前仍必须重新确认当时的 canonical main、live Bridge SHA256、live ledger、request-visibility、liveness producer/transport、HK Agent service/timer。

设计文档不是 live authority。

## 2. 要修的真实缺口

现有系统已经保护 duplicate request id、already-seen PR head、plan / approval one-time use、task id / nonce、executor attempt budget、publish-time recheck 和 host drift checks。

但这些不能阻止两个不同但合法的业务 Request 交叉。

示例：

Boss: CANARY A
Eason: CANARY B
Boss: VERIFY
Eason: VERIFY

本补丁只增加一个 durable business slot，确保同一时刻只有一个人工 / GPT 业务意图可以推进。

## 3. Ledger / active_flow

继续使用现有 ledger.lock、fcntl.flock(LOCK_EX)、atomic save / fsync / replace。

顶层兼容增加 active_flow。

建议最小字段：

- flow_type
- owner
- candidate_image_id
- candidate_contract_sha256
- stage
- started_at
- current_task_id

不复制几十个业务字段。

检查 slot、创建/推进 slot、claim Request 必须处于同一个 Ledger.transaction()。

## 4. Business slot 范围

### 4.1 Business actions

人工 / GPT 业务操作：

- TEST_PR
- CANARY
- VERIFY
- DEPLOY
- ROLLBACK

原则：

active business flow 存在时，除合法 continuation 外，新的业务 Request 在签 Task 前拒绝。

### 4.2 HEALTH 例外

CONTROL_PLANE_HEALTH 不取得 business slot，也不构成 COMMAND_CENTER_BUSY 的原因。

原因：

- live 有周期性 liveness producer；
- HEALTH 是观测探针；
- 若 HEALTH 与业务共用长期 slot，会让监控与业务互相阻塞。

### 4.3 HK 并发复核结论

窄范围复核确认：

- go-hk-agent.service: Type=oneshot, RemainAfterExit=no
- timer: OnUnitActiveSec=60s
- 正常生产入口唯一
- 约 41h journal：1709 完整 session，多次 session >60s / >120s，max concurrent depth = 1

因此当前正常生产入口不会因为 HEALTH 与 business Task 同时存在而启动两个 HK Agent 主进程。

本补丁不增加 HK mutex。

残余人为绕过，例如直接 shell 启第二个二进制，不属于本补丁解决范围。

## 5. DEPLOY lifecycle

流程：

CANARY external Request
→ WAITING_FOR_PREFLIGHT_VERIFY
→ PREFLIGHT VERIFY external Request
→ WAITING_FOR_DEPLOY
→ DEPLOY external Request
→ POST_ACTION_VERIFY Bridge internal continuation
→ terminal / clear

### 5.1 Preflight VERIFY 必须独占 lineage

plan_derivation.latest_pair() 按 issued_at 取最新匹配 Task；newest matching pair 决定，非 SUCCESS 不回退旧成功结果。

因此 active DEPLOY flow 期间：

- 当前合法 preflight VERIFY：允许
- 其他 standalone VERIFY：BUSY reject

否则外部 VERIFY 可能顶掉本 flow 的 preflight。

### 5.2 Post-action VERIFY

DEPLOY / ROLLBACK 后由 Bridge 内部 reconcile_post_action_verifies() 合成。

它不经过外部 Request admission，不应被自己的 slot 阻挡，直到 terminal 后才释放 active_flow。

## 6. Author / continuation：不增加 flow_id

当前 live：

- DEPLOY / ROLLBACK 会读取控制总线 PR metadata / author
- CANARY / VERIFY / TEST_PR 当前不读取 author

窄范围复核结论：

- persistent_process(number, head, ...) 已有 PR number
- 现有 GitHub metadata / verified author 逻辑可以抽取并泛化
- 不需要修改 Request JSON schema

建议实现方向：

- github_pr_metadata(number)
- verified_author(metadata)

现有 check_deploy_pr() 保留自己的 DEPLOY / ROLLBACK 状态门禁，并复用以上 helper。

CANARY / VERIFY / TEST_PR 只取 verified author，用于 active_flow owner。

Continuation 条件：

- author == active_flow.owner
- current candidate == active_flow.candidate
- request.action == active_flow expected next action

三者都满足才允许推进。

不增加 caller-controlled flow_id / parent_id。

### 同账号不同 Chat

同一个 GitHub author 的另一个 Chat，如果恰好发送正确下一阶段且 candidate 相同，可能被视为 continuation。

这是不加 flow_id 的明确取舍。

若未来确实需要“同一账号下区分多个并行聊天流程”，再单独升级协议。

## 7. Candidate binding

candidate identity 来自 CC 自己已有 authority，不从 Request 提供。

建议 active_flow 至少绑定 candidate image id 和 candidate contract sha（存在时）。

每次 continuation 前重读当前 candidate。

若变化：

- 不继续
- reason: FLOW_CANDIDATE_CHANGED
- 原 deployment flow 终止
- 新部署重新 CANARY

不得出现 CANARY X → candidate 变 Y → DEPLOY Y。

## 8. 唯一未冻结的产品选择：standalone CANARY

现场确认三层都无法区分 standalone CANARY 和 deployment-start CANARY。

Request 层：CANARY 使用普通五字段，没有“我只是测试”或“这是部署第一步”。

Task 层：CANARY authority / candidate 完全由 Bridge 派生，不从 Request 读取 flow intent。

DEPLOY selection：DEPLOY 只选择最新、candidate 匹配的 CANARY，不引用一个 caller flow id。

因此下面两句话目前生成同种 CANARY Request：

- 跑一下当前候选的金丝雀
- 部署当前版本（GPT 编排的第一步）

### Option A — 所有 CANARY 都开启 deployment flow

优点：

- Request schema 零改动
- 最小代码
- 不用 flow marker

代价：

- 用户只想 CANARY 时，也会进入 WAITING_FOR_PREFLIGHT_VERIFY
- business slot 会保持到 flow timeout / 后续继续

只有产品接受这个行为，才适合采用。

### Option B — 给 deployment-start CANARY 一个最小显式 intent

例如仅 CANARY 允许一个布尔 / enum intent，standalone CANARY 仍保持旧五字段。

优点：

- 产品语义清楚
- standalone CANARY 不会长期占 flow
- 不需要通用 flow_id

代价：

- 有一次 Request schema 改动
- 需要相应测试 / guide 更新

### Option C — 用 author / candidate / stage 猜 intent

不推荐。

它无法真正知道用户是“只测 CANARY”还是“准备部署”，会把启发式写成长期合同。

本设计稿不替产品决定 Option A / B。

## 9. 时间窗口

Request max age = 900 seconds。

含义：fresh Request 自己创建后，需要在约 15min 内被 Bridge 接受。

它不限制两个 Request 之间能等多久。

部署 flow 使用现有 proof freshness：

- CANARY: 1800s / 30min
- preflight VERIFY: 300s / 5min

例如 15:00 CANARY SUCCESS，15:20 创建 fresh VERIFY，requested_at = 15:20，仍合法。

## 10. UNKNOWN / failure

明确 terminal 可以释放：

- trusted SUCCESS
- trusted FAILED
- WAITING stage 的 proof freshness 已过期

outcome unknown 不能释放：

- Task 已发布
- 没有可靠 terminal outcome
- publish / execution / evidence 状态歧义

状态为 BLOCKED_REVIEW，新 business Request 继续拒绝。

第二轮会诊现场证据显示 Evidence 仓已有 FAILED Evidence：

- SUCCESS 223
- FAILED 10
- 覆盖 CANARY / VERIFY / ROLLBACK / TEST_PR 等动作

因此大多数明确失败可成为 terminal。

但 attempt-failure publication 是 best-effort；发布失败时仍可能进入 UNKNOWN，这正是保留 BLOCKED_REVIEW 的原因。

## 11. Request Visibility

现有：

- command-center-request-visibility-v1
- REQUEST_REJECTED
- Bridge poll journal
- facts published to control bus

第一阶段只要求以下 reason 能进入现有 Request Visibility：

- COMMAND_CENTER_BUSY
- FLOW_CANDIDATE_CHANGED
- FLOW_EXPIRED
- FLOW_CONTINUATION_MISMATCH
- FLOW_REQUIRES_OPERATOR_REVIEW

### Structured diagnostic 拆第二阶段

现有 request_fact_v1.schema.json 多层 additionalProperties:false。

reason 可以承载新的 reject token / CONFLICT class，但没有现成字段放：

- active owner
- active stage
- active task
- started_at
- candidate

为了保持小补丁，第一阶段只保证机器可读 reason。

Boss GPT 看到 REQUEST_REJECTED + reason=COMMAND_CENTER_BUSY 就必须停止，不排队、不重试、不绕过。

“当前谁在做什么”的完整诊断作为独立第二阶段增强。

## 12. Scheduled Task

Scheduled Task 只负责编排：

1. 创建当前阶段 fresh Request
2. 查看 Request fact / Task / Evidence
3. SUCCESS -> 创建下一 fresh Request
4. PENDING -> 等
5. REJECTED / FAILED / EXPIRED / BLOCKED -> 停止并报告

禁止：

- 没看到结果就重发同一阶段
- 重用 request_id
- 复活 expired flow
- 绕过 BUSY
- 自动 retry DEPLOY / ROLLBACK

## 13. 实现分期

### Phase 1 — Single-flight core

目标：业务 Request 不串线。

包含：

- active_flow ledger
- atomic admission
- author lookup 泛化
- candidate / stage continuation
- preflight VERIFY isolation
- post-action VERIFY lifecycle
- fail-closed UNKNOWN
- BUSY reason token
- request-visibility classification
- tests
- Boss GPT guide

### Phase 2 — 可选诊断增强

独立授权 / 独立 PR：

- structured BUSY diagnostic
- current owner / stage / task / started_at 的 GitHub 可读展示
- operator recovery UX
- 其它观察性增强

### 当前不做

- HK mutex
- Redis / SQL
- Queue / Priority / Preemption
- 通用 Workflow Engine
- 自动 retry
- 新 daemon
- shell / Docker 参数扩权

## 14. 实现验收测试

至少覆盖：

1. 两个 Bridge process/tick 同时抢 business slot，只能一个成功
2. flow A CANARY 运行中，flow B CANARY -> BUSY
3. flow A CANARY SUCCESS 后，B business Request -> BUSY
4. verified owner 的 expected preflight VERIFY -> allow
5. 其他 owner VERIFY -> BUSY
6. candidate changed -> reject continuation
7. standalone VERIFY 不能顶掉 active flow preflight
8. CANARY proof >30min -> flow expire
9. preflight proof >5min -> DEPLOY 不允许
10. fresh Request 自己仍受 900s max-age
11. post-action VERIFY bypass external admission
12. ROLLBACK 保持 slot 到 post-action VERIFY terminal
13. HEALTH 不取得 business slot
14. normal HK Agent path 不因本补丁新增第二实例
15. BUSY Request 不产生 Signed Task
16. REQUEST_REJECTED 可见 COMMAND_CENTER_BUSY
17. process restart 后 active_flow durable
18. prepared / publishing / ambiguous publish fail-closed
19. FAILED Evidence -> terminal
20. failure publication 丢失 -> BLOCKED_REVIEW
21. 同 GitHub owner / same candidate / correct stage 的另一个 Chat 行为与产品约定一致
22. 根据第 8 节最终选择，测试 standalone CANARY 行为

## 15. 实现 PR 开工条件

开始写代码前，只需再确认：

1. 当时 live / main 基线没有发生改变到使本设计失效；
2. Eason 对第 8 节 standalone CANARY 选择 Option A 或 Option B。

除此之外，不再需要继续扩大架构会诊。

## 16. 产品层验收口径

Command Center 同一时刻只推进一个人工 / GPT 业务意图。部署开始后，只有该业务流程合法的下一阶段可以继续，其他业务 Request 在签 Task 前明确拒绝；HEALTH 不占业务锁；DEPLOY / ROLLBACK 的 post-action VERIFY 仍由 Bridge 内部自动完成；旧流程不会因 GPT 掉线、迟到或 outcome 不明而误释放或串到另一条业务流程。

这就是本补丁的范围。

不要把它扩成调度平台。
