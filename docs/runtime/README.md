# GO Persistent Runtime — 老板使用说明

> 面向 Product Owner / Boss。只讲“怎么派活、怎么发审核”。  
> Runtime 的内部实现、安装、lease、outbox、systemd 和故障恢复不需要任务发起人操作。

## 你实际只需要做两件事

### 1. 给 C01-C12 派一个开发任务

在 GO 仓库新建一个 **GitHub Issue**。

标题固定为：

```text
Cxx · <task-id> · <scope>
```

例如：

```text
C08 · V71-R1-C08-01 · improve trip-planning handoff
```

正文至少写：

```text
Task: Improve the trip-planning handoff so the next execution step is explicit and testable.

Canonical source: <CURRENT_MAIN_SHA>
```

规则：

- `Cxx` 只能是 **C01-C12**。
- task id 格式必须是 `V<number>-R<number>-Cxx-<number>`，而且里面的 Cell 必须和标题一致。
- 标题第三段就是任务 scope。
- `Task:`（或 `Successor task:`）后面写真正要做什么。
- `Canonical source:` 必须是**创建 Issue 当时 GO 仓库 current main 的完整 40 位 SHA**。
- 不要从旧 Issue、聊天记录或 README 示例里复制一个旧 SHA。
- 新一轮任务请新建 Issue / 新 task id；不要只在旧 Issue 评论里改 task id。

Issue 创建以后，正常链路是：

```text
Formal Issue
→ Persistent Runtime
→ C01-C12 Generic Builder
→ GitHub Agentic Workflow
→ inspect / edit / test
→ exactly one Draft PR
→ Runtime adopts result
```

任务发起人不需要登录 rt01，不需要 dispatch workflow，也不需要操作 Runtime。

---

### 2. 让 C14/C13 审核一个候选 PR

需要审核某个候选 PR 时，新建一个 **GitHub Issue**。

标题固定为：

```text
C14 · REVIEW · <description>
```

正文只需要：

```text
Candidate PR: #<PR_NUMBER>
Candidate SHA: <EXACT_CURRENT_PR_HEAD_SHA>
```

例如：

```text
C14 · REVIEW · review the current hotel checkout candidate

Candidate PR: #394
Candidate SHA: 0cb92ac7900cd177be383a4429a2759007119a10
```

注意：

- **不要创建 `C13 · REVIEW` Issue。**
- Issue 只能启动 C14。
- 只有 C14 的 sealed result 允许继续时，Runtime 才会自动创建 C13。
- Candidate SHA 必须等于这个 PR **创建 Review Issue 时的当前 head**。
- 如果 PR 后来又 push 了新 commit，旧 Review Issue 会被拒绝；对新的 head 新建一张 Review Issue。
- C13/C14 只做审核和 Evidence，**不会 merge，也不会 deploy**。

正常链路：

```text
C14 · REVIEW Issue
→ Runtime C14_REVIEW_V1
→ C14 review
→ sealed result
→ if admissible: Runtime automatically creates C13_REVIEW_V1
→ C13 review + focused machine tests
→ sealed round decision
→ Runtime adopts result
```

---

## C01-C12 是干什么的

| Cell | 主要职责 |
| --- | --- |
| C01 | Hotel AI Operations |
| C02 | Flight AI Operations |
| C03 | Rail AI Operations |
| C04 | Rental AI Operations |
| C05 | Ride AI Operations |
| C06 | Attraction AI Operations |
| C07 | Traveler Intelligence |
| C08 | GO AI Planning & Execution |
| C09 | GO Judgment & Trust |
| C10 | Unified Trips |
| C11 | Transaction & Finance |
| C12 | Platform / Security / Model Gateway |

C13 / C14 是 control-only review Cells，不接受普通 Builder task。

---

## 最简单的老板用法

如果通过连接 GitHub 的 Boss GPT 操作，不需要老板自己填写这些格式。

可以直接告诉 Boss GPT：

```text
请在 yuguangzhi3836-glitch/GO 创建一个给 C08 的正式任务 Issue。
先读取当前 main SHA，再按 GO Persistent Runtime 的 Formal Issue 格式创建。
任务：把行程规划后的下一步执行动作做得更明确，并补必要测试。
不要直接改代码，只创建任务 Issue。
```

或者审核：

```text
请审核 PR #394。
先读取 PR 当前 head SHA，然后按 GO Persistent Runtime 的 Formal Review Issue 格式创建 C14 Review Issue。
不要直接创建 C13 Issue，不要 merge，不要 deploy。
```

关键不是使用哪一个聊天工具，而是**最终落到 GitHub 的 Issue 必须符合上面的正式格式**。

---

## 创建以后还要不要人工搬任务？

不用。

当前已经 LIVE 的 resident consumer 会自动扫描正式 Issue 并交给 Persistent Runtime。

### Builder Issue

重复扫描同一张 Issue 会命中同一个 Runtime idempotency identity，不会因为一直 open 就重复创建同一个任务或重复付费。

Builder 正常成功后会生成 Draft PR。

### Review Issue

重复扫描同一张 Review Issue同样不会创建第二个相同 review round。

Review 完成以后建议关闭 Issue，方便仓库保持干净；关闭只是整理，不是 Runtime 正确性的前提。

---

## 当前一个有意保留的边界

Formal Issue 是**任务入口**，不是聊天式状态面板。

当前 Runtime 不要求 consumer 回写 Issue 评论，也不会让 C13/C14 自动 merge/deploy。

所以：

- Builder 的主要可见产物是 Draft PR；
- C13/C14 的正式结果在 Runtime / GitHub Actions sealed artifacts / Evidence 中；
- 如果希望未来“审核完成自动给老板 Issue 回一条人话总结”，那是一个独立的产品 UX 功能，不是当前 Runtime transport 的缺陷。

---

## 常见拒绝原因

| 情况 | 结果 |
| --- | --- |
| Builder Issue 的 `Canonical source` 不是 current main | 拒绝，不运行付费 Builder |
| main 在入队后、执行前发生变化 | workflow 再次检查 SHA，不一致则在付费 agent 前停止 |
| Review Issue 的 Candidate SHA 已不是 PR 当前 head | 拒绝，不自动跟随新 commit |
| 直接创建 `C13 · REVIEW` | 拒绝 |
| task id 的 Cell 和标题 Cell 不一致 | 拒绝 |
| 缺少 Task / source / PR / SHA 等必填身份 | 拒绝而不是猜 |

原则是：**身份不确定就不执行，不偷偷修成“差不多对”。**

---

## 当前状态与技术资料

当前项目状态：

- [GO current state](../project/GO_CURRENT_STATE.md)
- [Context checkpoint](../project/CONTEXT_CHECKPOINT.json)

技术实现目录：

- [Runtime Host channel](../../control-plane/runtime-host-channel-v1/)

历史设计/验证文档在本目录中保留用于工程审计；老板日常派活以本 README 为准。

---

## 一句话

```text
C01-C12：发 Formal Task Issue。
C13/C14：发 C14 Formal Review Issue。
剩下的交给 Runtime。
```
