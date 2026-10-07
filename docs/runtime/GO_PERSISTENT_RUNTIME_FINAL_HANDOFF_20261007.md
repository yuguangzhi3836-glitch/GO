# GO Persistent Runtime · FINAL HANDOFF（2026-10-07）

> **如果只想确认 Persistent Runtime 是否已经交付、当前怎么用、哪些历史不要再碰，请以本 PR 为最终入口。**

本文件是 **最终收口**，不是新 Runtime feature。合并本 PR 之后，Persistent Runtime 在工程上封板（FROZEN）。

- **收口时间**：2026-10-07（UTC+8）
- **收口基线 main**：`794dd21e44b5fb41b94b96a18575537de262a76e`（= PR #555 merge）
- **现场**：Runtime Host `rt01`（`i-j6cg7euc4ggol8gkijog`，cn-hongkong），2026-10-07 只读回读
- **上一份现场 closeout**：`GO-C1-CLEANUP-AND-OUTBOX-DRIFT-CLOSEOUT-20261007.md`（工作区报告，非仓库内文件）

---

## A. 一句话状态

```text
Persistent Runtime = DELIVERED / LIVE / FROZEN
```

- **DELIVERED**：C01-C12 正式 Issue → Generic Builder → Draft PR → 自动 C14 → 自动 C13 → 封存结论，全链已在 2026-10-04 用真实运行证明（Issue `#403` → PR `#404`）。
- **LIVE**：现场 `rt01` 常驻 6 个 unit 均 active/enabled，`systemctl --failed` 为空。
- **FROZEN**：本 PR 之后，Runtime 不再扩架构。只有本文件 §H 列出的 **真实故障** 才允许重新打开 Runtime。

本 PR 是**最终 handoff**，不是新 Runtime feature。

---

## B. 当前真实链路

```text
Boss / Boss GPT
→ C01-C12 Formal Task Issue
→ Persistent Runtime
→ Generic Builder
→ Draft PR
→ automatic C14
→ automatic C13
→ sealed result
→ STOP
```

- Merge / deploy 仍然 **独立授权**，不属于 Runtime，也不被 C13/C14 结论自动触发。
- 正常路径下，老板**只需要建一张 Issue**。Builder 一旦产出恰好一个合法 Draft PR，C14 与 C13 由 Runtime 自动接上。
- Builder 合法地没有产出 PR 时，Runtime 如实记录，并且**不创建任何审核任务**。

---

## C. 老板到底怎么用

面向 Product Owner，只有两件事需要人做。

### C.1 普通开发任务（默认路径）

在 GO 仓库新建一个 **GitHub Issue**，标题固定：

```text
Cxx · <task-id> · <scope>
```

正文至少写：

```text
Task: <真正要做什么>

Canonical source: <创建 Issue 当时的 current main 完整 40 位 SHA>
```

- `Cxx` 只能是 **C01-C12**；task id 形如 `V<n>-R<n>-Cxx-<n>`，Cell 必须与标题一致。
- `Canonical source` 必须是**创建 Issue 当时**的 main SHA，不要从旧 Issue / 聊天记录里复制。
- 解析器只把 `Task:` 之后**第一个连续段落**当作 objective——所有范围、限制、验收要求都写进这一段（可换行，不加空行，≤4000 字符）。

建完 Issue 之后：**不需要再做任何事**。审核会自动接上。

### C.2 手工 C14 Review（可选，非默认路径）

只有当要审的 PR **不是** Runtime Builder 刚产出的（别人手写的 / 历史 PR / 想重审一次）时，才需要：

```text
C14 · REVIEW · <description>

Candidate PR: #<PR_NUMBER>
Candidate SHA: <创建 Review Issue 时该 PR 的当前 head SHA>
```

- **不要创建 `C13 · REVIEW` Issue** —— Issue 只能启动 C14；C13 只能由一份 sealed 且 admissible 的 C14 自动创建。
- PR 之后又 push 了新 commit 时，旧 Review Issue 会被拒绝；对新 head 重新建一张。

