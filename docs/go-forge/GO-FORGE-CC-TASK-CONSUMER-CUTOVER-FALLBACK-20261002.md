> **HISTORY** — 历史 / 取证材料，不是当前操作说明。
> **HISTORY** — historical / audit material, not current operating instructions.
>
> 当前入口：人（中文）[`README.md`](../../README.md) · AI（英文）[`AGENTS.md`](../../AGENTS.md)。
> Current entry points: [`README.md`](../../README.md) (Chinese, humans) and [`AGENTS.md`](../../AGENTS.md) (English, AI).
>
> 本文档不定义正常操作路径，不得作为当前操作依据。This document does not define the normal path; do not use it as current operating guidance.

---

# GO Forge — Command Center Task Consumer Cutover / Fallback

**Date:** 2026-10-02（原始 2026-10-01；本次更新为 cutover 执行后的真实状态）
**Status:** **执行中 / 已切换，Forge = Primary Operator**（原文的 `DRAFT / DESIGN ONLY / DO NOT EXECUTE YET` 已作废）
**Owner:** chenzhenxi1-sudo
**Purpose:** 记录 Task 主消费路径从旧 Command Center 切到 GO Forge 的方式，以及旧 CC 如何保留为独立兜底。

> 本文件曾从「未来实施提醒」升级为当时的切换 / 运行文档；**自 2026-10-08 起已降为 HISTORY**。
> 下文 §14 是当时的状态记录，已不再是「唯一权威状态块」。当前状态见仓库根 `README.md`（中文）/ `AGENTS.md`（英文）。

---

## 1. 为什么单独留这个 PR

GO Forge 的目标不是改造现有 Command Center，也不是让 Forge 套在 CC 前面继续走旧流程。

Task 总线的主消费者需要切换：

~~~text
BEFORE:
Boss GPT → go-control-tasks → Old Command Center consumer → HK-STAGING

AFTER:
Boss GPT → go-control-tasks → GO Forge → HK-STAGING
~~~

原则：

> **不重构、不侵入、不改写 CC 的内部部署逻辑；只在 Task consumer 边界做一次可逆切换。**

⚠ **2026-10-02 现场更正（重要）**：实际执行时发现，**这次切换根本不需要动 CC**。
原计划（§4 原文）设想「disable 旧 CC 的 consumer unit/timer」。实测不成立，见 §4。

---

## 2. 老板侧保持不变（但入口契约收窄为更简单的一种）

原文要求「老板不改任何东西」。真实现场比这个更明确：

- **仓库不变**：`chenzhenxi1-sudo/go-control-tasks`
- **入口不变**：仍然是往这个仓提交一个任务文档
- **但契约变简单了**：老板**只需要**给出 `target_pr`

事实上**老板要提供的信息比原来更少**，不是更多。切换后的正常部署请求是：

~~~text
Deploy PR <number> to HK-STAGING.
~~~

对应的任务文档（历史形态；tasks 仓 `GO_FORGE_BOSS_USAGE.md` 已于 2026-10-08 降为 HISTORY）：

~~~json
{
  "authority": "GO-FORGE",
  "action_id": "FORGE_DEPLOY",
  "environment": "HK-STAGING-01",
  "target_pr": 320,
  "schema_version": "1",
  "task_id": "forge-deploy-pr320-<utc>",
  "issued_at": "<utc>",
  "expires_at": "<utc+2h>",
  "nonce": "<random>",
  "parameters": {}
}
~~~

老板**不再需要知道、也不再被要求提供**：

~~~text
TEST_PR / candidate admission / artifact digest / package sha256 / candidate contract
CANARY / VERIFY / recovery 细节 / Docker / HK Agent / deployctl / migration 步骤 / rollout 顺序
~~~

这些由 Forge 自己从 live state 解析。

---

## 3. 最终形态：两条独立部署路径

~~~text
                         ┌── GO Forge ─────────────→ HK-STAGING
Boss → go-control-tasks ─┤        PRIMARY
                         │
                         └── Old Command Center ───→ HK-STAGING
                                  FALLBACK
                                  (normally detached)
~~~

