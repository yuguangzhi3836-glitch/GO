# Runtime Builder · C01–C12 泛化（U7A）

**日期**：2026-10-04
**Base**：`main` = `b6b114a46d226f4f1739103536f2e5b0941a02f8`
**性质**：candidate only —— 未合并、未装机、未派发、未调用任何模型。

---

## 1. 本轮要解决的问题

C01 的 gh-aw Builder 已经真实端到端通过（PR #388：Runtime → gh-aw → 改码 → 测试 → Draft PR → artifact → adoption → `SUCCEEDED`）。但它只服务一个 cell：worker 的 `OWNER_C = "C1"`、payload 校验器要求 `cell_id == "C1"`、workflow 的收单门只接受 `C1/C01`、completion 硬编码 `runtime.complete("C1", …)`。

目标不是「再造十二套」，而是让**同一套已证明的执行器**服务 C01–C12，同时：

- C13/C14 保持 special control-only，**不被改造成 Builder**；
- C1 已经真实跑过的执行身份**逐字节不变**；
- 不复制 12 个 worker / outbox / workflow / unit / 队列。

---

## 2. 结构：一套，cell 随任务走

```text
C01 ┐
C02 │
... ├─→ GHAW_BUILDER_V1 ─→ ONE resident worker ─→ ONE outbox ─→ ONE workflow ─→ ONE Runtime DB
C12 ┘
```

真正区分 executor 的是 **`(owner_c, task_kind)`**，而 `owner_c` 来自任务本身，不来自进程。

| | 值 |
|---|---|
| kind | `GHAW_BUILDER_V1`（唯一，未按 cell 拆分） |
| owners | `C1`..`C12`（`contract.BUILDER_OWNER_CS`） |
| outbox | `/var/lib/go-runtime-c1/outbox-ghaw-builder.db`（唯一，路径名保留 `c1` 不改） |
| worker id | `go-runtime-host-ghaw-builder-worker` |
| workflow | `.github/workflows/c1-gh-aw-builder-v1.{md,lock.yml}`（唯一） |
| Runtime DB | `/var/lib/go-c-runtime/runtime.db`（与 Responses worker 同一个） |

**Runtime kernel 一行未改。**

---

## 3. C1 硬编码在哪里被移除

| 位置 | 原来 | 现在 |
|---|---|---|
| `c1_execution_contract.validate_task_payload` | `cell_id != OWNER_C → TASK_PAYLOAD_CELL_IS_NOT_C1` | 按 `allowed_owner_cs` 判，逐 kind 派生 |
| `c1_execution_contract.task_binding` | `"owner_c": OWNER_C` | `"owner_c": payload["cell_id"]`（已规范化） |
| `c1_execution_contract.run_identity_name` | `"C1 %s %s %s"` | `"%s %s %s %s" % (owner_c, …)`，`owner_c` 默认 `C1` |
| `c1_execution_loop._not_our_task` | `owner_c != OWNER_C` | 按 **kind 的 owner 边界**判（`allowed_owner_cs_for_kind`） |
| `c1_worker.tick` | `runtime.claim(OWNER_C, …)` | 沿 `claim_owner_cs` 逐个 cell 询问，`max new claims = 1` |
| `c1_ghaw_builder_worker` | `OWNER_C = "C1"` | `CLAIM_OWNER_CS = allowed_owner_cs_for_kind(GHAW_BUILDER_KIND)` |
| `c1_result_pull.complete_after_pull` | `runtime.complete("C1", …)` | `runtime.complete(binding["owner_c"], …)` |
| `c1_result_pull.fail_after_pull` | `runtime.complete("C1", …)` | `runtime.complete(outbox.owner_c_for(request_id), …)` |
| `c1_issue_ingress` | `INGRESS_OWNER_C`，`INGRESS_ISSUE_IS_NOT_C01` | `INGRESS_OWNER_CS`（派生），`INGRESS_CELL_NOT_OWNED_BY_BUILDER_EXECUTOR` |
| `c1_issue_consumer` | `looks_like_c01()`，只认 `C01` | `looks_like_builder_issue()`，向 ingress 询问 `is_builder_cell()` |
| workflow | 收单门只接受 `C1/C01`；`allowed-branches: c01-builder/*` | 收单门校验 `owner_c`；`allowed-branches: builder/*` |

---

## 4. C1 身份如何被冻结

改动全部落在 **kind 无关**的地方，且对 C1 渲染结果不变：

- `task_binding` 的 `owner_c` 对 C1 任务取 `payload["cell_id"] == "C1"` —— 与原常量同值；
- `prompt_for_task` 的首行由 `"GO C1 real task (…)"` 改为 `"GO %s …" % cell_id` —— 对 C1 逐字节相同；
- `run_identity_name` 默认 `owner_c=OWNER_C` —— 无 owner 参数的调用完全相同；
- `dispatch_inputs` 只为 `GHAW_BUILDER_KIND` 增加 `owner_c`，`REAL_DISPATCH_INPUT_NAMES`（Responses real）**未变**。