### C.3 什么不用老板管

- 不用登录 rt01，不用手工 dispatch workflow，不用操作 Runtime。
- 不用管 lease / outbox / attempt / systemd / 安装。
- 不用为 Builder 产出的 PR 单独发审核。

### C.4 C13/C14 不负责 merge / deploy

C13/C14 只产出审核与 Evidence，**既不 merge 也不 deploy**。即使 `PASS_SCOPED + ACCEPT`，也停在 review 完成。

> 完整用法（含载荷规则、去重键、常见拒绝原因）见 `docs/runtime/README.md`。

---

## D. 当前 live Runtime 组成（2026-10-07 现场 readback）

### D.1 常驻服务

| Unit | 2026-10-07 状态 | 来源目录 | 作用 |
| --- | --- | --- | --- |
| `go-c1-c14-runtime` | active / enabled | `/opt/go/c1-c14-runtime/` | C1-C14 隔离 Runtime kernel（队列 / lease / attempt fencing） |
| `go-runtime-host-agent` | active / enabled | `/opt/go/runtime-host-agent/` | 常驻 Management Agent（registration-bound poller） |
| `go-runtime-host-runtime-bridge` | active / enabled | `/opt/go/runtime-host-agent/` | 本地 C1 runtime bridge（固定 inbox/outbox，无网络） |
| `go-runtime-host-c01-issue-consumer` | active / enabled | `/opt/go/runtime-host-c1-worker/` | GitHub 正式 C01-C12 Issue → Runtime.enqueue（只读 GitHub） |
| `go-runtime-host-ghaw-builder-worker` | active / enabled | `/opt/go/runtime-host-ghaw-builder-worker/` | 领取 `GHAW_BUILDER_V1` → gh-aw Builder → Runtime |
| `go-runtime-host-c13c14-review-worker` | active / enabled | `/opt/go/runtime-host-c13c14-review-worker/` | 领取 `C14_REVIEW_V1` / `C13_REVIEW_V1` → Lite 审核 → Runtime |
| `go-runtime-host-registration-sync` | `disabled` / 2016 后 `activating`（由同名 timer 拉起） | `/opt/go/runtime-host-agent/` | 有界 registration 刷新 |

- `systemctl --failed` = 空。
- 运行态：`tasks` 195 行（SUCCEEDED 145 / FAILED 45 / ESCALATED 4 / QUEUED 1），`evidence` 46002 行；review outbox 127 行，C1 outbox 5 行。

### D.2 已经删除、不要再复活的东西

- **Legacy standalone C1 Responses executor** ——`go-runtime-host-c1-worker.service` 已从源码删除（PR #555）并从 rt01 删除（2026-10-07，离线备份 `/root/c1retire-backup-20261007T065047Z`）。
  **不要重新创建 `go-runtime-host-c1-worker.service`**。
- **PG533-specific supplement 活代码** —— 已由 PR #553 从 generic Runtime/C13 中删除。

### D.3 `c1_worker.py` 是 shared library，不是 retired worker

- `control-plane/runtime-host-channel-v1/c1_worker.py` **仍在 main，且必须保留**。
- 现役两个 executor 都 `from c1_worker import (...)`：
  `c1_ghaw_builder_worker.py`（Builder）与 `c1_c13c14_review_worker.py`（C13/C14 review）。
- `test_c1_executor_boundary.py` 明文断言这个 import 必须存在。删除它 = 当场打断 Builder 链。
- 同理必须保留：`go-runtime-host-c1-worker.tmpfiles.conf`（声明 4 个 unit 共用的 `/etc/go-runtime-c1` 与 `/var/lib/go-runtime-c1`）、以及安装目录 `/opt/go/runtime-host-c1-worker/`（**现役 consumer 的 ExecStart 就在里面**）。

### D.4 一个必须知道的事实：main ≠ 现场字节（Runtime Host agent/bridge）

