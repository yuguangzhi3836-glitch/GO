# GO Runtime — Builder 完成后自动推进 C14 / C13（V1）

日期：2026-10-04
通道：`control-plane/runtime-host-channel-v1/**`
范围：把正常任务流的最后一处人工作业去掉。

---

## 1. 这一轮去掉的是什么

在此之前，一句准确的话是：

> Builder 能干活，但 **PR 出来之后没人审**。

审核入口有两条，两条都要人：

```text
deliver_review_round.py            （Eason 手工跑）
C14 · REVIEW · ... Issue           （Owner / Eason 手工建）
```

于是正常链路最后一步仍然是"人看到 PR，然后发起一轮审核"。这就是本轮唯一要消掉的东西。

现在的正常链路：

```text
C01-C12 Issue
→ Runtime
→ Builder（gh-aw）
→ exactly one Draft PR
→ 自动 C14
→ 自动 C13
→ sealed round decision
→ Runtime 收账
```

人只剩下：**发一张 Builder Issue**。

---

## 2. 关键约束：候选 PR 不能靠猜

Builder 的结果文件 `c1_result.json` 由 **agent job 的 post-steps** 封印，而 PR 由 **safe-outputs job** 创建 ——
后者在前者之后。所以结果文件里**物理上没有** PR 号，也无法从中读出来。

因此本轮明确拒绝：

* 按标题搜 PR
* 按时间取"最新的 `[Builder]` PR"
* 按 `builder/*` 分支名猜
* 解析模型的回答文字

正确来源是 **run 自己的记录**：gh-aw 的 safe-outputs job 把自己实际做了什么写进
`safe-output-items.jsonl`（`create_pull_request` 条目带 `number` / `url`），并以 artifact
`safe-outputs-items` 上传。Runtime 用**已有的** artifact transport 读它——这不是搜，也不是猜，
是运行自己说它做了什么。

### 为什么没有按原计划让 workflow 再封一个 candidate artifact

原本的想法是"在 safe-outputs 完成之后再生成一个新的 candidate artifact"。落地时发现这条路
在 gh-aw 上不成立，证据如下：

| 探测 | 结果 |
| --- | --- |
| `jobs.safe_outputs.steps` | 编译期拒绝：`steps are only supported for the activation job` |
| `jobs.safe_outputs.pre-steps` | 支持，但**在 Process Safe Outputs 之前**运行，看不到 PR 号 |
| `jobs.safe_outputs.setup-steps` | 同上，更早 |
| `jobs.conclusion.pre-steps` | 在 safe_outputs 之后，但 conclusion job 跑在 `ubuntu-slim`；现有 safe-outputs job 的 patch guard 注释明确写着该 runner 可能连 `diffutils` 都没有，要在那里拼 JSON 文档不可靠 |

也就是说：**要么手改 lock 文件**（本轮的硬性要求明确禁止，且下次 `gh aw compile` 会覆盖），
**要么把候选解析放在一个没有 Python 保证的 runner 上**。两条都不比"Runtime 读 run 自己的记录"
更安全，而后者还有一个额外好处：**它用的每一个读取能力都已经在生产上验证过**。

关于权限：任务要求"不要扩 Runtime Host token 权限"。本轮**没有扩**。部署中的 token 实测带有
Actions / Pull requests / Contents 的读权限（`GET /repos/...` 返回的 `permissions` 为
`admin/maintain/push/triage/pull`），而本轮新增的四个读取（PR / PR files / commit / tree）
全部是 **GET**，没有任何写权限。四个端点本轮也都在 rt01 上用真实 token 实测过。

---

## 3. 成立的结构

```text
Builder result sealed
   │
   ├─ read the run's OWN safe-output record      (artifact: safe-outputs-items)
   │     no create_pull_request entry  ────────► NO_CANDIDATE_PR：Builder 正常完成，不建审核
   │
   ├─ read the pull request it names             (GET PR / files / commit / tree)
   │     base != main / not draft / tree unresolved ─► 拒绝：不完成 Builder，不建审核
   │
   ├─ validate the candidate document            (身份 / run / PR / tree / 不授权任何动作)
   │
   ├─ Runtime.enqueue(C14_REVIEW_V1)   ◄── 确定性幂等键（来源 Issue + 冻结候选）
   │
   └─ Runtime.complete(Builder)        ◄── 顺序：先 enqueue，后 complete
```

顺序与 C14→C13 完全一致，理由也一样：**崩溃窗口靠 Runtime 自己的幂等键修复**。
先 complete 再 enqueue，则"封印后崩溃"会留下一个已完成的 Builder 任务和一个永远不存在的审核。

### 新增的常驻实体：0

| 项 | 数量 |
| --- | --- |
| Runtime kernel 改动 | 0 |
| 新 workflow | 0 |
| 新 worker / outbox / DB / scheduler / queue / registry | 0 |
| 新 Review 规则 | 0（判定、封存、prereq gate 仍全部来自 `control-plane/c13-c14-lite/**`） |

新增的只是**模块**：`c1_builder_candidate.py`（候选 + 钩子）与 `c1_candidate_reads.py`
（"怎么读一个冻结候选"的唯一实现，Owner 的 Review Issue 路径与 Builder 路径共用）。

---

## 4. 单一来源的收敛

本轮把三处"只能有一个答案"的东西收敛到契约里：

| 问题 | 唯一来源 | 之前 |
| --- | --- | --- |
| 这一轮是哪一轮 | `review_round_identity(issue_number, candidate_sha)` | 只在 Review Issue ingress 里 |
| C13 机器测试范围怎么算 | `review_test_inventory(changed_files)` | 只在 Review Issue ingress 里 |
| 怎么读一个冻结候选 | `c1_candidate_reads` | 只在 Review Issue ingress 里 |

Builder 路径复用它们，并把**来源 Issue 号**取成 Builder 任务自己的 Issue 号：
两条路径对"同一 Issue + 同一候选"必然得到**同一个 round**。

`review_round_identity` 的格式串在契约里出现**一次**，测试会拒绝任何其他文件出现它。

---

## 5. 语义边界（必须保持）

* **审核交付 ≠ 审核结论**。C14 判 FAIL/BLOCKED 仍然是一次**已交付**的审核：Runtime 任务 SUCCEEDED，
  只是不创建 C13。本轮没有改动这一点。
* **审核 ≠ 合并 / 部署**。candidate 文档自带 `authorizes_any_action: false`；即便 round decision 是
  ACCEPT，PR 仍是 Draft，merge / deploy 仍然要独立授权。
* **没有 PR 是合法结果**。Builder 正常完成，C14 / C13 数量都是 0。
* **候选不可信则不算完成**。Builder 任务保持未完成（Identity 在 outbox 里被结算并记下原因，
  Runtime 侧由自身 stale recovery 升级），绝不"看起来一切正常"地完成。
* **只审 Runtime 自己产出的候选**。不会因为"哪个 PR 存在"就自动审；入口只有 Builder 完成事件与
  Owner 的 Review Issue。

---

## 6. 验证

* `control-plane/runtime-host-channel-v1` 全量测试（含新增 `test_c1_builder_auto_review.py`）
* `control-plane/c13-c14-lite` 全量测试
* 变异：逐条破坏上述守卫，要求测试变红（详见 PR 正文与交接）
* 真实 E2E：见交接记录（一条 Builder Issue → Builder → Draft PR → C14 → C13）