冻结由**黄金值测试**钉住（`test_c1_cell_generalization.C_TheLiveC1IdentityIsFrozen` / `D_TheLegacyResponsesIdentityIsFrozen`），黄金值取自 `origin/main` 的旧契约实算：

```text
GHAW C1  execution_request_id = ba75f59ee2547d4168ffc7480943004cfabf9f41933626039ef567b2f51c5401
GHAW C1  prompt_sha256        = 323a0c0a893ff43c4a34184effa6e6168bf6d87d2aeaaf4e0cc6652face099ec
REAL C1  execution_request_id = 1fcb7598a6f14802750605428ee5116e1cdb45c70c1cc86e545cd092faf2b4bf
SMOKE    execution_request_id = 12d810e9b7a3c51d04d37d7a88074ee59d18de9582a2068dc1fc536006e20eba
GHAW C1  idempotency_key      = c1-ghaw-builder-v1:C1:C01-GOLDEN-1
REAL C1  idempotency_key      = c1-ai-task-v1:C1:C01-GOLDEN-1
SMOKE    idempotency_key      = c1-real-ai-worker-v1:smoke:1
```

---

## 5. Payload 校验：三段分离，不复制第二个校验器

```python
validate_task_payload(payload, *, allowed_owner_cs=LEGACY_OWNER_CS)
```

1. **形状** —— 字段集 / 必填 / schema 版本 / 文本上限（与 kind 无关）
2. **规范化** —— `canonical_cell_id()`，仍然认识 C1–C14（全局解析器不许破坏）
3. **边界** —— `allowed_owner_cs`，唯一 executor-相关的一步

默认值 = Responses executor 的集合 `("C1",)` ⇒ 现有调用者语义不变。边界由 **kind 派生**，不是调用者传入：

```python
allowed_owner_cs_for_kind(kind):
    GHAW_BUILDER_V1        -> ("C1", …, "C12")
    AI_WORK_V1 / AI_TASK_V1 -> ("C1",)
```

因此「C1..C12」在整个 channel 里**只定义一次**：worker 的 `CLAIM_OWNER_CS`、ingress 的 `INGRESS_OWNER_CS`、loop 的 owner 门全部读它。

`canonical_cell_id` 仍然是**正确解析出 `C13`/`C14`** 的（kernel 确实是 14 个 cell）；把它们排除出去是 executor 的 owner 集合在做的事，不是破坏解析器。

---

## 6. C13/C14：三层独立拒绝

```text
① worker 的 CLAIM_OWNER_CS 不包含 C13/C14   → 从不 claim
② contract 的 payload 校验器拒绝             → 建不出任务
③ workflow 的 pre-agent gate 拒绝            → 派到也不跑
```

第三层是独立的一道：workflow 在自己的 checkout 里**无法 import contract**，所以它**自带**范围：

```python
builder_cells = tuple("C%d" % n for n in range(1, 13))
```

顺序（每一步都可达）：

```text
OWNER_C_MISSING
OWNER_C_NOT_OWNED_BY_BUILDER_EXECUTOR      ← owner 是控制类 cell
TASK_PAYLOAD_CELL_NOT_OWNED_BY_BUILDER_EXECUTOR  ← payload 是控制类 cell
OWNER_C_DOES_NOT_MATCH_TASK_PAYLOAD        ← 两边都在范围内但不一致
```

`owner_c` 必须是**规范拼写**（`C1` 而非 `C01`）—— contract 发出的就是规范拼写，非规范即说明这次派发不是来自 contract，不做静默调和。

---

## 7. 调度：cursor 是便利，不是权威

```text
1. outbox unfinished FIRST
2. resume in-flight FIRST
3. 仅当无在途：沿 C1..C12 顺序询问，取「最老 QUEUED」
4. 每次 tick 最多新增 1 个 claim
```

- cursor 是 `main()` 里的一个局部 `int`，**不持久化**、重启从 C1 重来（允许）；
- **scan 起点不进入任何身份**：identity / idempotency / `execution_request_id` 全部由任务本身派生；`test_c1_cell_generalization.H` 用不同 cursor 断言同一身份；
- 全局并发仍是 **一个 Builder 执行在途**；`claim(kinds=)` 语义、lease、attempt fencing、exactly-once 全部沿用，未新增池 / 并行 / per-cell worker。

不新增：executor registry / cell registry / router / scheduler / PR broker / path-policy DB / 第二 Runtime / 第二队列 / 第二种数据库技术。

---

## 8. `owner_c` 作为 dispatch 身份输入

`GHAW_BUILDER_INPUT_NAMES = REAL_DISPATCH_INPUT_NAMES + ("owner_c",)`

- 值从 binding 复制，**不是调用者输入**；
- workflow 用它做第二道比对；
- Responses real class **不变**（`REAL_DISPATCH_INPUT_NAMES` 原样，无 `owner_c`）；
- `run-name` 改为 `"${{ inputs.owner_c }} …"` ⇒ C1 渲染出与现场已记录**完全相同**的字符串。