1. **Forge = Primary deployment path**
2. **Old Command Center = Fallback deployment path**
3. 两者不是串联关系。
4. Forge 不把正常任务送回 CC。
5. CC 不需要为 Forge 重写任何内部逻辑。
6. 正常状态下只有 Forge 消费新的部署任务。
7. 老 CC 保留完整，fallback 独立可恢复。

禁止形成：

~~~text
Forge → Command Center → HK
~~~

---

## 4. Cutover 的真实机制（已实测，取代原设想）

**实测结论：两条路径由不同的输入驱动，因此「断开」是天然发生的，不需要停任何 CC unit。**

| 路径 | 消费者 | 它读什么 |
|---|---|---|
| Old Command Center | `go-boss-request-bridge.service`（+ `go-liveness-producer` / `go-liveness-request-transport` / `go-request-fact-cycle` / `go-command-center-state-cycle` 等 timer） | `go-control-tasks` 里的 **`boss-request-*` Request PR**，`allowed_actions = [HK_STAGING_VERIFY, HK_STAGING_TEST_PR, HK_STAGING_DEPLOY, HK_STAGING_ROLLBACK, HK_STAGING_CANARY, CONTROL_PLANE_HEALTH]` |
| GO Forge | `forge-worker.service`（daemon，60 s 轮询） | `tasks/` 目录下的 **commit**，且 `authority == GO-FORGE` |

两个事实使切换变成**发布约定变更**，而不是主机改动：

1. **bridge 不扫 `tasks/`**。给 Forge 的任务是普通 commit，不是 Request PR ⇒ bridge 结构上看不见它。
2. **Forge 有硬件命名空间过滤**。`authority != GO-FORGE` 的任务在代码里、任何 claim 之前被 IGNORED —— 零 model 调用、零 token、零 inflight。已实测：总线上 20 条 `GO-COMMAND-CENTER` legacy 任务全部被忽略，且游标正常前进（不会卡在同一旧任务上重复扫描）。

所以：

> **旧 CC 从未被「停用」，而是不再被喂它认识的东西。**
> 它仍然 running、仍然可用的 fallback；恢复它的成本 = 老板重新发一条 `boss-hk-*` Request。

这个机制同时满足原 §4 的「可逆」要求，而且**改动量比原计划小一个数量级**：没有 unit 被 disable，没有 ledger 被清，没有代码被删。

⚠ 仍然成立的一条：**实施前必须重新核对真实 live consumer，不得只凭历史文档操作**。本次已现场核对（见 §14 证据）。

---

## 5. 不允许为了 Cutover 做的事情

以下仍未授权，本轮也**没有**做：

- 重写 Command Center / candidate governance / projection / publication；
- 修改 CC 的固定 Gate 语义；
- 修改 HK Agent / deployctl 内部逻辑以适配 Forge；
- 重做 ledger / Evidence；
- 修改老板 PR 或老板 Task 生成方式；
- 为 Forge 引入新的审批系统 / 权限中心；
- 把 Forge 塞回 CC workflow。

如发现 Forge **必须**依赖某个 CC 内部改造才能上线：`STOP → 单独提出原因 → 单独 PR → Owner 决策`。

---

## 6. Forge 上线前置条件 — 逐条实测状态

原 §6 列 A/B/C/D。真实结果：

### A. 本地实现通过 — ✅ PASS

Task intake、AI tool loop、GitHub、SSH/Shell、audit、recovery tracking、verify、dedupe、crash/restart 全部实现。
- `--self-test`：**66 / 66，0 failures**（Round 2 时为 52）
- `acceptance_live.py`：**17/17 PASS**（真实总线上 20 条 legacy 任务全部 IGNORED，零 model 调用、零 token）
- 已修真实缺陷 4 个 + 本轮新增 3 个（见 §12）

### B. Prompt 校准通过 — ✅ PASS（版本已冻结）

`GO_FORGE_OPERATOR_PROMPT_V1` 在**首次真实运行后冻结**；本轮因 Boss 契约收窄升至 **V2**，每条新增都对应一个实测缺口：

