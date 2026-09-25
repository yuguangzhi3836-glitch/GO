# GO C13/C14 Lite 最终改造设计 V1

> 状态：方向已由陈震曦与 Owner 于 2026-09-25 电话确认。本文用于工程实施，不是二次方案征求。

## 1. 设计目标

在不新增硬件、不新增云信任体系、不新增第三方服务的前提下，使用现有：

- Command Center ECS
- HK-STAGING ECS
- GitHub / GitHub Actions
- 现有 AI API
- 现有 Task / Evidence 签名能力

实现：

> **C13 与 C14 对同一冻结候选分别进行真实、互不污染的 Independent AI Review Execution，并通过冻结输入、机器测试、运行身份、哈希链和 CC/HK 双见证，使结果可验证、可追溯、不可静默篡改。**

---

## 2. “Independent”的正式定义

本项目中的独立仅表示：

```
implementation_execution != C13_execution
implementation_execution != C14_execution
C13_execution != C14_execution
```

以及：

```
C13 seal 前不得读取 C14 opinion/verdict
C14 seal 前不得读取 C13 opinion/verdict
```

不表示：

- Independent Authority
- Independent Organization
- Independent Cloud Account
- Independent GitHub Account
- Independent Physical Host
- Independent HSM
- Independent Signing Authority

今后文档中的 `independent` 默认解释为：

> **Independent AI Review Execution**

除非 Owner 另行明确提出更高层级要求。

---

## 3. 总体架构

```
                    Human Owner / Operator
                              |
                              v
                    Command Center (CC)
                  freeze + signed task
                              |
                 +------------+------------+
                 |                         |
                 v                         v
          GitHub C13 Run             GitHub C14 Run
          fresh AI context            fresh AI context
          read-only review            disposable sandbox
          no C14 opinion              PostgreSQL 18.4
                 |                    tests + AI review
                 |                         |
              C13 seal                  C14 seal
                 +------------+------------+
                              |
                       sealed bundles
                              |
                 +------------+------------+
                 |                         |
                 v                         v
              CC witness               HK witness
                 +------------+------------+
                              |
                         FINAL_ROOT
                              |
                      human deployment
                         decision only
```

不再需要第三台 C14 ECS。

---

## 4. 冻结候选

任何 C13/C14 运行前，CC 必须冻结并签发唯一 Acceptance Task。

至少绑定：

- repository
- candidate_commit_sha
- application_tree
- test_scope_sha256
- workflow identity / workflow SHA
- C13 prompt SHA256
- C14 prompt SHA256
- task_id
- nonce
- issued_at
- expires_at

继续使用现有 CC Task Ed25519 签名。

任何 candidate/tree/scope/prompt/workflow 不一致，都视为不同验收轮次。

---

## 5. C13 Lite

C13 是**开发侧独立 AI 审核执行**。

### 输入

只允许读取：

- Frozen Candidate
- Frozen Diff
- Frozen Contract
- 允许的机器 Evidence
- 固定 C13 Prompt

不得继承：

- 实现 AI conversation/context
- C14 conversation/context
- C14 opinion/verdict
- 历史非本轮 reviewer 结论

### 执行

- GitHub-hosted ephemeral runner
- 新的 workflow run
- 新的 AI execution/context
- read-only reviewer permission
- `openai/codex-action@v1` 或现有已验证的同等 API 调用
- structured output schema

### 输出

至少：

- task_id / nonce
- candidate_sha
- application_tree
- test_scope_sha256
- github_run_id / run_attempt / workflow identity
- ai_provider / ai_model / ai_execution_id
- prompt_sha256 / input_sha256 / opinion_sha256
- verdict: PASS_SCOPED / FAIL / BLOCKED
- opinion / findings
- issued_at
- C13_ROOT

C13 AI 本身不需要长期审核私钥。

---

## 6. C14 Lite

C14 是**运行侧独立 AI 验收执行**。

必须使用另一个 GitHub workflow run。

### 6.1 Machine Test Job

该 job 可以执行 Candidate Code，但不得拥有：

- AI API key
- SSH deployment key
- CC credential
- HK credential
- Production credential
- GitHub write credential（除必要 artifact upload 能力）

执行：

