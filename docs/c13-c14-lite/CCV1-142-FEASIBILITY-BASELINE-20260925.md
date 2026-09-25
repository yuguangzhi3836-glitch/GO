# CCV1-142 · C13/C14 Lite 可实现性现场基线

- 日期：2026-09-25
- 来源：WorkBuddy / Eason-13490 只读摸底 + 本地临时 PoC
- GitHub：只读
- Command Center：只读
- HK-STAGING：只读
- 现场写操作：0
- 正式 C13/C14 Run：0
- 部署/安装/重启/IAM/Secret 变更：0

> 本文把 CCV1-142 摸底中与后续 C13/C14 Lite 改造直接相关的现场事实固化到 GitHub。它不是 C13/C14 PASS，也不是部署授权。

## 1. 工程结论

`RESULT = LITE_FEASIBLE_MEDIUM_DELTA`

在只使用现有 **CC ECS + HK-STAGING ECS + GitHub/GitHub Actions + 现有 AI API + 现有机器签名能力** 的前提下，C13/C14 的 **Independent AI Review Execution** 可以实现。

不需要：

- 第三台 C14 ECS
- Google HSM / KMS
- WIF
- 新第三方服务
- 常驻 C14 Docker/PostgreSQL 主机

预计改动量：

| 区域 | 改动量 | 结论 |
|---|---:|---|
| GitHub | MEDIUM | 两条正式 C13/C14 workflow + bundle/run identity + 参数化冻结候选 |
| CC | MEDIUM | verifier + witness ledger + final aggregator |
| HK | SMALL | 独立 lightweight witness，#245 不动 |
| 新硬件 | NO | 不需要 |
| HSM/KMS/WIF | NO | 不作为 Lite 硬门槛 |
| 新外部服务 | NO | 仅 GitHub + 现有 AI API |

---

## 2. 老版 C13/C14 真实情况

### 2.1 确实存在过 AI 版 C13/C14

历史仓库中至少存在两代 AI pipeline：

- `v70-r3-ai-cell-pipeline.yml`
- `c01-formal-run.yml`
- `c01-gates-from-candidate.yml`
- `c01-formal-continuation.yml`

核心形态已经具备：

- GitHub-hosted `ubuntu-24.04` runner
- `openai/codex-action@v1`
- `OPENAI_API_KEY`
- C13/C14 独立 job
- read-only permission profile
- 独立 prompt file
- JSON output-schema
- GitHub Actions artifact

历史 prompt 已经明确表达：

- C14 是独立 read-only engineering/boundary reviewer
- C13 是独立 acceptance reviewer
- C13 不是实现者，也不是 C14

### 2.2 但 AI 版从未真正形成过一条正式 AI opinion

历史 Actions 事实：

- AI 版 C13/C14 review job 为 skipped / cancelled，未产出正式 opinion。
- 已抓到的一次真实失败日志为：
  `You have no credits remaining.`
- 这证明 OpenAI API 配额曾直接阻断 AI pipeline。

同时仓库中存在成功先例：

- `openai-api-smoke.yml` 成功调用 Responses API。
- `c01-codex-action-smoke.yml` 成功运行 `openai/codex-action@v1` 并产生文件改动。

因此：

> AI API 与 Codex Action 的基础链路已经被仓库历史证明可用；已证实的主要外部运行风险是 API 额度/配额，而不是 C13/C14 理论上不能在 GitHub 跑。

### 2.3 大量“C13/C14 PASS”其实是机器门，不是 AI opinion

现场发现多条历史 workflow 属于：

- PostgreSQL 18.4 + pytest
- SHA256SUMS
- candidate/application tree binding
- JUnit / artifact digest
- 硬编码 `C13_RESULT.json`

特别是历史 `c01-c13-independent.yml` 中存在直接在 YAML 写出结果文件的情况。

因此必须继续严格区分：

```
Machine Test != Independent AI Opinion
```

当前 #241 中的：

- `PENDING_INDEPENDENT_REVIEW`
- `EVIDENCE_ONLY_PENDING_INDEPENDENT_REVIEW`

也说明机器层已经较完整，但 AI opinion 层尚未真正接通。

---

## 3. 当前 #241 可复用能力

摸底冻结基线：

- PR：#241
- 当时 head：`501c01b3a829e04452de43b4835fe7c649bc2f5c`
- Draft / open
- 66 commits
- 37 changed files
- 101 个 Linux 单元/合同测试离线复跑通过

### KEEP

可以直接保留或复用：

- canonical JSON
- nonce / expiry
- `candidate_sha`
- `application_tree`
- `test_scope_sha256`
- CC Task Ed25519 signer/verifier
- Task exact readback
- JUnit identity checking
- stdout / manifest SHA-256
- `AIReviewGroup`
- `principal_id` / `review_execution_id`
- C13/C14 opinion schema 的核心字段
- Git evidence publication/readback 语义
- disposable PostgreSQL 18.4 sandbox
- artifact + SHA256SUMS discipline
- `authorizes_any_action=false`