`/opt/go/runtime-host-agent/` 的 8 个文件（`adapter.py` `agent_service.py` `channel.py` `flow.py`
`git_transport.py` `registration_sync.py` `runtime_bridge.py` `runtime_bridge_service.py`）
**逐字节等于 PR #297 的 head `1e442d5db1a852c0bd263eece87138eec5bfd9ac`**，
而 **main 里完全没有这个 Management Agent 组件**（main 的 `control-plane/runtime-host-channel-v1/` 只有 `c1_*` 一行文件）。

- 本 PR **不把老组件硬合入 main**（见 §F）。
- 这套源码的 source-of-record = 分支 `eason/runtime-host-c1-bridge-20261001`（PR #297，已归档关闭、分支保留）。
- 2026-10-02 已经有过一次专门审计并得出同一结论（`GO-RH297-CANONICAL-PORT-2026-10-02.md`：`READY_FOR_INSTALL = NO`，因为那需要把整个 ≈30 文件组件搬进 main，而不是一个最小补丁）。

---

## E. 最终 PR lineage（分阶段）

### E.1 阶段总览

| 阶段 | 时间 | 关键 PR | 状态 |
| --- | --- | --- | --- |
| 0. 前身：C13/C14 Lite V2 | 09-25 ~ 09-27 | #252 #253 #254 #255 #256 #257 #262 #263 | MERGED（CURRENT） |
| 1. Boss 早期 Runtime 设计 | 10-01 | #285 #287 #289 #290 | CLOSED / UNMERGED（HISTORICAL_DESIGN） |
| 2. Eason Runtime Host foundation | 10-01 | #292 #293 #294 #295 #297 | OPEN → 归档关闭（RUNTIME_HOST_FOUNDATION） |
| 3. C1 真实执行 + Issue 入口 | 10-01 ~ 10-02 | #303 #304 #305 #310 #321 #322 #327 #329 | MERGED（CURRENT） |
| 4. Persistent Cell 槽位占位 | 10-02 | #331–#344 | CLOSED / UNMERGED（NEVER CANONICAL） |
| 5. Generic C01-C12 Builder | 10-04 | #381 #386 #387 #389 #391 #392 | MERGED（CURRENT） |
| 6. 自动 C14 / C13 | 10-04 | #395 #396 #397 #398 #402 | MERGED（CURRENT） |
| 7. 交付文档与收口 | 10-04 | #400 #401 #405 #406 | MERGED（DOCUMENTATION） |
| 8. Hardening | 10-04 ~ 10-07 | #419 #427 #428 #442 #449 #470 #483 #485 #539 #540 | MERGED（CURRENT） |
| 9. PG533 弯路与删除 | 10-06 ~ 10-07 | #534 #544（引入）→ #546 #553（删除） | 引入已 MERGED，专用活代码已 RETIRED |
| 10. Legacy C1 清理 | 10-07 | #555 #549 | MERGED（CLEANUP） |
| 11. 最终 handoff | 10-07 | 本 PR | 本 PR |

> 完整逐 PR inventory 见 **附录 A**。

### E.2 一句话读法

- 阶段 1 是**设计**，不是当前架构。
- 阶段 2 是**现场安装来源**，但不是 main 的 current source。
- 阶段 3–8 才是 **current main 里真正在跑的通用 Runtime**。
- 阶段 9 是**弯路**：走进去过、后来被证明专用、专用活代码已删除。
- 阶段 10 是**退役**。

---

## F. 明确哪些历史不要复活

1. **`#285` / `#287` / `#289` / `#290`（Boss 早期 Runtime 设计）**
   closed / unmerged。**不会因为没有 merge 就自动成为 current**。
   注意：其中 `#287` 的整树**就是**现场 `/opt/go/c1-c14-runtime/` 的 kernel 字节——但它是"现场已装"，不是"main 已有"。不要据此把 #287 当作可合并候选。

2. **`#331`–`#344`（Persistent Cell 槽位占位）**
   全部 closed / unmerged。它们只是当年为 C01-C14 **占位**的 Draft。
   **当前实现不是"14 个独立常驻 worker/service"**，而是：
   **一个 Generic Builder + 一条 review transport**（外加 kernel / agent / bridge）。
   任何从这 14 个 PR 推导"14 个常驻 worker"的结论都是错的。