- checkout exact candidate SHA
- verify application tree
- disposable Docker sandbox
- PostgreSQL 18.4
- frozen test scope
- JUnit / stdout / manifest / runtime observations
- SHA256 digest

测试结束后 runner/container/PostgreSQL 全部销毁。

### 6.2 C14 AI Review Job

该 job：

- 有 C14 AI API credential
- **不得执行 Candidate Code**
- 只读 Source + Machine Evidence
- 使用全新 AI execution/context
- 在 seal 前不得读取 C13 opinion/verdict

输出与 C13 同类，但增加：

- junit_sha256
- stdout_sha256
- manifest_sha256
- machine_evidence_sha256
- `c13_opinion_seen_before_seal=false`

最终产生 C14_ROOT。

---

## 7. C13/C14 双盲规则

历史 pipeline 的 `C14 -> C13` 依赖关系不继续沿用。

正式 Lite 规则：

```
Frozen Candidate
   +--> C13 independent run --> seal
   |
   +--> C14 independent run --> seal
```

在 seal 之前：

- C13 看不到 C14 verdict/opinion/reasoning
- C14 看不到 C13 verdict/opinion/reasoning

可允许知道对方运行是否存在，或其 sealed bundle hash 已产生，但不能读取内容。

两边 seal 后，CC 才第一次汇总。

---

## 8. Bundle 与 Root

C13/C14 各自生成 canonical bundle。

Root 至少绑定：

- frozen candidate
- application tree
- test scope
- task/nonce
- GitHub run identity
- AI execution identity
- prompt/input/opinion hashes
- machine evidence hashes
- verdict
- timestamps

例如：

```
C13_ROOT = SHA256(canonical C13 bundle)
C14_ROOT = SHA256(canonical C14 bundle)
```

修改任意一个被绑定字段都会改变 Root。

---

## 9. GitHub Run Identity

### V1 必选

不新增外部服务。

CC 与 HK 分别使用 GitHub API 只读复核：

- run_id 是否真实存在
- repo / workflow / SHA 是否一致
- run status/conclusion
- artifact ID/digest
- run_attempt

再与 bundle 中记录逐项匹配。

### V1.1 可选增强

真实远程 PoC 通过后，可使用 GitHub OIDC：

- `id-token: write`
- custom `aud`
- repo/workflow/sha/run identity
- ephemeral public-key hash binding

OIDC 不作为 V1 的硬阻断项。

不引入 Sigstore/Fulcio/Rekor。

---

## 10. CC 改造

CC 不跑 AI、不跑 Docker、不跑 PostgreSQL。

增加：

### AcceptanceVerifier

负责：

- Task signature
- candidate/tree/scope
- GitHub run/artifact readback
- C13/C14 bundle/root
- AI execution separation
- blind-review fields
- hash/signature verification

### WitnessLedger

保存 first-seen、no-overwrite 的验收见证记录。

### FinalAcceptanceAggregator

生成：

```
FINAL_ROOT = SHA256(
  candidate_sha
  || application_tree
  || test_scope_sha256
  || C13_ROOT
  || C14_ROOT
)
```

并生成 CC witness。

### CC key

建议新建一把仅用于 witness 的本机 Ed25519 key。

不要复用 Task key，避免 key-purpose 混用。

不需要：

- HSM
- KMS
- WIF
- P-256 receipt
- Docker
- PostgreSQL
- ECS 扩容

---

## 11. HK 改造

保护现有 HK Agent / #245。

目标：

`#245_TOUCHED=NO`

新增轻量独立组件：

```
AcceptanceWitness
= read sealed bundle
+ GitHub API readback
+ recompute hashes
+ compare
+ sign witness record
+ persist first-seen record
```

建议：

- 独立路径
- 独立 oneshot service/script
- 独立 Ed25519 witness key
- 独立 ledger

HK 不再承担：

- C14 AI
- Docker sandbox
- PostgreSQL 18.4
- dedicated C14 daemon
- persistent C14 runner

资源开销近似可忽略，不需要扩容。

---

## 12. Final Acceptance

最终记录：

- candidate_sha
- application_tree
- test_scope_sha256
- C13_ROOT
- C13 verdict
- C14_ROOT
- C14 verdict
- FINAL_ROOT
- CC witness
- HK witness