| 新增行 | 对应的真实缺口 |
|---|---|
| 身份由 Forge 预先解析，模型只做核对 | 老板不该被要求提供技术事实 |
| `needs_test_pr` 时点出既有 TEST_PR 能力 | Forge 需要能自己准备候选 |
| 「不得自铸 candidate contract」 | 防止操作员自我认证 |
| INSPECT 明确「不授权部署」 | 身份块共用了「You are deploying」的措辞，会诱导非部署任务去变更 |

### C. 历史回放通过 — ✅ PASS

PR320 全链（TEST_PR_OK / admission / sealed package / artifact on HK）已被 Forge 独立重建与核对。

### D. HK-STAGING 真实试运行通过 — ✅ PASS（关键证据）

| # | 事项 | 结果 |
|---|---|---|
| 1 | `FORGE_INSPECT`（PR320） | **PASS**，`comparison = MATCH`，40 轮 / 449 s / 零 mutation |
| 2 | `FORGE_DEPLOY` 第一次 | FAILED_NEEDS_HUMAN，零 mutation（主机权威绑定 CC + 候选未装） |
| 3 | `FORGE_DEPLOY` 第二次（授权后） | **DEPLOY_SUCCESS** |
| 4 | 真实 Boss 最小意图 intake | **PASS**（`supplied_fact_keys = []`） |

**PR320 真实部署事实（第 3 项）**

~~~text
task        tasks/forge-deploy-pr320-r3-20261002T1642Z.json @ 14963104
run         20261002T084029Z-forge-deploy-pr320-r3-20261002T1642Z   (84 turns)
candidate   pr320-eeafca1b-unified-pr315-on-main
head        eeafca1b15a4754ba36a0f138a27347cbbd12c73   (live re-read before the run, unchanged)
artifact    sha256:26c95472d494100dc5365b031335670b57570b86ac50fb1b4ebd161d7933530b
previous    sha256:e1049b5c0f3fc9d04d2919c8fdbb259dcd71d9e2d6f979bf93e5a1c2c8c397aa
recovery    rp-02-image + rp-04-files（均 produced + verified）+ 人工 pg_dump（3500 TOC）
mutations   50（全部走主机自己的 pinned helpers）
verify      8/8 step verify ok
rollback    none required
result      DEPLOY_SUCCESS
evidence    go-control-evidence evidence/forge-deploy-pr320-r3-20261002T084029Z.json @ ae8b9720
~~~

独立复核（我方，非采信其自报）：8/8 业务容器 `26c95472d494`、api `healthy`、caddy/redis 未受影响、无 migration、alembic `0145_source_latest_index`、运行镜像内 `/app/src/go_hotel/main.py` 的 sha256 与 `eeafca1b` 下同名文件一致。

**Boss 最小意图 intake（第 4 项）**

~~~text
task    tasks/forge-inspect-bossintent-20261002T091549Z.json @ 5ed6b2af
        老板提供的全部内容 = {"authority","action_id","environment","target_pr":320} + envelope
        parameters = {}
run     20261002T091649Z-forge-inspect-bossintent-20261002T091549Z
  candidate_resolution.json:
    shape              = minimal
    supplied_fact_keys = []            <== 老板零技术字段
    identity_origin    = resolved
    candidate_id       = pr320-eeafca1b-unified-pr315-on-main
    source_commit      = eeafca1b15a4754ba36a0f138a27347cbbd12c73
    artifact_digest    = sha256:26c95472d494...
    contract sha256    = 49100fe16124f8d6189b56f78d5e63459e68aedb7749062202ffd65ea00fca74
    installed_on_host  = true
  result = PASS；零 mutating 操作；Evidence 已发布
  usage  = deepseek-flash / 23 calls / 输入 1,069,850 / 输出 41,733
~~~

---

## 7. Cutover 执行 — 实际发生了什么

原 §7 的 STEP 1–5。真实执行：

### STEP 1 — Freeze ✅

确认 Forge 无测试残留、CC 无 in-flight mutation、HK-STAGING 无进行中部署。任务总线**没有**一条任务被两套系统同时领取（结构上不可能：两套消费者读不同的输入，见 §4）。

### STEP 2 — Detach Old CC Consumer ✅（零主机改动）