3. **`#383`（Boss per-cell auto ingress，per-cell 设计）**
   open Draft，Boss-owned。**不是 current architecture**。
   它提出的"每个 Cell 一个 consumer/worker systemd 模板"路线，
   已被阶段 5 的 **Generic C01-C12 泛化** 取代（`#389`）：
   现在是一个 Builder workflow + 一个 review worker，**没有** 13 个常驻 worker。

4. **`#292`–`#297`（Runtime Host foundation 栈）**
   已归档关闭（unmerged）。**不要为了"补 lineage"把它们硬合入 main。**

5. **PG533 supplement 路径（`#534` / `#544` 引入）**
   专用活代码已在 `#553` 删除（`lite_pg533.py` / `lite_pg533_plugin.py` /
   `lite_supplement_preflight.py` / `c1_c13_supplement_contract.py` /
   `c1_c13_supplement_ingress.py` 及相关测试文件）。
   **它不是 current Runtime capability，是一条已经走完并被清理的弯路。**

6. **Legacy standalone C1 Responses executor**
   源码 unit 已删除（`#555`），rt01 实体已删除。
   `AI_WORK_V1` / `AI_TASK_V1` / `c1-ai-execution-backend-v1.yml` 词汇**保留**（协议兼容），
   但**没有**任何常驻单元再用它们当独立执行器。

7. **historical evidence 不应重新变成 current authority**
   历史 PR / 旧 checkpoint / 名为 `CURRENT` 的旧文件，都不能覆盖 live GitHub / 现场 / 当前 Evidence。

---

## G. Known non-blockers（记录在案，**不需要继续修**）

以下都是本轮（含上一轮 closeout）已定性为**无害**的项。请**不要再**拿它们开新 Runtime PR。

1. **`c1_dispatch_outbox.py` 字节漂移**
   现场 `52d2d816…`（= 提交 `a04c0fe0e`，2026-10-04 装机）vs main `2cd7719a…`。
   整份文件唯一差异是 `DispatchOutbox.__init__` 多了一个**可选**关键字参数 `*, read_only=False`（+7/−1）。
   分类：**C `SEMANTICALLY_EQUIVALENT_DRIFT`**。
   证据：两树 A/B 全绿且失败集完全相同（`655 OK` / `295 OK(skipped=1)`），20 步语义探针逐项一致。
   **claim / dispatch / 状态机 / idempotency / failure handling / run adoption 全无影响。**

2. **main 上孤立的 `read_only` 参数**
   `read_only=True` 的**唯一**调用方是 `c1_c13_supplement_ingress.py`，已随 `#553` 退役。
   因此 main 侧那 7 行现在是**零调用方死代码**。**保留即可，不要为它开 PR。**

3. **`c1_worker.py` 的 docstring-only 漂移**（现场 `33a1e26d` vs main `b491e7c7`）
   去掉 docstring 后 AST 完全相同。**惰性、无行为差。**

4. **consumer 目录的 `c1_worker.py`（`04f2399a`，来自 `#389`/U7A）**
   现役 consumer **不 import** 它。**惰性**。

5. **review worker `--check` 状态行显示 shared worker 的单数 `dispatch_target`**
   纯显示问题；review client 实际已正确绑定 `c14-rule-compliance.yml` / `c13-quality-acceptance.yml`。
   不是执行 / dispatch 缺陷。**除非状态 UX 真的造成操作困惑，否则不修。**

6. **`go-runtime-host-registration-sync` 是 `disabled` 但有 enabled timer**
   `disabled` **不等于没人用**。它被同名 timer 周期性拉起。
   判"有没有人用"必须同时看：`is-active` + `RequiredBy/WantedBy` + `*.wants/` 符号链接 + 是否有 timer。

7. **早于本轮的一条 `QUEUED` 任务**（`AI_GHAW_HELLO_V1 ghaw-restart:…`）
   存在于 runtime.db，早于本轮治理。**不属于本轮问题，不处理。**