状态机：

```
C13 PASS + C14 PASS
  -> ACCEPTANCE_ELIGIBLE

C13 FAIL or C14 FAIL
  -> NOT_ELIGIBLE

任一 BLOCKED
  -> ACCEPTANCE_BLOCKED

candidate/tree/scope mismatch
  -> INVALID_CHAIN

run/artifact/hash/signature mismatch
  -> INVALID_EVIDENCE

C13/C14 opinion conflict
  -> HUMAN_REVIEW_REQUIRED
```

即使 `ACCEPTANCE_ELIGIBLE`，也不自动部署。

`authorizes_any_action=false`

部署仍由真人通过 Command Center 明确授权。

---

## 13. 防篡改语义

本系统不宣称“文件永远不能被修改”。

它保证：

> **历史结果被修改后，无法继续通过 Root 重算、run/artifact readback 和 CC/HK 双见证，被冒充为原始验收结果。**

本地 PoC 已验证以下篡改全部失败：

- C13 opinion
- C14 verdict
- candidate SHA
- JUnit hash

这是 Lite 的安全目标：

> **tamper-evident + dual-witness**

而不是构造一个不存在的 external independent authority。

---

## 14. Before -> After

| 模块 | 当前 | Lite |
|---|---|---|
| C13 | 机器门较成熟，AI 版在 side branch 且从未正式产出 opinion | 独立 GitHub AI run，blind review，sealed C13 bundle |
| C14 | #241 设计要求专用 HK runtime host | 独立 GitHub run + disposable Docker/PG18.4 + blind AI review |
| AI 独立 | 语义存在，但 execution identity 记录不完整 | fresh execution/context + run/execution identity + 双盲 |
| Sandbox | 正准备落到 HK 专用运行环境 | GitHub-hosted ephemeral runner |
| HK | TEST_PR Agent + 业务容器 | 原 Agent 不动，仅增加 lightweight witness |
| CC | Task/bridge/ledger | 增 verifier + witness ledger + final aggregator |
| Receipt | HSM P-256 硬门槛 | FINAL_ROOT + CC/HK Ed25519 witness |
| HSM/KMS/WIF | 设计硬依赖 | 从 Lite 主链移除 |
| 新 ECS | 拟新增 | 不需要 |
| 成本 | 常驻基础设施 + AI | GitHub/AI 按需运行 |

---

## 15. 实施责任

### 陈震曦 + WorkBuddy：GitHub

- 新建/收敛 C13 Lite workflow
- 新建/收敛 C14 Lite workflow
- 复用旧 prompt/output-schema/codex-action
- 参数化冻结 candidate/tree/scope
- bundle/schema/root
- 双盲约束
- GitHub run/artifact readback metadata
- CI / PoC

### 陈震曦 + WorkBuddy：CC

- AcceptanceVerifier
- WitnessLedger
- FinalAcceptanceAggregator
- CC witness key
- dry-run / readback / integration

### 陈震曦 + WorkBuddy：HK

- lightweight AcceptanceWitness
- HK witness key
- local ledger
- 保证 #245 不变

### Owner

- API 额度/账号级资源
- 必要 repo Settings 权限
- 最终 merge / deployment decision

### Owner GPT

- 阅读本 PR
- 向 Owner 做白话解释

不负责重新设计或施工。

---

## 16. 实施前唯一需要做的工程验证

这不是重新选方案，只是施工前技术验证：

1. AI API 当前可用额度
2. 新 C13/C14 workflow 能在 main/正式可派发路径运行
3. 一次真实双 run：
   - C13 run_id != C14 run_id
   - 两边 fresh AI execution
   - 两边 blind before seal
4. GitHub API run/artifact readback
5. 如果要启用 OIDC，再做一次 `id-token: write` PoC

---

## 17. 最终一句话

> **使用现有两台 ECS + GitHub 按需临时 Runner + 两个互不污染的 AI execution/context，对同一冻结候选分别形成 C13/C14 独立意见，并通过固定输入、机器证据、GitHub 运行事实、哈希链和 CC/HK 双见证保证结果可验证、可追溯、不可静默篡改；不新增常驻硬件，也不再把“独立”扩展成独立 HSM、独立 ECS 或独立外部权威。**