**没有 disable 任何 unit。** 断开发生在输入层：Forge 的任务是 `tasks/` commit，bridge 不认识这种输入。
- 旧 CC 相关 service/timer 现场状态**未被改动**，全部保持原有 enabled/active 状态。
- 未删除 unit / 代码 / ledger / 历史状态。

### STEP 3 — Enable Forge Consumer ✅

`systemctl enable --now forge-worker.service` → **enabled + active**。
`ReadWritePaths` 唯一写目录 `/var/lib/go-forge`；硬化集（`ProtectSystem=strict` / `ProtectHome` / `PrivateTmp` / `NoNewPrivileges`）实测生效。

### STEP 4 — Prove Single Consumer ✅（关键判据）

~~~text
new Task (authority=GO-FORGE)
  ↓
Forge sees it          ← 实测：60 s 内 claim
CC does NOT consume it ← 实测：bridge 输入面不含 tasks/；且总线上 20 条 legacy CC 任务被 Forge 全部 IGNORED
~~~

**双向都已证明**：Forge 不吃 CC 的任务；CC 也看不见 Forge 的任务。

### STEP 5 — Run First Production-Like HK-STAGING Task ✅

即 §6 第 3、4 项。Boss 输入方式未变（且更简单）、Task repo 未变、Forge 完成任务、CC 未抢任务、HK 无双 mutation、audit/evidence 完整。

---

## 8. Fallback：老 CC 怎么救场

Old Command Center 保持完整：它仍然 installed、enabled、running、可独立运行。

切换顺序（原样保留，本轮未执行过 fallback）：

~~~text
1. STOP / DISABLE Forge consumer
2. 确认 Forge 当前无 in-flight mutation
3. 确认 HK-STAGING 达到一个已知状态
4. 由老板重新发一条 boss-hk-* Request（= 旧 CC 的输入面）
5. 再允许新 Task 进入旧 CC 路径
~~~

禁止：

~~~text
Forge 正在改 HK  +  CC 同时开始改 HK
~~~

> **Fallback 是 consumer ownership 的切换，不是两套系统同时抢任务。**

---

## 9. 恢复 Forge 后怎么切回来

~~~text
1. 先停止新 Task
2. 等 CC 当前任务 terminal
3. 停止向旧 CC 输入面投递 boss-hk-* Request
4. 确认 HK 无 mutation
5. 确认 forge-worker 为 enabled + active
6. 发一条测试 Task 验证单消费者
7. 恢复正常 Task 流量
~~~

不需要老板改变操作。

---

## 10. 两道保险的正式定义

### Primary — **GO Forge Autonomous AI Operator**

fresh AI session / clean context；自己调查候选与真实环境；自己选工具与执行方式；强制 audit；强制 recovery；hard red lines；以工程判断完成部署。
落地形态：`go-cc` 上的 `forge-worker.service`，用户 `go-forge`，namespace `authority = GO-FORGE`。

### Fallback — **Existing GO Command Center**

保留当前已有实现；平时不消费新任务；Forge 不可用时人工切回；不要求为 Forge 持续跟随改造。
落地形态：`go-boss-request-bridge.service` 等既有 unit，输入面为 `boss-request-*` Request PR。

---

## 11. 为什么不做 Active/Active

明确不做 `Forge consumer = ON` **且** `CC consumer = ON`。

原因不是把 AI 当敌人，而是没有现实收益却引入：同一 Task 双消费、同一环境并发 mutation、attempt budget 消耗、两套状态机互不理解、recovery source 被另一条路径消耗、排障时无法确定谁改了现场。

> **两道保险 = 两套独立能力 + 单一当前 owner。**

---

## 12. 当前主消费者开关 & 已修缺陷

### 主消费者 fact

真实实现为两个位置，任一处即可判断当前 owner：

~~~text
chenzhenxi1-sudo/go-control-tasks  →  CURRENT_OPERATOR.md
   PRIMARY_OPERATOR     = GO_FORGE
   NORMAL_BOSS_ACTION   = FORGE_DEPLOY
   RESULT_REPOSITORY    = chenzhenxi1-sudo/go-control-evidence
   OLD_COMMAND_CENTER   = FALLBACK_ONLY
   PRODUCTION_DEFAULT   = FORBIDDEN