8. **Runtime Host agent/bridge 源码不在 main（§D.4）**
   `REAL_FAILURE_PREVENTED` 写不出来 ⇒ 按节奏原则**不做** source-alignment。
   记录在案，source-of-record 指向分支/PR #297。

---

## H. Freeze rule

### H.1 只有下面这些**真实故障**允许重新打开 Runtime

- Formal C01-C12 任务**无法进入** Runtime；
- durable task **丢失**；
- **duplicate paid dispatch**（重复付费派发）；
- **lease / attempt fencing 失效**；
- **wrong candidate identity / wrong task adoption**（采纳了错误的候选）；
- Generic Builder **普遍无法**产出 Draft PR；
- C14/C13 的通用正确性缺陷会产出**错误 PASS** 或审错候选；
- **recovery 无法恢复**真实在途任务。

### H.2 下面这些**不是** reopen 理由

- 文件名不好看；
- byte SHA 不完全一样但**行为等价**；
- 历史 dead code 还剩几行；
- 想让架构"更正规 / 更统一"；
- 为某一个 candidate 再做专用 verifier / supplement。

---

## I. Runtime 与产品的边界

```text
Runtime delivered != GO product done
```

Runtime 只是"老板派活 → 产出 Draft PR → 自动审核"的**执行与审核运输层**。
它不判断产品质量，不 merge，不 deploy。

下一阶段主线应回到产品：

```text
UX Evidence Pack → UX Contract → Hotel Onboarding → Browser E2E → Product Done
```

请**不要**再因为 Runtime 有工具问题而持续偏离产品主线。

---

## J. Boss 终点

> 如果只想确认 Persistent Runtime 是否已经交付、当前怎么用、哪些历史不要再碰，**请以本 PR 为最终入口**。

- **不要再为 Persistent Runtime 开新的架构 PR。**
- **不要复活** §F 列出的历史设计。
- 派活只做一件事：**建一张 C01-C12 Formal Issue**。
- 用法细节见 `docs/runtime/README.md`。

---

## 附录 A · Persistent Runtime PR inventory（完整）

`Role` 取值：FOUNDATION / EXECUTION_BACKEND / ISSUE_INGRESS / BUILDER / REVIEW_TRANSPORT /
HARDENING / HISTORICAL_DESIGN / SUPERSEDED / CLEANUP / DOCUMENTATION / CANARY_EVIDENCE。
`Action` 取值：KEEP_MERGED_HISTORY / CLOSE_SUPERSEDED / CLOSE_HISTORICAL / MERGE_REQUIRED /
BOSS_HISTORY_COMMENT_ONLY / NO_ACTION。

### A.1 Boss 早期 Runtime 设计（HISTORICAL_DESIGN / NEVER CANONICAL）

| PR | Owner | State | Merged | Head | Role | Current relevance | Action | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| #285 | boss | closed | no | `f7e4217113b3…`树 | HISTORICAL_DESIGN | 早期 24x7 kernel，非 main | NO_ACTION | 已关；kernel 字节现装于 rt01，但不可合并 |
| #287 | boss | closed | no | `b40b07c76e…` | HISTORICAL_DESIGN | **现场 kernel 整树字节来源** | NO_ACTION | 已关；"现场已装" ≠ "main 已有" |
| #289 | boss | closed | no | `94aa9902aa…` | HISTORICAL_DESIGN | 目标主机拓扑文档 | NO_ACTION | 已关 |
| #290 | boss | closed | no | `481de5f7bc…` | HISTORICAL_DESIGN | 专用主机注册 | NO_ACTION | 已关；#292-297 的 stack base |

### A.2 我方 Runtime Host foundation（SUPERSEDED / 本次归档关闭）

