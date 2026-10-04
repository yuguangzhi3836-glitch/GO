# GO Persistent Runtime — Boss GPT / 14 Cell 使用说明

> 给余总 / Boss GPT 的唯一使用入口。
> 目标：老板只描述“要做什么”，Boss GPT 负责选择 C01-C12、创建正式任务；Runtime 自动完成 Builder → Draft PR → C14 → C13。
> 当前 normal path 已通过真实 LIVE E2E 验证。

## 1. 先记住一句话

```text
正常开发任务：
老板 → Boss GPT → 1 张 C01-C12 Formal Task Issue
→ Runtime → Builder → Draft PR → 自动 C14 → 自动 C13 → 审核收口

不要手工搬任务。
不要手工创建 C13。
不要因为审核通过就自动 merge / deploy。
```

Boss GPT 的职责是：

1. 理解老板要做什么；
2. 选择最合适的 **一个 C01-C12 Cell**；
3. 读取 GO 当前 live `main` SHA；
4. 创建一张符合格式的 Formal Task Issue；
5. 到此停止，后续交给 Persistent Runtime。

---

## 2. 14 个 Cell 怎么分工

| Cell | 当前正式职责 | Boss GPT 正常是否直接派任务 |
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

### C13 / C14 的特殊规则

C13、C14 是 control-only Cells。

正常开发链：

```text
C01-C12 Builder 产生 Draft PR
→ Runtime 自动创建 C14_REVIEW_V1
→ C14 审核
→ 如果 C14 准入
→ Runtime 自动创建 C13_REVIEW_V1
→ C13 审核 / focused machine tests
→ round decision
```

所以：

- Boss GPT **不要给 C13 发普通开发任务**；
- Boss GPT **不要为正常 Builder PR 再创建 C14 Review Issue**；
- Boss GPT **不要手工创建 C13 Review Issue**；
- C13/C14 的审核结论不拥有 merge / deploy 权限。

---

## 3. Boss GPT 如何选择 C01-C12

按任务的主要业务所有权选择，不要为了“多 Agent 看起来更强”同时发给多个 Cell。

- **C01 — Hotel**：酒店产品、酒店库存、酒店预订、酒店供应连接、酒店业务服务。
- **C02 — Flight**：航班搜索、航班供应连接、航班订单与航班业务能力。
- **C03 — Rail**：铁路 / 火车业务、铁路连接、铁路相关流程。
- **C04 — Rental**：租车业务。
- **C05 — Ride**：网约车 / 接送 / Ride 业务。
- **C06 — Attraction**：景点、门票、Attraction 业务。
- **C07 — Traveler Intelligence**：旅客画像、身份、偏好、Traveler Intelligence。
- **C08 — GO AI Planning & Execution**：跨业务规划、计划生成、任务执行编排、GO AI routing。
- **C09 — GO Judgment & Trust**：判断、推荐可信度、trust / judgment 规则。
- **C10 — Unified Trips**：统一行程、Journey、跨业务 Trip 组合。
- **C11 — Transaction & Finance**：支付、交易、补偿、Finance。
- **C12 — Platform / Security / Model Gateway**：平台基础能力、安全、可观测性、autonomy、workbench、Model Gateway、工程平台工具。

如果任务横跨多个领域：

> 选择“最终负责这个能力结果”的主 Cell，不要为了覆盖范围拆成多个并行重复任务。真正需要拆任务时再拆。

---

## 4. Boss GPT 创建任务的标准动作

老板可以自然语言告诉 Boss GPT，例如：

```text
把酒店退改流程做得更清楚，补上异常场景测试。
```

Boss GPT 应该：

1. 判断这是 C01；
2. 读取仓库当前 live `main` 的完整 40 位 SHA；
3. 生成一个新的 task id；
4. 创建一张 Formal Task Issue；
5. 不直接改代码，不手工 dispatch workflow。

### Issue 标题

```text
Cxx · V<number>-R<number>-Cxx-<number> · <scope>
```

例如：

```text
C01 · V73-R1-C01-01 · clarify hotel cancellation exception flow
```

### Issue 正文

至少：

```text
Task: Clarify the hotel cancellation exception flow and add focused regression coverage.

Canonical source: <CURRENT_MAIN_40_HEX_SHA>
```

关键规则：

- 标题 Cell 与 task id 中的 Cell 必须一致；
- `Canonical source` 必须是**创建 Issue 当时的 current main**；
- 不要复制旧 Issue 里的 SHA；
- 不要在旧 Issue 里换 task id 当新任务；
- 一个新任务用一个新的 Formal Issue。

---

## 5. 创建 Issue 以后会发生什么

Boss GPT 创建正确 Issue 后，到此就可以停止。

Runtime 自动完成：