~~~

另有机器可读的 `forge-operator/schema/forge-task-v1.schema.json`。
按原 §12 要求：人能一眼看懂、切换可逆、不改老板入口。**没有为它新建数据库或审批系统。**

### 已修真实缺陷（全部有实测证据，非推测）

| # | 缺陷 | 后果 | 状态 |
|---|---|---|---|
| 01 | listener `GitHubClient(config, None)` | 真实 HTTP 状态码全丢，变成 `AttributeError` | 已修 |
| 02 | `--dry-run` 从不传给 session | 文档承诺 nothing executed，实际跑真实会话 | 已修 |
| 03 | `inflight` 单行槽位永不过期 | 一次中断后 worker 永久卡死 | 已修 |
| 04 | `dry-run` 不拦 GitHub 写 | dry-run 会话真的发了 PR 评论 | 已修 |
| 05 | `docker exec` 等只读命令被判为 mutating | 只读巡检被迫创建恢复点、记录 2 条假 mutation | **记录，未修** |
| 06 | `forge/recovery.py` L178/L204 `printf '%s'` 应为 `%%s` | `_db_backup` 的 PGURL 抽取被破坏 | **记录，未修** |
| 07 | 候选事实被 `cat` 失败后静默跳过 | **「读不到」被当成「不存在」** —— 会误拒一次合法部署 | 已修（本轮） |
| 08 | 身份块对 INSPECT 也写「You are deploying」 | 诱导非部署任务去变更 | 已修（本轮） |

> 07 与 08 都是本轮**用真实 proof 找出来的**，不是设计推演。07 尤其危险：它会把一次完全合法的部署拒掉。

---

## 13. Rollback of Cutover

~~~text
ROLLBACK TARGET: Task consumer ownership only
~~~

不是回滚整个 GO 系统。最小回滚：

~~~text
stop forge-worker
↓
verify no in-flight Forge mutation
↓
boss resumes publishing boss-hk-* Requests（旧 CC 输入面）
↓
verify one Task enters CC
~~~

因为 CC 内部没有被 Forge 改造过，fallback 成本极低。

---

## 14. 历史状态记录（本文件已降为 HISTORY，不再是「唯一权威状态块」）

~~~text
FORGE_READY_FOR_CUTOVER = YES
CUTOVER_AUTHORISED      = YES
NORMAL_BOSS_PATH        = GO_FORGE        (FORGE_DEPLOY + target_pr)
CC_CONSUMER_CHANGE      = NONE_REQUIRED_BY_DESIGN   (bridge 输入面不含 tasks/；未停任何 unit)
CC_FALLBACK_PRESERVED   = YES             (unit/service/ledger/代码全部原样保留)
FORGE_SERVICE           = enabled + active (go-cc)
FORGE_CODE_HEAD         = source == installed, byte-identical; --self-test 66/66
HK_CHANGE               = PR320 已部署并在跑（8/8 业务容器 = sha256:26c95472d494）
PRODUCTION_CHANGE       = NONE
BOSS_PR_CHANGE          = NONE
HUMAN_PR_CHANGE         = NONE
RESULT_CHANNEL          = chenzhenxi1-sudo/go-control-evidence → evidence/
~~~

### 现场证据锚点

~~~text
PR320 identity      head eeafca1b15a4754ba36a0f138a27347cbbd12c73
                    candidate pr320-eeafca1b-unified-pr315-on-main
                    artifact sha256:26c95472d494100dc5365b031335670b57570b86ac50fb1b4ebd161d7933530b
                    contract 49100fe16124f8d6189b56f78d5e63459e68aedb7749062202ffd65ea00fca74
                    package  d13f14d112670dfeff17f90b860c9c4ed8cf92e7a55c1962abee87f9f2f40d76