| PR | Owner | State | Merged | Head | Role | Current relevance | Action | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| #292 | eason | open→closed | no | `d943689da501` | FOUNDATION | 栈的第 1 步 | CLOSE_SUPERSEDED | 内容被栈顶 #297 完整包含 |
| #293 | eason | open→closed | no | `c1aab868c776` | FOUNDATION | 注册续期 / 常驻 | CLOSE_SUPERSEDED | 同上 |
| #294 | eason | open→closed | no | `447f89571c58` | FOUNDATION | 单轮 Git 快照 | CLOSE_SUPERSEDED | 同上 |
| #295 | eason | open→closed | no | `390e1d17516a` | FOUNDATION | C1 bridge 最小闭环 | CLOSE_SUPERSEDED | 同上 |
| #297 | eason | open→closed | no | `1e442d5db1a8` | FOUNDATION | **现场 agent/bridge 的 de-facto source-of-record** | CLOSE_HISTORICAL | 见 §D.4；不硬合入 main，分支保留 |

### A.3 C1 真实执行 + Issue 入口（CURRENT）

| PR | Owner | State | Merged | Merge SHA | Role | Current relevance | Action | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| #300 | eason | closed | no | — | EXECUTION_BACKEND | 被 #303 取代 | NO_ACTION | 已关 |
| #303 | eason | closed | **yes** | `5968d62e80` | EXECUTION_BACKEND | C1 GitHub AI backend | KEEP_MERGED_HISTORY | current |
| #304 | eason | closed | **yes** | `7de1382938` | EXECUTION_BACKEND | Runtime→GitHub→Runtime 闭环 | KEEP_MERGED_HISTORY | current |
| #305 | eason | closed | **yes** | `b616d92ed5` | EXECUTION_BACKEND | `AI_WORK_V1` worker | KEEP_MERGED_HISTORY | 代码仍在；独立 unit 已退役(#555) |
| #310 | eason | closed | **yes** | `4931fc3374` | HARDENING | resume before claim | KEEP_MERGED_HISTORY | current |
| #321 | eason | closed | **yes** | `fd7b472cd3` | EXECUTION_BACKEND | 真实任务契约 | KEEP_MERGED_HISTORY | current |
| #322 | eason | closed | **yes** | `e952f4ee46` | HARDENING | 失败 run 终态结算 | KEEP_MERGED_HISTORY | current |
| #327 | eason | closed | **yes** | `dd54b03035` | ISSUE_INGRESS | GitHub Issue 入口 | KEEP_MERGED_HISTORY | current |
| #329 | eason | closed | **yes** | `f4ce7e6e1f` | ISSUE_INGRESS | 最小 C01 Issue consumer | KEEP_MERGED_HISTORY | current |

### A.4 Persistent Cell 槽位占位（NEVER CANONICAL）

| PR | Owner | State | Merged | Role | Action | Reason |
| --- | --- | --- | --- | --- | --- | --- |
| #331–#344 | eason | closed | no | HISTORICAL_DESIGN | NO_ACTION | 14 个占位 Draft；**不代表 14 个常驻 worker** |

### A.5 Generic C01-C12 Builder + 自动 C14/C13（CURRENT）