特别重要：

> #241 已经明确把 `principal_id` 定义为真实独立 AI execution/context，而不是 GitHub 账号或签名主体。这与 Lite 目标完全一致。

### MODIFY

需要轻量收敛：

- 将钉死 PR #240 的 candidate/tree/scope/run/artifact 常量参数化为“本轮冻结候选”。
- C13/C14 opinion 增加 GitHub run identity、AI execution id、prompt/input/opinion hash、JUnit/stdout/manifest hash。
- 历史 AI workflow 从 side branch 收敛为正式 workflow。
- C13 与 C14 改成两个独立 workflow run。
- C13/C14 必须在各自 seal 前互相 blind。

### DROP_FROM_HARD_PATH

不再作为 Lite 必选条件：

- Google HSM P-256 receipt
- Google Cloud KMS
- WIF
- HSM SPKI fingerprint gate
- 独立 C14 ECS
- dedicated HK C14 host
- second Docker daemon
- C14 systemd daemon
- 常驻 PostgreSQL
- persistent host claims 作为硬门槛
- orphan-container reconciliation 作为硬门槛
- Registration Authority / Independent Authority

---

## 4. GitHub-hosted C14 沙箱已经被证明可运行

#241 的 GitHub-hosted runner 已真实执行：

- `runs-on: ubuntu-24.04`
- Docker build / run
- PostgreSQL 18.4
- frozen candidate
- frozen test inventory
- JUnit / stdout / manifest artifact

关键现场结论：

| 问题 | 结果 |
|---|---|
| GitHub-hosted runner 能否跑 | YES |
| 是否依赖 HK | NO |
| 是否依赖 CC | NO |
| 是否依赖 Google KMS | NO |
| 是否占用现有两台 ECS 资源 | NO |

因此：

> “C14 需要真实 Docker/PostgreSQL 验收”并不能推出“必须新购独立 ECS”。

---

## 5. Independent AI Review Execution 可实现性

WorkBuddy 摸底确认 GitHub Actions 天然可提供：

- 独立 VM / process
- 独立 checkout
- 独立 prompt
- 独立 Codex invocation
- 独立 run/job identity
- read-only reviewer permission
- structured output schema

历史日志中还能看到 Codex session id，只是旧设计没有把它正式写入 Evidence。

最低独立条件可以被机器化检查：

```
implementation_execution_id != c13_execution_id
implementation_execution_id != c14_execution_id
c13_execution_id != c14_execution_id
c13_github_run_id != c14_github_run_id
c13_nonce != c14_nonce
```

最终设计进一步要求：

```
C13 seal 前不得读取 C14 opinion/verdict
C14 seal 前不得读取 C13 opinion/verdict
```

即两个 AI 对同一冻结候选分别形成自己的意见，再由 CC 汇总。

---

## 6. 本地签验 PoC 已跑通

WorkBuddy 在本机临时目录用 synthetic data 和 ephemeral Ed25519 key 完成：

- C13 bundle
- C14 bundle
- C13_ROOT
- C14_ROOT
- CC witness
- HK witness
- FINAL_ROOT
- 独立性正向/负向检查
- OIDC JWT 离线验签逻辑

结果：

- C13 original verify：PASS
- C14 original verify：PASS
- CC witness：PASS
- HK witness：PASS
- final acceptance clean：ACCEPTED
- `authorizes_any_action=false`

四个 tamper case 全部被拒：

1. 修改 C13 opinion
2. 修改 C14 verdict
3. 修改 candidate SHA
4. 修改 JUnit hash

因此已经证明：

> Lite 链可以实现“历史内容一旦改变，就无法继续冒充原始验收结果”的 tamper-evident 语义。

这里的安全目标不是“文件永远无法被修改”，而是：

> **任何修改都必须被验签/重算/双见证检测出来，无法静默替换历史结果。**

---

## 7. GitHub run identity / OIDC 摸底

现场已验证：

- `https://token.actions.githubusercontent.com` 可访问
- GitHub OIDC discovery/JWKS 可访问
- CC/HK 均可访问 GitHub OIDC 与 GitHub API
- 标准 claim 包含 repo、sha、run_id、run_attempt、workflow_sha、check_run_id 等
- 本地 synthetic RS256 OIDC 验证 PoC 通过，错误 run_id / kid / aud / expiry / key 全部被拒

但当前仓库还没有真实 `id-token: write` 运行先例。

因此最终 Lite V1 不把 OIDC 设成阻断上线的前置条件：

### Lite V1

使用：