forged deploy evid  evidence/forge-deploy-pr320-r3-20261002T084029Z.json @ ae8b9720
bootstrap inspect   evidence/forge-inspect-20261002T152500Z.json      @ 6499146b
boss-intent inspect evidence/forge-forge-inspect-bossintent-…json     @ 9c35b3f4
operator source     forge-operator/source/ (tasks repo PR #134)  或  go-cc:/opt/go-forge
~~~

---

## 15. 未决 / 需要 Owner 侧处理

以下全部**已被记录，本轮按任务边界未修**。

### 15.1 🔴 Baseline 必须由 Owner 推进（直接阻塞下一次部署）

上一次真实巡检（Boss 最小意图那次）报出 **`comparison = DRIFT`**，且**是正确的**：

- **declared baseline** 仍指向 PR320 **之前**的版本（`CURRENT_HK_RUNTIME.json` → `e109af4d` / 镜像 `e1049b5c`，environment-graph `e109af4d`，最后一条 CC deploy record 为 10-01 23:04）。
- **actual runtime** = PR320（`eeafca1b` / 镜像 `26c95472`）。

原因是 PR320 部署**没有**（也不应该由操作员）推进 canonical pointer / environment-graph / CC deploy record。

后果：**在 declared baseline 被推进到 PR320 之前，任何新的部署请求都会（正确地、安全地）报 DRIFT 并停止变更。**

这正是设计的闭环：
~~~text
Forge 部署 → Forge 发布 Evidence → Owner 侧依据 Evidence 推进 baseline/head
~~~
**Forge 即使 DEPLOY_SUCCESS 也不推进 baseline。**

### 15.2 环境缺陷：封存 deployctl 与新候选的路径假设不一致

`collector_runtime.ALEMBIC_WORKDIR` 写死 `/workspace`，而候选镜像把应用放在 `/app`
（`docker inspect ... WorkingDir=/app`、`PYTHONPATH=/app/src`）。后果：主机自带的 `verify`
**无法验证当前在跑的候选**（部署本身无问题，但自动验证链是断的）。

⚠ **更正（2026-10-02 17:5x）**：本节此前引用的复现命令**是错的**，已撤回。`verify` 要求 **7 个参数**
（`--release-id` / `--candidate-image-id` / `--expected-current-image-id`）；参数形状不对会在**任何 gate 之前**
打印**全空字段**的 `VERIFY_REJECTED`，与 workdir 无关。正确复现如下：

~~~
verify --release-id <id> --candidate-image-id <sha> --expected-current-image-id <sha>
  -> VERIFY_REJECTED, gate_results {}      (fields populated => past the CLI check, still no gates)
collector_runtime.ALEMBIC_WORKDIR = /workspace
docker exec -w /workspace <api> alembic current -v
  -> rc 127 : OCI runtime exec failed: chdir to cwd ("/workspace") ... no such file or directory
collector_runtime._collect_alembic_for_api -> ValueError('current exit')
  -> caught by _verify -> REJECTED, gate_results {}
docker exec -w /app <api> alembic current -> 0145_source_latest_index (head)
~~~

`_installed_identity()` 仍 PASS ⇒ 安装本身完好，坏的只有这一条路径假设。

⚠ **修法不是「把常量改成 `/app`」**，理由有三，都是实测：

1. `/workspace` 硬编码在 **≥8 处、7 个 runtime 模块**，其中 **2 处是校验器**
   （`media_topology_runtime.py:116` 要求 `profile['workdir']=='/workspace'`；
   `migration_program.py:66` 断言 `startswith('/workspace/src/')`）——不是默认值，是断言。
2. 封存的 `/etc/go-hk-deployctl/media-topology-v2.installation.json` 带 `runtime_profile.workdir`，
   被 `topology_sha256` + `authorization_sha256` 绑定 ⇒ 改 workdir 会改哈希，**现有授权不再覆盖它**。
3. launcher 用 `_COLLECTOR_SHA256` / `_CANARY_SHA256` / `_DEPLOY_SHA256` / `_ROLLBACK_SHA256` /
   `_ARTIFACT_SHA256` 钉死各模块字节，而 `_verify_installation()` 门控**每一个** action
   ⇒ 改任何 runtime 模块，**在重新密封安装事实之前主机上所有动作全部失效**（不只 verify）。

⇒ 「重新密封安装事实」不是收尾动作，而是**强制前置**；而且这一步等于**在改「负责验证的那一方」**。
建议方向：让 runtime root 成为**派生量**（从候选镜像自身读，或从候选合同里已有的
`build_definition.executor_version = test-pr-v4-runtime-root` / `profile` 读），8 处共同消费同一个解析值——
这正是 #306 已经对「世代」用过的同一范式（`canary_runtime.HEAD` → `expected_head()`、
`collector_runtime.EXPECTED_REVISION` → `resolve_revision()`）。今天没有任何地方派生它：
`hk_candidate_contract.verify_profile()` 直接返回模块级常量 `WORKDIR = '/workspace'`。

### 15.3 Forge 源码没有 canonical GitHub home

现状：源码只存在于工作站 `D:/Code/Workbuddy/FORGE-V0/` 与 `go-cc:/opt/go-forge`。
本轮按「不得为这一轮新建仓库」的要求，暂存于 `go-control-tasks` 的 `forge-operator/source/`（PR #134），并在其 README 明确标注这是**临时落点**。
**这是一个 open source-of-truth defect，需要 Owner 明确决定正式归属，不应顺其自然。**

### 15.4 Owner 侧对账：Forge 未扩展 pinned 签名 deploy-record 链

Forge 的 PR320 部署**没有**写入 CC 的签名 deploy-record 链（最新记录仍是 10-01 的 `58920cd1…`）。
⇒ **Command Center 对「现场在跑什么」的视图现在是过期的**（现场跑 `26c95472`，而 CC 仍把它呈现为「待部署的候选」）。
推进 baseline / head / candidate authority 明确不属于操作员职责。

### 15.5 其它已记录项

- **SYSTEM_DEFECT-05**：`docker exec` / 含 `>` 重定向的只读命令被判定为 mutating；且状态探针含 `date -u -Is`，使每次 before/after 比较都「变了」。一次只读巡检因此在 `result.json` 里留下 2 条假 mutation 并被迫建恢复点。建议最小修法：区分「显式声明 mutating」与「模式推断」，两者都记录。
- **SYSTEM_DEFECT-06**：`forge/recovery.py` L178 / L204 的 `printf '%s'` 应为 `%%s`。
- **GO-FORGE 任务不验签**：namespace 过滤靠 `authority` 字符串。签发方是受信身份，暂不改；但要知道这是一条**约定**而非密码学边界。
- **会话上下文逐轮增长**：一次部署 84 轮、输入 **12,063,085** token。成本已可归因（`usage.json`），但无任何机制管理上下文增长。
- **Evidence 路径可读性**：`publish_evidence` 的默认路径把 `task_ref` 与 `run_id` 拼接，产生三段重复的长文件名。纯观感问题。
- **`--dry-run` 的真实语义**（已写入 README）：`dry-run = 真实推理 + 零外部变更`，**不是**「免费/不调模型」。

---

## 16. 最终一句话

> **老板入口不变、而且契约更简单（只说 `Deploy PR <n> to HK-STAGING`）；GO Forge 已成为主操作员并已真实完成一次 PR320 部署；旧 Command Center 一行代码未改、仍然完整可用作为兜底；任意时刻同一环境只有一个 mutation owner。**

---

## 附：Boss 使用规则（正本）

Boss 面向的使用说明正本在任务仓：

~~~text
chenzhenxi1-sudo/go-control-tasks
  CURRENT_OPERATOR.md        当前路由事实
  GO_FORGE_BOSS_USAGE.md     零上下文可读的使用指南
  forge-operator/schema/     任务文档 schema
  forge-operator/task-template/  三种最小任务模板
~~~

要点：

1. 正常部署只说一句：`Deploy PR <number> to HK-STAGING.`
2. 发布为一条 `authority=GO-FORGE` / `action_id=FORGE_DEPLOY` / `target_pr=<n>` 的任务到 `tasks/`。
3. **不要**另外单独发 TEST_PR / CANARY / VERIFY / DEPLOY request —— Forge 自己决定并执行所需准备。
4. **不要**提供 image digest / artifact digest / package digest / migration 命令 / Docker 命令 / compose 路径。
5. 结果从 `chenzhenxi1-sudo/go-control-evidence` 读。
6. 旧 Command Center 仅作兜底，**不得与 Forge 同时使用**，且不得由 Boss 自行决定同时走两条路。