| PR | Owner | State | Merged | Merge SHA | Role | Action | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| #381 | eason | closed | **yes** | `ff72392232` | BUILDER | KEEP_MERGED_HISTORY | gh-aw executor/outbox 正式化 |
| #386 | eason | closed | **yes** | `0e7499557e` | BUILDER | KEEP_MERGED_HISTORY | 注册 gh-aw Builder workflow |
| #387 | eason | closed | **yes** | `b6b114a46d` | BUILDER | KEEP_MERGED_HISTORY | 启用改码测试与 Draft PR |
| #389 | eason | closed | **yes** | `a505b5ac9e` | BUILDER | KEEP_MERGED_HISTORY | **最小泛化到 C01-C12** |
| #391 | eason | closed | **yes** | `e4076276d7` | HARDENING | KEEP_MERGED_HISTORY | dispatch run 名带 cell |
| #392 | eason | closed | **yes** | `beb20ff234` | ISSUE_INGRESS | KEEP_MERGED_HISTORY | 拒绝旧 source + 绑定执行 SHA |
| #395 | eason | closed | **yes** | `a270ed8337` | REVIEW_TRANSPORT | KEEP_MERGED_HISTORY | C14→C13 接入 Runtime |
| #396 | eason | closed | **yes** | `d58f020b3b` | HARDENING | KEEP_MERGED_HISTORY | 首次真实 C14 派发修复 |
| #397 | eason | closed | **yes** | `c0f4f565aa` | HARDENING | KEEP_MERGED_HISTORY | 付费派发前确认 lease |
| #398 | eason | closed | **yes** | `1faf0faedf` | REVIEW_TRANSPORT | KEEP_MERGED_HISTORY | Formal Review Issue ingress |
| #402 | eason | closed | **yes** | `bdaba56bbb` | REVIEW_TRANSPORT | KEEP_MERGED_HISTORY | **Draft PR 自动推进 C14/C13** |
| #400 | eason | closed | **yes** | `8b93153081` | DOCUMENTATION | KEEP_MERGED_HISTORY | 刷新 current state |
| #401 | eason | closed | **yes** | `57b250324e` | DOCUMENTATION | KEEP_MERGED_HISTORY | 老板使用 README |
| #405 | eason | closed | **yes** | `5dac84fd26` | DOCUMENTATION | KEEP_MERGED_HISTORY | 记录全自动链 |
| #406 | eason | closed | **yes** | `5ff80dfb2c` | DOCUMENTATION | KEEP_MERGED_HISTORY | 正式交付说明 |

### A.6 Hardening（CURRENT）

| PR | Owner | State | Merged | Merge SHA | Role | Action | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| #419 | boss | closed | **yes** | `ee4a0a4ea4` | HARDENING | KEEP_MERGED_HISTORY | Builder 60 AIC 预算中断修复 |
| #427 | boss | closed | **yes** | `32060c6384` | HARDENING | KEEP_MERGED_HISTORY | rebind 陈旧 acceptance source |
| #428 | boss | closed | **yes** | `fef946b129` | HARDENING | KEEP_MERGED_HISTORY | 收窄历史门禁触发范围 |
| #442 | boss | closed | **yes** | `bf633805b7` | HARDENING | KEEP_MERGED_HISTORY | 读已关闭候选 brief |
| #449 | boss | closed | **yes** | `be2816965b` | HARDENING | KEEP_MERGED_HISTORY | 防 task-ID 冲突 / ingress 隔离 |
| #470 | boss | closed | **yes** | `16604794d5` | HARDENING | KEEP_MERGED_HISTORY | C13 独立测试路径 / machine inventory |
| #483 | boss | closed | **yes** | `0d3f343ace` | HARDENING | KEEP_MERGED_HISTORY | review 完整 PR diff |
| #485 | boss | closed | **yes** | `00dcf6007f` | HARDENING | KEEP_MERGED_HISTORY | C13 补齐 Node / 隔离预检输出 |
| #539 | boss | closed | **yes** | `d8c96154ff` | HARDENING | KEEP_MERGED_HISTORY | C09 审批要求作为 C14 来源 |
| #540 | boss | closed | **yes** | `2802ccef51` | HARDENING | KEEP_MERGED_HISTORY | 把冻结的 pytest node id 传给 C13 |

### A.7 PG533 弯路与清理（引入已 merge，专用代码已 RETIRED）

| PR | Owner | State | Merged | Merge SHA | Role | Action | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| #534 | boss | closed | **yes** | `2d59d0a826` | HISTORICAL_DESIGN | KEEP_MERGED_HISTORY | 引入 PG533 supplement（历史瞬间） |
| #544 | boss | closed | **yes** | `e076256c01` | HISTORICAL_DESIGN | KEEP_MERGED_HISTORY | 绑定 #533 最后一个 slot（历史） |
| #546 | eason | closed | **yes** | `e9b3676fde` | HARDENING | KEEP_MERGED_HISTORY | PG533 V2 activation guard |
| #553 | eason | closed | **yes** | `5f2bac316c` | CLEANUP | KEEP_MERGED_HISTORY | **删除 PG533 专用活代码（8 删 + 4 改）** |
| #554 | boss | closed | no | — | HISTORICAL_DESIGN | NO_ACTION | Boss 自标 SUPERSEDED / CLOSED |
| #549 | eason | closed | **yes** | `ae5b8e2dbde2` | CLEANUP | KEEP_MERGED_HISTORY | backend-entry 计数 pin 改为非空洞下限 |