---

## 9. completion / failure 的 owner 来自哪里

`outbox.completion_binding()` 现在多返回一个 `owner_c`，`owner_c_for(request_id)` 是新读取点，两者都从**这条身份注册时存下的 request** 里读（`request_json`），并在契约前的历史行上回退为 `C1`（那类行按构造就是 smoke）。

```text
C12 任务 → request.owner_c = C12 → outbox 持久化 → 重启 → resume → Runtime.complete("C12", …)
C7  失败 → Runtime.complete("C7", success=False)     ← 不再落到 C1
```

`fail_after_pull` 里 owner 在 `try` **之外**解析：缺 owner 是我们自己的缺陷，不是 Runtime fence 的拒绝，不能被当成后者吞掉。

---

## 10. U6 Solution-Leak Gate：只有 seam，没有实现

新模块 `c1_solution_leak_gate.py`：

```text
SOLUTION_LEAK_GATE_ENABLED = False
enabled=False  decision=PASS  reason=GATE_DISABLED  reviewed=False  model_called=False  calls=0
```

**`GATE_DISABLED` 与「DeepSeek 审过且 PASS」语义严格不同**：bypass 的记录里 `reviewed=False`；下游不得只看 `decision` 就当作审过。

开关打开但没有 checker：

```text
raise Refused("SOLUTION_LEAK_GATE_NOT_IMPLEMENTED")
```

不是 PASS —— 「翻开关以为启用了门、而门并不存在」正是这个文件要防的失败。

本轮：DeepSeek 调用 = 0、无 SDK、无 secret、无 API 配置、无网络。

`plan_ingress` 已经把 gate 记录放进 plan（`solution_leak_gate`），所以将来接 checker 时**调用点不用改**。

---

## 11. Issue 路径泛化

一个 consumer 服务 C01–C12，不是十二个。

```text
title → 解析 cell → canonical → 非 control-only → U6 bypass gate → Runtime.enqueue(owner_c = cell)
```

- `c1_issue_consumer` 不新增 `parse`、不做 cell 判定：它向 ingress 询问 `is_builder_cell()`，保证 pre-filter 与硬门**用同一个答案**；
- GitHub 侧仍然 **READ ONLY**（不评论 / 不贴标签 / 不关闭 / 不改 issue）；
- **无本地 seen 表**：重复 poll 仍依赖 Runtime 的 idempotency（`UNIQUE(idempotency_key)`），没有第二套去重。

---

## 12. 验证

WSL `Ubuntu-24.04` / root / ext4 / `PYTHONDONTWRITEBYTECODE=1`：

- **全量**：`Ran 385 → 440 tests  OK`（+55）
- **变异 15/15 CAUGHT、0 MISSED、0 INVALID** —— 逐个把本轮新增的守卫拆掉，对应测试必红：
  contract 边界 / loop owner 门 / success 与 failure 的 completion owner / binding owner /
  worker 退回单 cell claim / worker owner 表放进 C13 / run-name 去掉 cell /
  prompt 退回硬编码 C1 / workflow 两道 owner 检查 / ingress cell 门 / pre-filter /
  U6 开关假启用 / U6 bypass 谎报 reviewed。
- **workflow 编译**：`gh-aw v0.89.21` / `strict` / codex，编译成功（134.2 KB）；
  与泛化前相同的唯一警告（缺 `concurrency.job-discriminator`），行为上产物是
  `cancel-in-progress:false` + queue，不互相取消。

**未证明**：workflow 是否已注册、派发是否送达、任何 cell 的工程质量。这是离线边界，不是 live run。

---

## 13. 本轮未做（以及为什么）

| 未做 | 原因 |
|---|---|
| merge / 装机 / 重启 / `workflow_dispatch` / 真实模型调用 | 本轮是 candidate；live 步骤需 Eason 当次授权 |
| 改 Runtime kernel | 不必要：`owner_c = C1..C14` 本来就支持 |
| 改 `control-plane/c13-c14-lite/**` | C13/C14 是另一条链，硬禁止 |
| 重命名 outbox / workflow 里的 `c1` | 命名不好看不是迁移理由；重命名会改掉已证明的路径与现场字节 |
| 改名 `NOT_A_C1_TASK` 这个 action token | 状态字，不是身份；重命名没有 `REAL_FAILURE_PREVENTED` |
| `GH_AW_CI_TRIGGER_TOKEN` / README 保护文件误报 / U5 清理 / U4 / U8 / U9 | 均非本轮 blocker |
| 提交 `.github/aw/actions-lock.json` | 编译器副产物，main 上从未跟踪，保持一致 |

---

## 14. 与 Boss #383 的关系

只读比对，**未改动、未引用、未依赖**。lineage 保持 `main → #381 → #386 → #387 → 本分支`。
若两者都引入 cell 概念，语义不同：本轮的 `owner_c` 是 Builder 的**执行边界**（一个 executor 服务十二个 cell），不是多 executor / 多 consumer 架构。