- GitHub run_id / workflow SHA / candidate SHA / artifact digest
- CC 对 GitHub API 的只读独立复核
- HK 对 GitHub API 的只读独立复核
- ephemeral bundle signature
- CC/HK dual witness

### Optional V1.1

在一次真实 Actions PoC 通过后，可以增加 GitHub OIDC 绑定作为增强。

OIDC 不是 Lite 独立性的定义，也不是 V1 的新外部依赖。

---

## 8. Command Center 现场事实

只读实测：

- host：`iZj6c7k6k01biwlbnwutu5Z`
- CPU：2 cores
- RAM：7393 MB total，6369 MB available
- disk：40G，约 43% used
- Python：3.10.12
- cryptography：3.4.8
- git：2.34.1
- 无 gcloud
- 无 Google SDK
- 无 GOOGLE_APPLICATION_CREDENTIALS
- 无 KMS credential

现有能力：

- `task-manifest-signing.pem`：Ed25519 private key
- task public key
- GitHub tasks writer
- GitHub evidence reader
- request/source reader
- Command Center ledger/storage
- canonical Task/bridge 机制

当前 CC 没有正式 C13/C14 Lite verifier/witness。

### Lite 需要新增

- `AcceptanceVerifier` — MEDIUM
- `WitnessLedger` — MEDIUM
- `FinalAcceptanceAggregator` — SMALL

不需要：

- Docker
- PostgreSQL
- Google KMS
- HSM
- WIF
- 扩容

最终实现建议为 CC Witness 使用**独立 Ed25519 witness key**，不要复用 Task key，避免 key purpose 混用。

---

## 9. HK-STAGING 现场事实

只读实测：

- host：`iZj6ccs8t04f1p4d8pe69zZ`
- CPU：2 cores
- RAM：3495 MB total
- available：约 1.6 GB
- disk：40G，约 32% used
- Python：3.10.12
- cryptography：3.4.8
- git：2.34.1

#245 已安装 baseline 逐字节保持：

- `test_pr.py` SHA256 = `86c3cd055e6a36691ce91a290ca0523eb09f0747f424aa730915b35d54bd2199`
- `transport.py` SHA256 = `e4e2244cc652130f1c94c8632ab9f42a70bd08435278fc2c30e5d73d07852194`
- `core.py` SHA256 = `44b04dd83ca5f192f031bb5541deb5c571241e0c076d086e79a8651909a39f7c`

`#245_TOUCHED=NO`

现有能力：

- CC Task verify public key
- HK Evidence Ed25519 signing key
- Git tasks-read / evidence-write / source-reader credentials
- 现有 HK Agent / ledger

### Lite 目标

HK **不再运行 C14 Docker/PostgreSQL/AI**。

只增加：

```
AcceptanceWitness
= read bundle
+ verify GitHub run/artifact
+ recompute hashes
+ compare
+ sign witness record
+ persist first-seen record
```

预计：

- CPU < 1 s / run
- memory < 50 MB
- disk < 1 MB / run
- 不需要扩容
- 不需要碰 #245

最终实现建议为 HK Witness 生成**独立 Ed25519 witness key**，不要与现有 Evidence signing key混用。

---

## 10. 当前真实风险 / 前置事项

### R1 — AI API 配额

这是已经发生过的真实阻断。

实施前必须保证 C13/C14 使用的现有 AI API 有可用额度，并有基本额度告警。

### R2 — 正式 C13/C14 workflow 需要落在可派发路径

历史 AI workflow 主要存在于 side branch，无法直接作为当前正式入口。

需要由本轮 Lite 改造创建正式 C13/C14 workflow。

### R3 — GitHub run identity

Lite V1 采用 GitHub API readback + artifact digest + dual witness。

OIDC 为增强项，待一次真实远程 PoC 后再决定是否启用。

### R4 — 双 AI 不得互相锚定

历史 pipeline 曾使用 C14 → C13 的依赖顺序。

最终 Lite 不继续这一点。

必须改为：

```
Frozen Candidate
   ├── C13 independent run → seal
   └── C14 independent run → seal

seal 之前双方均不得看到另一方 opinion/verdict
seal 之后由 CC 汇总
```

---

## 11. 最终事实结论

```
LITE_FEASIBLE_MEDIUM_DELTA

GitHub delta          = MEDIUM
CC delta              = MEDIUM
HK delta              = SMALL
New hardware required = NO
HSM required          = NO
KMS/WIF required      = NO
External new service  = NO
#245_TOUCHED target    = NO
```

这不是一个从零开始的新系统。

更准确的工程描述是：

> **复用旧版 C13/C14 的 AI reviewer 形态 + 复用 #241 已成熟的冻结候选/机器验收/完整性能力 + 复用现有 CC/HK 的签名和服务器，删除过度扩张的独立基础设施要求，收敛成按需、双 AI、双见证的 Lite 验收链。**