### A.8 Legacy C1 清理 + 最终 handoff

| PR | Owner | State | Merged | Merge SHA | Role | Action | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| #555 | eason | closed | **yes** | `794dd21e44` | CLEANUP | KEEP_MERGED_HISTORY | 删除退役 legacy C1 systemd 入口 |
| 本 PR | eason | — | — | — | DOCUMENTATION | MERGE_REQUIRED | 最终 handoff |

### A.9 Boss-owned OPEN Runtime PR（**不治理其状态**，只补历史说明）

| PR | Owner | State | Role | 归类 | Action |
| --- | --- | --- | --- | --- | --- |
| #383 | boss | open Draft | HISTORICAL_DESIGN（per-cell 设计） | superseded by #389 泛化 | BOSS_HISTORY_COMMENT_ONLY |
| #425 | boss | open Draft | HARDENING（Builder Python 依赖准备） | non-blocking / still candidate | BOSS_HISTORY_COMMENT_ONLY |
| #480 | boss | open Draft | HARDENING（失败执行绑定 receipt） | non-blocking / still candidate | BOSS_HISTORY_COMMENT_ONLY |

> #383 / #425 / #480 的状态**保持原样**（不 merge、不 close、不 push、不改 head/body）。
> 其余 Boss-owned OPEN PR 属于 **Runtime 之外**的轴（HK 业务候选 / CI / Command Center / 法务文档），
> 不在本次 Runtime 治理范围内，**NO_ACTION**。

### A.10 Runtime 产生的候选 PR（Bot-owned，**不是** Runtime 架构 PR）

`github-actions[bot]` 名下的一批 OPEN Draft（`#371` `#388` `#390` `#394` `#404` `#421` `#424`
`#453` `#466` `#467` `#468` `#476` `#477` `#499` `#500` `#501` `#502` `#503` `#504` `#523` `#524`
`#525` `#526` `#527` `#543` …）是 **Runtime 的产物**（Builder 针对具体 C01-C12 任务产出的候选），
不是 Runtime 自身的开发 PR。

- `#394`（历史 review-ingress canary）与 `#404`（2026-10-04 全自动链 canary）是 **CANARY_EVIDENCE**。
- 其余是**产品候选**，其 merge / close 属于产品线的决定，**不属于** Runtime 治理。
- **NO_ACTION**（本次不碰）。

### A.11 Runtime 之外的相邻轴（明确排除）

以下 PR 名字里带 "runtime"，但属于**其它轴**，本次不治理、不合并、不关闭：

- HK 业务 runtime 指针 / canonical baseline：`#302` `#306` `#308` `#318` `#320` `#328` `#376` `#377` `#378`
- Command Center V1（CCV1）：`#316` 等 `control-plane/boss-deploy-request-v1` / `hk-staging/*` 系列
- GO Forge：`#325` `#369` 等（本次授权明确不含 GO Forge 自身）
- 其它纯业务 PR（RIDE / money / hotel / registration / C11 …）

**记法**：`Repository source` · `Business runtime (HK-STAGING)` · `Persistent Runtime (rt01)` 是**三条独立的轴**，不能互相推断。

---

## 附录 B · 复现信息

**收口 main**：`794dd21e44b5fb41b94b96a18575537de262a76e`

**现场只读回读命令（不写任何东西）**：

```bash
ssh go-rt01 'systemctl list-units --all "go-*"; systemctl is-active go-runtime-host-*'
```

**推荐的上游读法**：`docs/project/GO_CURRENT_STATE.md` → 本文件 → `docs/runtime/README.md`