```text
Formal Task Issue
→ resident consumer
→ Persistent Runtime
→ Generic Builder
→ GitHub Agentic Workflow
→ inspect / edit / test
→ exactly one Draft PR
→ 自动冻结真实 Draft PR head
→ 自动 C14
→ 自动 C13
→ sealed round decision
→ STOP
```

不需要：

- 老板登录 rt01；
- 老板运行 shell；
- 老板手工 dispatch GitHub Actions；
- 老板再次创建 C14 Issue；
- Eason 手工把 Builder PR 搬给 C14；
- Eason 手工把 C14 搬给 C13；
- 运行 `deliver_review_round.py` 作为正常流程。

---

## 6. 最终会停在哪里

即使：

```text
Builder = SUCCEEDED
C14 = PASS_SCOPED
C13 = PASS_SCOPED
round_decision = ACCEPT
```

系统仍然停在：

```text
Draft PR + review evidence
```

不会自动：

```text
merge
deploy HK-STAGING
deploy Production
run migration
```

这些仍然是单独的授权 / 发布行为。

---

## 7. 什么时候才手工用 C14 Review Issue

只有要审核一个**不是刚由 Runtime Builder 产出的现成 PR**时，例如历史 PR、人工写的 PR、Boss GPT 直接写出来的独立候选 PR、或需要单独重新审一个既有 candidate。

这时才创建：

```text
C14 · REVIEW · <description>
```

正文：

```text
Candidate PR: #<PR_NUMBER>
Candidate SHA: <EXACT_CURRENT_PR_HEAD_SHA>
```

然后 Runtime：

```text
C14
→ 如果准入
→ 自动 C13
```

仍然不要手工创建 C13。

---

## 8. Boss GPT 最推荐的固定提示词

余总以后可以直接对 Boss GPT 说：

```text
按 GO Persistent Runtime / 14 Cell 正式入口处理这个需求。

先读取 yuguangzhi3836-glitch/GO 当前 live main 和
docs/runtime/BOSS_GPT_14_CELL_GUIDE.md。

根据需求选择最合适的一个 C01-C12 Cell，
按 Formal Task Issue 格式创建一张新 Issue。

必须使用创建 Issue 当时的 current main 40 位 SHA。
不要直接改代码，不要自己创建 C13/C14 普通任务，
不要手工 dispatch Runtime。

Issue 创建完成后停止。
后续 Builder → Draft PR → C14 → C13 由 Persistent Runtime 自动推进。

需求：
<把老板的需求写这里>
```

这是正常开发任务的默认用法。

---

## 9. 如果老板不知道应该用哪个 Cell

Boss GPT 自己判断，不要让老板背 Cell 表。

| 老板说 | Boss GPT 应选择 |
| --- | --- |
| “酒店退款流程有问题” | C01 |
| “航班变更逻辑要补” | C02 |
| “铁路订单” | C03 |
| “租车” | C04 |
| “接送机 / Ride” | C05 |
| “景点票” | C06 |
| “用户偏好 / 画像” | C07 |
| “AI 怎么规划整段旅程” | C08 |
| “推荐可信度 / 判断规则” | C09 |
| “把不同订单串成统一行程” | C10 |
| “支付 / 补偿” | C11 |
| “平台、安全、模型网关、workbench” | C12 |

老板只需要讲业务需求。

---

## 10. 不要做的事

Boss GPT 不要：

- 为同一个需求同时给多个 Cell 发重复任务；
- 直接给 C13 发 Builder 任务；
- 正常 Builder 完成后再人工补一张 C14 Issue；
- 为 C14 通过后手工创建 C13；
- 把 C13/C14 PASS 理解成 merge 授权；
- 因为 PR 编号更新就认为它更 canonical；
- 用历史 README / 旧 Issue 的 SHA 代替 current main；
- 直接操作 rt01 作为普通派活手段。

---

## 11. 当前已验证能力

当前 normal path 已真实证明：

```text
C01-C12 Formal Issue
→ Builder
→ Draft PR
→ automatic C14
→ automatic C13
→ sealed round decision
```

并且：

- Builder / C14 / C13 的 paid dispatch 均可 exactly-once 收口；
- Runtime 使用 durable queue / lease / attempt fencing / outbox；
- crash window 使用 deterministic idempotency 修复，不靠人工搬运；
- C13/C14 的结果与执行成功分离；
- C13/C14 不拥有 merge / deploy authority。

---

# Boss 一句话版本

> **告诉 Boss GPT 需求即可。Boss GPT 选 C01-C12 并创建一张 Formal Task Issue；后面的 Builder、Draft PR、C14、C13 全由 Persistent Runtime 自动完成。C13/C14 不需要老板手工派，最终 merge / deploy 仍然单独决定。**
