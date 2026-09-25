# CCV1-142 · C13/C14 Lite 双独立 AI 验收方案：可实现性摸底 + 本地最小 PoC

- 日期：2026-09-25（CST）
- 执行人：WorkBuddy（麻花）／Eason-13490
- 授权边界：`GITHUB_READ_ONLY=YES` `CC_READ_ONLY=YES` `HK_READ_ONLY=YES` `LOCAL_ANALYSIS=YES` `LOCAL_TEMP_POC=YES`
  其余全 NO：`COMMIT/PUSH/PR/MERGE/INSTALL/DEPLOY/RESTART/CONFIG_CHANGE/IAM_CHANGE/SECRET_CHANGE/TASK_ISSUE/C13_FORMAL_RUN/C14_FORMAL_RUN/PRODUCTION = NO`
- 写操作计数：**0**。CC/HK 仅 `ssh "cmd"` 只读采集 + 两条只读 `curl` 探活；GitHub 仅 REST GET；PoC 全在本机临时目录。
- 主报告：本文件。PoC 证据：`.workbuddy/tmp/ccv1-142-lite/`（`evidence/`、`raw/`、`poc/`）。
- ⚠ 编号说明：今日早间已有一份 `CCV1-142-C14-INSTALLATION-LAYER-2026-09-25.md`（C14 安装层工程，纯本地）。
  本轮按指令使用同号不同名的 `CCV1-142-C13-C14-LITE-FEASIBILITY-2026-09-25.md`，两份互不覆盖；引用时请带全名。

---

## 1. Executive conclusion

**`RESULT = LITE_FEASIBLE_MEDIUM_DELTA`**

在「只用现有 CC ECS + 现有 HK-STAGING ECS + GitHub/GitHub Actions + 现有 AI API + 现有机器签名能力」的前提下，C13/C14 的 **Independent AI Review Execution 是可以实现的**，而且本仓库里**已经存在一套形状完整、只是从未跑通的旧版 C13/C14 AI 实现**，可以大量复用。

一句话结论：**技术上可行，不需要第三台机器、不需要 HSM/KMS/WIF、不需要任何新外部服务；工作量集中在 GitHub 侧的两个新 workflow + CC 侧三个新组件 + 一次 receipt 签名后端替换（HSM P-256 → 现有 Ed25519）。**

三条关键事实（与任务书假设的差异，必须先说）：

| # | 任务书假设 | 现场实测 |
|---|---|---|
| F1 | 「老版 C13/C14 以前已经正常存在于 GitHub」 | **代码存在、运行从未成功。** AI 版 C13/C14 review job 在 Actions 历史里 **100% 是 `skipped` 或 `cancelled`**，从未产出一条 AI opinion。唯一一次成功的是 AI 实现步（`C01 AI implementation`，run `34967469151`），随后在 deterministic promotion 处断裂。 |
| F2 | 绿色 CI ≈ 有 C13/C14 | **本仓库的「C13 independent acceptance」大部分是机器门/盖章件**：`c01-c13-independent.yml` 直接把 `C13_RESULT.json` **硬编码**在 workflow 里。机器测试 ≠ AI opinion，任务书的这条区分在现场得到证实。 |
| F3 | 老版 C13/C14 现在还能运行 | **不能直接跑。** 118 个 workflow 里只有 **26 个在 `main`**；全部 C13/C14（含 AI 版）只活在 `ops/*`、`codex/*`、`acceptance/*` 快照分支上 ⇒ `workflow_dispatch` 需要 workflow 存在于默认分支，**旧版当前不可派发**。 |

本轮"独立"的定义严格按任务书执行：只做 `Independent AI Review Execution`，**不**向外扩成组织级独立基础设施。

---

## 2. Current GitHub C13/C14 facts（老版 C13/C14 的完整定位）

### 2.1 摸底方法

- Actions workflow 索引：`GET /repos/.../actions/workflows?per_page=100`（2 页，**118** 个）。
- 逐 workflow 查运行：`/actions/workflows/<file>/runs`，取 `head_branch` 反查 workflow 实际所在 ref（关键：workflow 文件不在 `main` 上，`contents?ref=main` 全部 404）。
- 逐 run 查 job：`/actions/runs/<id>/jobs`；失败 job 下真日志：`/actions/jobs/<id>/logs`。
- 文件取件：`contents?ref=<branch>`（base64）。取下的 18 个 workflow 全文存 `raw/wf/`。

### 2.2 存在两代「老版 C13/C14」

**A 代 · AI 版（`v70-r3-ai-cell-pipeline.yml`，2026-09-14/15，分支 `ops/codex-coding-runner-pilot-20260914`）**

```
agent (AI implementation)  →  promote (deterministic)  →  c14 (AI, read-only)  →  c13 (AI, read-only)
```

- 入口：`v70-r3-code-modifying-ai-runner.yml`（可复用 workflow 调用者，11 个 cell 各一个 job，`secrets: inherit`）。
- AI 调用方式：`uses: openai/codex-action@v1` + `openai-api-key: ${{ secrets.OPENAI_API_KEY }}`。
- C14 与 C13 的 **prompt 原文**（节选，全文见 `raw/wf/v70-r3-ai-cell-pipeline.yml` L355-L431）：
  - C14：*"You are C14, an independent read-only engineering/authority/boundary gate. … **Historical PASS does not transfer to this SHA.**"*
  - C13：*"You are C13, an independent acceptance reviewer. **You did not implement this change and you are not C14.**"*
- 隔离手段：C13/C14 各用 `permission-profile: ':read-only'` + `safety-strategy: drop-sudo`；**各自一个 job、各自一个 `ubuntu-24.04` runner**；C13 `needs: [promote, c14]` ⇒ 结构上 C14 verdict 先于 C13 形成。
- 输出强约束：`output-schema`（JSON Schema）限定
  `C14 = {status∈[PASS_SCOPED,BLOCKED,FAIL], candidate_sha, summary, blocking_reasons}`
  `C13 = {status∈[PASS_SCOPED,BLOCKED,FAIL], candidate_sha, summary, remaining_risks}`。
- 模型：实现 `gpt-5.6-sol`；C14/C13 均 `gpt-6-astra`、`effort: high`。
- **实际运行结果**：5 个 run，**全部 `failure`**，45 个 job 里 12 个 cell 的 `Run sandboxed code-modifying Codex` 全红，`promote/c14/c13` 全 `skipped`。
- **失败真因（真日志，job `104321212179`）**：
  ```
  ERROR: stream disconnected before completion: You have no credits remaining.
  Add credits to continue using the API at https://platform.openai.com/settings/organization/billing/.
  → Error: /usr/bin/sudo exited with code 1  (codex-action 收尾)
  ```
  即 **OpenAI API 余额耗尽**，不是设计缺陷、不是权限问题。
- 同一 run 日志里可读到 Codex 自带 **session id**：`session id: 01a0a454-d93a-71d3-96ea-4f9a2d641942` ⇒ **底层 AI runtime 已有每次调用的 execution 标识**，只是当时没被写进 Evidence。

**B 代 · AI 版（`c01-formal-run.yml` / `c01-gates-from-candidate.yml` / `c01-formal-continuation.yml`，2026-09-15..17，分支 `ops/c01-formal-20260915`）**

- 同构：`preflight → agent → promote → c14 → c13`，`c14`/`c13` 均 `openai/codex-action@v1` + `:read-only` + `output-schema`，模型统一 `gpt-5.6-sol`。
- 运行结果：`c01-formal-run` 1 次 failure（`C01 AI implementation` **success**，断在 `deterministic promotion → Verify and apply exact patch`）；`c01-formal-continuation` 1 次 failure（断在 publish Draft PR）；`c01-gates-from-candidate` 1 次 **cancelled**（`C01 C14 read-only gate` 被取消）。
- ⇒ **C14/C13 的 AI job 在 B 代同样一次没跑成**。

**C 代 · 非 AI（机器门 / 盖章）** —— 这是任务书要重点区分的部分：

| workflow | 所在分支 | 性质 | 运行历史 |
|---|---|---|---|
| `c01-c13-independent.yml` | `ops/c01-formal-20260915` | **硬编码盖章**：`C13_RESULT.json` 与 `C14_BINDING.txt` 直接写死在 YAML 里 | 1 run 成功（2026-09-16） |
| `c01-c14-deterministic.yml` | 同上 | **机器测试**：`postgres:18.4` service container + `pytest` 竞态用例 + SHA256SUMS 固定 | 3 runs 成功 |
| `c01-02-c13-independent.yml` | 同上 | **半机器半绑定**：真跑 7 个 targeted 用例，再经 GitHub API 校验 C14 run/artifact digest，然后冻结 `C13_RESULT.json` | 1 run 成功（2026-09-17） |
| `c01-02-c14-deterministic.yml` | 同上 | 机器测试 + artifact 绑定 | 1 run 成功 |
| `c13-independent-control.yml` | `codex/c13-independent-control-20260924` | **4 个 job**，各钉一个 candidate SHA，跑 `postgres:18.4` + `pytest`，产出 `C13_SOURCE_BINDING.json`，字段含 `test_scope_sha256`，状态写 **`PENDING_INDEPENDENT_REVIEW`** | 5 runs（3 成功 2 失败） |
| `c13-independent-wave1/2.yml` | `codex/c13-independent-wave1/2-20260924` | 同上模式 | 4 runs |
| `c13-flight-development.yml` | `codex/c13-first-hk-c14-architecture-20260924`（= #241 head 分支） | 机器测试 + `C13_SOURCE_BINDING.json`，状态 **`EVIDENCE_ONLY_PENDING_INDEPENDENT_REVIEW`** | 37 runs（含 2026-09-25） |
| `c13-pr76-independent-acceptance.yml` | `acceptance/c13-pr76-37d9a420-20260914` | 机器：独立重算 source fingerprint + app tree，无 AI | 2 runs 全 failure |
| `flight-c14-predepth-postgres.yml` | `codex/flight-c14-predepth-20260921` | 机器：`postgres:18.4` service + 迁移血缘 | 12 runs |

🔴 **这是本轮最重要的定性发现**：`C13: PENDING_INDEPENDENT_REVIEW` / `EVIDENCE_ONLY_PENDING_INDEPENDENT_REVIEW` 这两个字面值，就是 AUTHOR 自己留的 **"AI opinion 还没接上"的占位符**。机器层早已完备，AI 层从未落地。

**D · AI 能力证明（小而关键）**

| workflow | 分支 | 证明什么 | 结果 |
|---|---|---|---|
| `openai-api-smoke.yml` | `ops/openai-api-smoke-20260915` | 裸 `curl https://api.openai.com/v1/responses`，`model: gpt-5.6-sol`，`secrets.OPENAI_API_KEY` | 1 run **success**（2026-09-15T11:05Z） |
| `c01-codex-action-smoke.yml` | `ops/c01-runner-repair-20260915` | `openai/codex-action@v1` **真的改了文件**（`C01_RUNNER_PROBE=PASS` + `DONE` 双断言） | 1 run **success**（2026-09-15T11:09Z） |

⇒ **AI API 与 codex-action 在这个 repo 里都有成功先例**，且发生在 AI 版 C13/C14 失败（09:10Z）之后 2 小时 ⇒ 当时余额已恢复。**余额/配额是唯一被证实的硬外部依赖。**

### 2.3 C13（老版）逐项回答

| 问题 | 答案 |
|---|---|
| 1 真正入口 | 两代：`v70-r3-code-modifying-ai-runner.yml` → 复用 `v70-r3-ai-cell-pipeline.yml`；`c01-formal-run.yml` / `c01-gates-from-candidate.yml` |
| 2 workflow 文件 | 见上；均在非 main 分支 |
| 3 哪个 AI/模型产生 opinion | `openai/codex-action@v1`，`gpt-6-astra`（A 代）/ `gpt-5.6-sol`（B 代），`effort: high` |
| 4 AI 调用方式 | GitHub Action（`codex-action@v1`），或裸 REST `api.openai.com/v1/responses` |
| 5 是否已有 API integration | **有且已验证**（`openai-api-smoke.yml` success） |
| 6 context/execution 怎么创建 | 每个 AI review 是 **独立 job + 独立 runner + 进程级一次性 prompt file 输入/输出**，无跨 job 会话延续 |
| 7 是否已有独立 execution ID | **没有落到产物里**；但 runtime 有 session id（日志可见），且 `GITHUB_RUN_ID` / `github.job` / `run_attempt` 都在用 |
| 8 输入 | checkout 固定 `candidate_sha` 的仓库 + `EVIDENCE.json` + C14 result（C13 才有） |
| 9 输出 | `c13-output/C13_RESULT.json` + `.sha256`，`upload-artifact` 保留 90 天 |
| 10 Evidence 保存 | GitHub Actions artifact（`actions/upload-artifact@v4`），无外部存储 |
| 11 现在是否仍能运行 | ❌ 不可派发（不在 main）；且 AI job 历史成功率 0 |
| 12 可直接复用 | **prompt 文本、output-schema、`:read-only` profile、job 切分、artifact 约定、codex-action 调用形态**（全部 1:1 可搬） |

### 2.4 C14（老版）逐项回答

| 问题 | 答案 |
|---|---|
| 1 入口 | 同上，`c14` job（AI 版）；机器版 = `c01-02-c14-deterministic.yml` / `flight-c14-predepth-postgres.yml` / #241 的 `sandbox-development-integration` |
| 2 workflow | 同上 |
| 3 Runner | 全部 `runs-on: ubuntu-24.04`（GitHub-hosted），无 self-hosted |
| 4 Docker | **两个方向都有**：service container（`services: postgres:18.4`）与真 `docker build` + `docker run`（#241 `sandbox_smoke.py`，`--docker-socket /var/run/docker.sock`） |
| 5 PostgreSQL | `postgres:18.4`（service container）与 `postgres:18.4-bookworm`（自建镜像，见 `sandbox/Dockerfile`） |
| 6 test scope | 显式命令列表，`test_scope_sha256 = sha256(canonical(scope_list))` |
| 7 AI opinion | 有 schema、有 prompt、**从未产出** |
| 8 API 调用 | 同 C13 |
| 9 Evidence | JUnit XML + stdout.log + `BINDING.txt` / `EVIDENCE.json` + SHA256SUMS + artifact |
| 10 现在是否仍能运行 | ❌ 同 C13 |
| 11 与 C13 是否已存在上下文隔离 | **结构上已存在**（不同 job / 不同 runner / 不同 prompt file / `:read-only` / C13 依赖 C14），**但没有可引用的 execution id 记录**，也没有"C14 未看 C13"的显式证明字段 |
| 12 可直接复用 | 沙箱构建（Dockerfile + `sandbox_payload.py`）、`postgres:18.4` 约定、artifact/SHA256SUMS 纪律、JUnit 计数断言 |

### 2.5 Machine Test 与 AI Review Opinion 的分界（现场证据）

- 机器测试：`pytest` 退出码 / JUnit 计数 / artifact digest。（B 代、C 代全部）
- AI opinion：`codex-action` 的 `output-schema` 产物 `C13_RESULT.json` / `C14_RESULT.json`。（A、B 代，**零产出**）
- 佐证：`c01-c13-independent.yml` 里 `C13_RESULT.json` 是 `cat > … <<'EOF'` 写死的字符串，`c14_run=35040162294` 也是常量 ⇒ **它根本不可能是 AI opinion**。

---

## 3. Current PR241 reusable matrix

### 3.1 冻结基线（本轮实测，非聊天摘要）

```
PR            = #241  "Draft: C13 首验 → 香港隔离 C14 复测的架构规则"
state         = open / draft=true / merged=false
head          = 501c01b3a829e04452de43b4835fe7c649bc2f5c
base          = main @ aa2ec62b68b49679c6d54217c7cb75f63a9c3ef0（未动）
commits=66  changed_files=37  additions=5435  deletions=0  updated_at=2026-09-25T05:18:21Z
subtree       = control-plane/c13-c14-v2/  34 blobs（逐字节经 contents API 取回，大小与 tree 一致）
```

⚠ head 仍在漂移（今日 3c2f93d1 → 8322a5c8 → 8e1ad011 → 501c01b3）。**任何以 #241 为来源的实施必须先冻结具体 commit SHA。**

### 3.2 离线复跑（本轮实测）

```
wsl Ubuntu-24.04 / python 3.12.3 / cryptography 41.0.7
python3 -m unittest discover -s . -p 'test_*.py'
→ Ran 101 tests in 2.512s
→ OK        UNITTEST_EXIT=0
```
与 PR 正文自述 "local 101/101" 一致。**该套件在 Linux 上全绿，在 Windows 上会因 `os.O_DIRECTORY` 大面积报错 ⇒ 判据只能在 Linux 取。**

### 3.3 GitHub-hosted Docker/PostgreSQL 沙箱核验（问题清单逐条回答）

| 问题 | 实测答案 |
|---|---|
| 是否真的能在 GitHub-hosted runner 运行 | **能**。`c13-c14-v2-contract.yml` 的 `sandbox-development-integration` job 在 `ubuntu-24.04` 上 `docker build` + `docker run`（用 runner 的 `/var/run/docker.sock`），并成功上传 artifact |
| 实际测试数量 | 契约/单元 **101**；沙箱内**冻结套件**（`c14_frozen_test_inventory.json`）另有清单 |
| 时间 | 该 job `timeout-minutes: 30`；`source-only` job `5` 分钟；实测最后成功 run `36097672437` @ 2026-09-25T05:13Z |
| 资源 | 标准 GitHub-hosted runner（4 vCPU / 16 GB 级），**不占 CC/HK 任何资源** |
| 是否依赖 HK 主机 | ❌ 不依赖 |
| 是否依赖 CC | ❌ 不依赖（该 job 只 checkout repo） |
| 是否依赖 Google KMS | ❌ 不依赖（该 job 只 `pip install cryptography`） |

证据：artifact `c14-sandbox-development-only`（9 份，最近 2026-09-25T05:17:09Z，未过期）。

### 3.4 #241 能力逐项核验

| 能力 | #241 是否已有 | 位置 | 结论 |
|---|---|---|---|
| `candidate_sha` binding | ✅ | `acceptance_gate._source()` `HEX40` 强校验 + `host.authorize_candidate()` | KEEP |
| `application_tree` binding | ✅ | 同上 | KEEP |
| `test_scope_sha256` | ✅ | `acceptance_gate.c13_admission()` `HEX64`；`c14_isolated_runner.SCOPE_COMMANDS` + `assert digest(...)==SCOPE` | MODIFY（现值钉死在 PR#240 的 `e13e181e…`） |
| canonical JSON | ✅ | `house_bridge.canonical`（`sort_keys`+紧凑分隔符），全文一致使用 | KEEP |
| nonce | ✅ | `host.fresh_nonce()` → `secrets.token_urlsafe(24)`；bus 信封正则 `[A-Za-z0-9_-]{1,128}` | KEEP |
| expiry | ✅ | `HongKongAcceptanceHost.task_is_fresh()`：`issued_at ≤ now ≤ expires_at` | KEEP |
| CC Task Ed25519 签名 | ✅ | 注入式 `task_signer` / `task_verifier`；CC 现网 `task-manifest-signing.pem` 实测为 **PKCS8 Ed25519** | KEEP（**直接复用现网同一把**） |
| Task exact readback | ✅ | `publish_house_task` → `read_house_task`（`git_acceptance_bus`） | KEEP（但需 git ≥2.38，见 §7） |
| JUnit identity 校验 | ✅ | `house_bridge.frozen_junit_counts`；`c13_attestation.inspect_artifact` 逐 payload digest + JUnit 61/61 + PG 恢复 10/10 | MODIFY（数值钉死 PR#240 产物） |
| stdout / manifest hash | ✅ | `AGENT`/`C13_SOURCE_BINDING.json` 里 `files{}` 逐文件 sha256；`raw_test_log_sha256` | KEEP |
| `AIReviewGroup` | ✅ | `ai_acceptance_host.AIReviewGroup{actor_id, principal_id, role, side, kind="AI"}` | **KEEP（核心可复用）** |
| `principal_id` / `execution_id` | ✅ | 注释明写 *"principal_id denotes the actual independent AI execution/context"*；C14 opinion 里叫 **`review_execution_id`** | KEEP |
| C13 opinion schema | ✅ | 契约名 `GO_C13_INDEPENDENT_OPINION_V2`（含 candidate/artifact/run/count binding + 原始 opinion 文本 + scoped verdict + 时间戳） | KEEP |
| C14 opinion schema | ✅ | `GO_C14_INDEPENDENT_OPINION_V1`，15 个字段（见 §4.3） | KEEP |
| Git evidence publication/readback | ✅ | `GitAcceptanceBus`（CC: tasks 可写/evidence 只读；HK 相反）+ `ReceiptStore` 原子 no-overwrite 发布 | KEEP |
| disposable PostgreSQL 18.4 sandbox | ✅ | `docker_sandbox.DockerSandbox` + `sandbox/Dockerfile`（`postgres:18.4-bookworm`，`USER 65532`，`-I` 隔离模式） | KEEP |
| KMS/HSM receipt | ⚠ | `kms_receipts.KmsReceiptSigner` 要求 Google Cloud KMS **HSM P-256 ECDSA** + SPKI 指纹，**明确禁止软件兜底** | **DROP_FROM_HARD_PATH**（Lite 不需要） |
| 专用 HK C14 host / 第二个 Docker daemon / C14 systemd daemon | ⚠ | README 明写需要 dedicated acceptance daemon，"Do not use the business daemon" | **DROP_FROM_HARD_PATH** |
| persistent host claims / orphan container reconciliation | ⚠ | `durable_claims.DurableClaims` + README 要求 reconcile | **MODIFY → 可选**（见 §15） |
| C13 reviewer P-256 签名要求 | ❌ 已被 Owner 取消 | README §Owner responsibility boundary：*"Owner correction of 2026-09-25 supersedes the previous reviewer P-256 signature requirement. C13 requires no reviewer key, signature or signing registration."* | **已 DROP** |

### 3.5 #241 分类结论

- **KEEP（Lite 可直接复用）**：canonical JSON、nonce、expiry、Task Ed25519 signer/verifier、Task readback、stdout/manifest hash、`AIReviewGroup`、`principal_id`、C13/C14 opinion schema 字段集、Git evidence bus 语义、disposable PG 18.4 sandbox、artifact/SHA256SUMS 纪律。
- **MODIFY（概念正确，需轻量改）**：`candidate_sha`/`application_tree`/`test_scope_sha256`/`ARTIFACT_SHA256`/`RUN_ID` 的**硬编码常量**（现在钉死 #240 `d4376d6a`，必须改为"当轮冻结候选"参数）；receipt 签名后端（HSM P-256 → 现有 Ed25519）；C13/C14 opinion 记录粒度（补 `github_run_id`/`run_attempt`/`workflow_identity`/`ai_execution_id`/`prompt_sha256`/`input_sha256`/`junit_sha256`）。
- **DROP_FROM_HARD_PATH（Lite 不再作为硬门槛）**：Google HSM/KMS 签名与 SPKI 指纹信任、WIF、专用 HK C14 主机、专用第二个 Docker daemon、C14 systemd daemon、常驻 C14 PostgreSQL、persistent host claims + orphan container reconciliation、`git_acceptance_bus` 的 git ≥2.38 运行时依赖（若 CC/HK 只做 witness）。

---

## 4. Independent AI execution feasibility

### 4.1 结论

**可实现，且实现难度低于预期。** 理由：`implementation / C13 / C14` 三者的上下文隔离在本仓库**不需要新建任何机制**，GitHub Actions 的 job 模型天然提供：

| 隔离维度 | 机制 | 现场依据 |
|---|---|---|
| 进程/上下文 | 每个 job = 独立 VM + 独立容器 + 独立进程 | A/B 代已在用 |
| 会话/对话 | `codex-action` 输入 = **一次性 prompt file**，输出 = **一次性 output file**；无 conversation 延续 API | `poc`/A/B 代 workflow 原文 |
| 文件系统 | 每 job 干净 checkout；`persist-credentials: false` | 全部 C13/C14 workflow |
| 网络 | 可选 `network: disabled`（#241 的 admission 里已把 `network/providers/payments/deployment/production` 全部置 `disabled`） | `acceptance_gate.c13_admission()` |
| 权限 | `permission-profile: ':workspace'`（实现）vs `':read-only'`（C13/C14） | A/B 代 workflow |
| 输出形状 | `output-schema` JSON Schema，非法形状直接失败 | A/B 代 workflow |

### 4.2 三条规则的可实现性与验证

```
implementation_execution_id != c13_execution_id != c14_execution_id
c13_github_run_id          != c14_github_run_id
c13_nonce                  != c14_nonce
```

- 机制：`workflow_run_id` + `job name` + 自生成的 `execution_id` 三元组；**两个 workflow run（推荐）** 而非同一 workflow 两个 job。
- **推荐用两个独立 workflow run**（理由见下），此时 `c13_github_run_id != c14_github_run_id` 由 GitHub 保证（run id 单调且唯一），不需要额外断言。
- 同一 workflow 两个 job 也能满足"不同 execution"，但 `github.run_id` **相同**，需要改用 `check_run_id`（OIDC claim 里也有 `check_run_id`）作为 run identity —— 可行但更绕。

**`ai_execution_id` 怎么来（按优先级）**

1. **首选**：`codex-action` 的 Codex **session id**（实机日志已见：`session id: 01a0a454-d93a-71d3-96ea-4f9a2d641942`）。需在 action 后用 `output-file`/日志提取并写入 bundle。
2. **可靠兜底**：自生成 `execution_id = sha256(task_id‖nonce‖role‖github_run_id‖run_attempt‖workflow_sha‖started_at)`，并在 bundle 里同时记录 `github_run_id`/`run_attempt`/`workflow_identity` 以便外部复核。
3. **可用锚点**：GitHub OIDC 的 `jti`（token 唯一 id）与 `check_run_id`。

**API key 相同是否影响独立性？**
不影响 *execution 独立性*（进程/上下文/会话均为全新），但影响 *操作者层面* 的可审计性。建议：

- **逻辑区分 `C13_AI_API_KEY` 与 `C14_AI_API_KEY`**（两个 secret 指向不同项目/不同 key，或至少不同支出主体），成本几乎为零，收益是可从 API 侧独立核账；
- 若 Owner 不接受双 key，则**必须在报告里显式写清**："C13/C14 共享同一个 API key ⇒ 独立性仅来自 execution/context 分离，不来自凭据分离"，并把它列为已知残余风险。

**stateless / fresh execution**：`codex-action` 已经是 stateless（prompt→output，无状态续传），无需改造。

### 4.3 建议的 bundle 字段（与 #241 契约对齐）

C14 opinion（#241 现有 `GO_C14_INDEPENDENT_OPINION_V1`，15 字段）：
```
contract, role, reviewer_id, review_execution_id, issued_at, review_reference,
opinion, verdict, candidate_sha, application_tree, test_scope_sha256,
task_id, nonce, evidence_sha256, receipt_sha256
```
Lite 建议**增补**（不删任何现有字段）：
```
github_run_id, github_run_attempt, workflow_identity, workflow_sha,
ai_provider, ai_model, ai_reasoning_effort,
prompt_sha256, input_sha256, opinion_sha256,
junit_sha256, stdout_sha256, manifest_sha256,
started_at, completed_at,
c13_opinion_seen_before_seal=false, c13_opinion_sha256=null   # 仅 C14，用于显式证明"先于 seal 未读 C13"
```
其中 `c13_opinion_seen_before_seal / c13_opinion_sha256` 是**现场缺失的一环** —— #241 用 job 依赖保证顺序，但没有**可核验的字段级证明**。

### 4.4 GitHub workflow job separation 是否足够？

- **顺序**：C14 必须先 seal，C13 才能在 `needs: c14` 之后读 C14；任务书还要求 "C14 形成 verdict 前不读 C13 opinion" —— 现有 A/B 代已天然满足（C13 在 C14 之后）。
- **数据面**：C14 job **不得 mount/下载 C13 产物**。A/B 代满足（C14 只下载 `fixed-candidate` artifact）。
- **建议改动**：显式给 C14 job 一个**独立的 `download-artifact` 白名单**，并在 C14 prompt 里加入 *"You must not read or infer any C13 opinion"*，再落一个字段级证明（见 §4.3）。
- **不共享 conversation/context**：已由 stateless 执行保证。

---

## 5. GitHub / OIDC feasibility

### 5.1 实测 discovery（2026-09-25，从本机、CC、HK 三处均 HTTP 200）

```
issuer   = https://token.actions.githubusercontent.com
jwks_uri = https://token.actions.githubusercontent.com/.well-known/jwks
alg      = ['RS256']
claims   = 36 个（原始清单：raw/oidc-configuration.json）
jwks keys= 4 把 RSA/RS256（kid cc413527… / 38826b17… / 38E9B30B… / 4F3E9AD8…）
```

36 个 claim 中含：`aud, iss, sub, exp, iat, nbf, jti, sha, ref, ref_type, ref_protected,
repository, repository_id, repository_owner, repository_owner_id, repository_visibility,
run_id, run_number, run_attempt, workflow, workflow_ref, workflow_sha,
job_workflow_ref, job_workflow_sha, environment, event_name, actor, actor_id,
runner_environment, check_run_id, base_ref, head_ref, enterprise, enterprise_id, issuer_scope`。

### 5.2 问题清单逐条回答

| # | 问题 | 答案 |
|---|---|---|
| 1 | CC/HK 能否在接收 Evidence 时验证 GitHub OIDC JWT | **能。** 只需 `RS256` 验签 + `kid` 选键 + `iss/aud/exp/nbf` 断言。CC 与 HK 实测均可直连 `token.actions.githubusercontent.com` 与 `api.github.com`（HTTP 200）。`cryptography 3.4.8`（现网版本）已足够。 |
| 2 | 是否只依赖 `token.actions.githubusercontent.com` / GitHub 公钥 | **是。** JWKS + `iss` 常量。**唯一外部依赖就是 GitHub 自己。** |
| 3 | 是否需要新增第三方服务 | **不需要。** 不引入 Fulcio/Rekor/Sigstore。 |
| 4 | token 生命周期对验收是否有问题 | `exp = iat + 300s`（多处文档一致，**5 分钟**）。⇒ **必须在 run 内即时验证并落盘**，不能"事后补验"。这正好与任务书设想一致：**首次验证后立即保存**。 |
| 5 | 是否应在 CC/HK 首次验证后保存 | **应该，且是设计要点**：`verified_claims` / `jwt_sha256` / `jwks_kid` / `jwks_fetched_at` / `bound_ephemeral_pubkey_sha256` / `bundle_root`。本轮 PoC-2 已产出该记录的完整样张。 |
| 6 | `aud = go-acceptance:<role>:<ephemeral_pubkey_sha256>` 是否可行 | **可行。** GitHub 支持自定义 `aud`（`core.getIDToken(audience)` 或 `ACTIONS_ID_TOKEN_REQUEST_URL&audience=...`）。⚠ 但**不能**注入任意自定义 claim —— 除 `aud` 外只能用 GitHub 预置 claim。文档提到的 `repo_property_*` 需要组织级自定义属性，本 repo 属 **User 账号**，**不可用**。 |

### 5.3 REMOTE_POC_REQUIRED

以下三点**必须**在真实 Actions run 中才能确认（本轮禁止 push/dispatch）：

```
REMOTE_POC_REQUIRED
  R1  本私有 repo 是否真的签出 id-token JWT
      （实测：118 个 workflow 里 id-token 出现 0 次；repo 目前 environments=0）
      最小验证：一条 workflow_dispatch，permissions: {id-token: write, contents: read}，
      打印 token 的 header/payload（不打印签名）→ 断言 iss/aud/repository/run_id/sha。
  R2  自定义 aud 是否按预期落进 aud 字段（同上一条合并做）
  R3  一次真实 C13 run + 一次真实 C14 run 的 run_id 是否互不相同、C13 是否能拿到 C14 产物
```

### 5.4 简化 fallback（不用 OIDC）评估

```
GitHub Actions run metadata (run_id/run_attempt/workflow_ref/sha)
+ ephemeral public key
+ bundle root
+ CC/HK immediate dual witness
```

**结论：对当前只有两个真人的 GO 项目，这个简化版已经足够做到"不可静默篡改"，但不够做到"可自证运行身份"。** 具体：

- **能防的**：事后换 bundle（root 摘要 + 双 witness 独立重算 ⇒ 见 §9/§10 全部 tamper 被拒）；换 candidate（binding 失败）。
- **不能防的**：**伪造一次"看起来像 GitHub 跑过"的 run**。因为 run metadata 是**提交方自己写进 bundle 的普通字符串**，CC/HK 无法从 GitHub 侧独立求证它。攻击者只要在 bundle 里写一个不存在的 `run_id`，简化版验签依然通过。
- **OIDC 恰好补上这一格**：JWT 由 GitHub 私钥签名 ⇒ CC/HK 可以**独立确认"这个 run 真的存在、确实是这个 repo、这个 workflow、这个 sha"**。
- **实证**：现有 `c01-02-c13-independent.yml` 已经在**手动**做这件事 —— 用 GitHub API 去 `GET /actions/runs/<id>` + `GET /actions/artifacts/<id>` 核对 run 状态与 artifact digest。**这正是 OIDC 要自动化替代的手工步骤。**

⇒ 建议：**Lite 硬门槛用 OIDC（if 可用），fallback 用"GitHub API 只读复核 run/artifact"（已有先例）**；两者都不引入第三方服务。

---

## 6. Local cryptographic PoC results

- 目录：`.workbuddy/tmp/ccv1-142-lite/`（`poc/` 脚本、`evidence/` 产物、`raw/` 现场采集）
- 运行环境：WSL Ubuntu-24.04 · python 3.12.3 · cryptography 41.0.7
- 密钥：**全部 ephemeral**（进程内生成，落盘仅为复验，标注 `SYNTHETIC_POC_ONLY`）；**未触碰任何现场私钥**
- 完整命令/退出码/哈希：`evidence/POC-COMMANDS.md`

### PoC A — Bundle

canonical JSON（`sort_keys=True, separators=(',',':'), ensure_ascii=False`），字段齐备：

```
task_id, nonce, candidate_sha, application_tree, test_scope_sha256,
github_run_id, github_run_attempt, workflow_identity,
ai_provider, ai_model, ai_execution_id,
prompt_sha256, input_sha256, opinion_sha256,
junit_sha256, stdout_sha256, manifest_sha256,
verdict, started_at, completed_at
+ role/side/environment/actor_id/principal_id（#241 对齐）
+ C14 专有：c13_opinion_seen_before_seal=false, c13_opinion_sha256=null
```
不存在的字段使用明确 synthetic 值并带 `mark=SYNTHETIC_POC_ONLY`。

### PoC B — 每次运行临时 key + 签验

```
C13 ephemeral Ed25519 → C13_ROOT = 35271c85b4ed85fda588e80ea8d23f54012c1a5366508c494e7aeccec289ad77
C14 ephemeral Ed25519 → C14_ROOT = 496dae46620b3a30f0996c5e2c129e66dedcdee82cb29c0c830b073c7b2b744d
```

| 场景 | 结果 |
|---|---|
| original → verify | `C13=VERIFY_PASS` `C14=VERIFY_PASS` |
| 改 1 字节（opinion hash）→ verify | `C13=INVALID_EVIDENCE`，明细 `{'signature': True, 'root_rehash': False, 'bundle_rehash': False, 'role': True}` |

**注意**：`signature: True` 说明签名本身没被破坏 —— 拒绝来自**独立重算 root 摘要**。这正是我们想要的语义：签名只证明"谁发的"，**重算才证明"发的是这份内容"**。

### PoC C — 双 Witness

```
CC Witness (独立重算 + 签) → VERIFY_PASS
HK Witness (再次独立重算 + 签) → VERIFY_PASS
FINAL_ROOT = SHA256(canonical{candidate_sha, application_tree, test_scope_sha256, C13_ROOT, C14_ROOT})
           = be768b16c92a61bdb4ae90de871792a0c795ed650e9a18876510f889461080c1
final_acceptance (clean) = ACCEPTED      (authorizes_any_action = false)
```

### 独立性门（正向 + 5 个负例）

正向：`INDEPENDENT`。
负例（全部拒绝，`admissible=False`）：`impl_eq_c13` / `c13_eq_c14` / `same_run_id` / `same_nonce` / `c14_not_blind`（C14 带了 C13 opinion）。

### PoC-2 — GitHub OIDC JWT 离线验签

用**真实 claim 名 + 真实 iss + 真实 alg**，用本地合成的 RS256 key + 合成 JWKS 走完整验签路径：

| 场景 | 结果 |
|---|---|
| original | `verified=True`；`aud=go-acceptance:c13:972239437fc551d9ec2a7d570c603a651901218c456445ff632e3079a159d4dc` |
| tampered `run_id` | `REFUSED` |
| unknown `kid` | `REFUSED` |
| wrong `aud` | `REFUSED` |
| expired（now+400s > exp+60） | `REFUSED` |
| JWKS 换成别的公钥 | `REFUSED` |
| 用**真实** GitHub JWKS 解析 | 4 把 RSA/RS256，`kid` 可选键 ✅ |

```
RESULT: POC_PASS (PoC A/B/C) + POC_PASS (PoC-2)
```

---

## 7. CC live delta（只读实测，2026-09-25 14:42–14:45 CST）

```
hostname = iZj6c7k6k01biwlbnwutu5Z     uptime 21 天     nproc 2
Mem: 7393 MB total / 6369 MB available / Swap 0
disk: /dev/vda3 40G, 用 16G (43%)
kernel 5.15.0-187-generic
python 3.10.12   cryptography 3.4.8   git 2.34.1
gcloud: 无    /usr/lib/google-cloud-sdk: 无    import google: ModuleNotFoundError
GOOGLE_APPLICATION_CREDENTIALS: 无    systemd Environment: 空
```

**服务**

| unit | 状态 |
|---|---|
| `go-ai-command-center.service` | active running |
| `go-boss-request-bridge.service` | **activating (start)**，`ExecStart=/usr/local/libexec/go-boss-request-bridge --once --channel-config /etc/go-command-center/boss-request-bridge-v1.json`，`User=root` |
| `go-boss-request-bridge.timer` | active（55s 前触发） |
| `go-liveness-producer` / `go-liveness-request-transport` / `go-request-fact-cycle` / `go-command-center-state-cycle` | timer active |

**bridge 二进制**：`/usr/local/libexec/go-boss-request-bridge`，130,036 B，含动作仅
`HK_STAGING_CANARY / DEPLOY / ROLLBACK / VERIFY / TEST_PR / UNKNOWN` + `GO_REPOSITORY` ⇒ **`HK_ISOLATED_C14_RETEST` 与 `GO_C13_FIRST_ACCEPTANCE` 均不存在**。
`/etc/go-command-center/` 与 `/usr/local/libexec/` 全目录 grep `c14|isolated|acceptance` **0 命中**。

**密钥（`/etc/go-command-center/keys/`，root-only）**

```
task-manifest-signing.pem        119 B  BEGIN PRIVATE KEY  →  PKCS8 Ed25519（实测 MC4CAQAwBQYDK2Vw…）
task-manifest-signing-public.pem  81 B  BEGIN PUBLIC KEY   → 同一把（HK task-verify.pub 是它的 ssh-ed25519 形式）
github-tasks-writer / github-evidence-reader / github-go-pr-resolver / github-requests-reader.token
```

⇒ **CC 现网唯一签名能力 = Ed25519（Task manifest）**。**没有 P-256、没有 HSM、没有 KMS 凭据。**

**存储/账本**

```
/var/lib/go-command-center/boss-request-bridge-v1/
  ledger.json            464,226 B  {"requests": …, "version": …}   (2026-09-25 14:43)
  environment-slots.json 4,625 B
  post-action-verifies.json
  ledger.lock
/etc/go-command-center/deployment-plans-v1/  (root-only, 07…)
```

### 7.1 Lite 方案 CC 需要增加什么

目标三件：`AcceptanceVerifier` / `WitnessLedger` / `FinalAcceptanceAggregator`。

| 目标组件 | 复用 | 具体落点 | 等级 |
|---|---|---|---|
| `AcceptanceVerifier` | **可大量复用** #241 `ai_acceptance_host.AIAdmissionHost`（`read_review_opinion` 的 `0700`/`0600`/`O_NOFOLLOW` 检查 + 摘要重算）、`c13_attestation.verify`、`c14_review.conclude` | 新增 `control-plane/c13-c14-lite/verifier.py`（照搬 #241 语义），接线到 CC 侧 | **MEDIUM** |
| `WitnessLedger` | 可复用 #241 `ControlReceiptRoute.ReceiptStore` 的原子发布语义（fsync + `os.link` no-overwrite + readback）；但不复用 KMS signer | 新增 `witness_ledger.py` + `/var/lib/go-command-center/c13c14-witness-v1/`（0700，service UID） | **MEDIUM** |
| `FinalAcceptanceAggregator` | 复用 canonical/JSON + 现有 ledger 写入路径 | 新增 `final_acceptance.py`；产出 `FINAL_ROOT` 与双 witness 记录 | **SMALL** |
| 复用项：Task signer | **直接复用现网 `task-manifest-signing.pem`（Ed25519）** | 注入式，无新密钥 | **SMALL** |
| 复用项：canonical JSON | 复用 `house_bridge.canonical` 语义 | — | **SMALL** |
| 复用项：Git bus | 复用现有 git 凭据（`github-tasks-writer` / `github-evidence-reader`）+ 现有 clone 布局 | 若走 #241 `GitAcceptanceBus` ⇒ 需 git ≥2.38（现网 2.34.1）⇒ 否则用现有 bridge 通道 | **SMALL ~ MEDIUM** |
| 复用项：Evidence verifier | 复用 CC 现有 `verify_acceptance_runner` 语义 | — | **SMALL** |
| 复用项：storage | 复用 `/var/lib/go-command-center/` 现有 0700 目录模式 | — | **SMALL** |

### 7.2 「不用 HSM/KMS 后，receipt contract 最小怎么改」

现状（#241 硬约束）：
- `kms_receipts.receipt_payload()` 把 receipt 收窄为 `RECEIPT_FIELDS - {"signature"}`，并钉死 `frozen` 字段集（`schema_version/contract/action_id/environment/candidate_sha/application_tree/test_scope_sha256/verification_state/terminal_state/authorizes_any_action/test_count`）。
- `KmsReceiptSigner` 自述 *"does not discover credentials, select a key, create keys, change IAM or **use a software signing fallback**"* ⇒ **没有 HSM 凭据 ⇒ fail-closed ⇒ CC 侧 C14 host 构造不出来。**
- 签名算法硬绑 **HSM P-256 ECDSA-SHA256 + base64 DER**，且验签前要核对 `version / HSM protection level / P-256 / CRC32C / SPKI SHA-256 fingerprint`。

**最小改法（3 处，不动 schema 字段本身）**

1. **替换 signer 后端（唯一必需改动）**
   把 `KmsReceiptSigner` 换成一个满足同一 4 方法契约的 `Ed25519ReceiptSigner`：
   - 签名：`Ed25519PrivateKey.sign(canonical_record)`
   - 验签：`Ed25519PublicKey.verify`
   - 编码：`base64`（去掉 DER 约束）、去掉 CRC32C/HSM/protection-level/SPKI 校验，改核 **Ed25519 raw pubkey 的指纹**
   - 密钥来源：**复用 CC 现网 `task-manifest-signing.pem`**（或另生成一把专用 receipt key —— 见下）
2. **`RECEIPT_FIELDS` 增加一个算法标识字段**（向后兼容）
   例如 `"signature_algorithm": "ed25519"`（现为隐含 `ecdsa-p256-sha256`）。`receipt_payload()` 的 `fixed` 断言随之按算法分支。
3. **`ControlReceiptRoute` 不动**
   它只依赖 `signer.sign_control_receipt / verify_control_receipt` 与 `ReceiptStore`，**无需改一行**（这正是 #241 分层的好处）。

⚠ **一个必须由 Owner 定的小决策**：receipt 用**复用** `task-manifest-signing`（副作用：Task 签名与 receipt 签名同密钥，key purpose 混用）还是**新建一把 CC 专用 receipt Ed25519 key**？建议**新建专用 key**，理由与 §8 的 witness key 相同。**本轮不生成任何密钥。**

---

## 8. HK live delta（只读实测，2026-09-25 14:43 CST）

```
hostname = iZj6ccs8t04f1p4d8pe69zZ   uptime 21 天    nproc 2
Mem: 3495 MB total / 1629 MB available / Swap 0      disk 40G, 用 12G (32%)
python 3.10.12   cryptography 3.4.8   git 2.34.1
```

**#245 baseline 保护状态（逐字节复核）**

```
/opt/go-hk-agent-rebuilt/hk_agent/test_pr.py   86c3cd055e6a36691ce91a290ca0523eb09f0747f424aa730915b35d54bd2199
/opt/go-hk-agent-rebuilt/hk_agent/transport.py e4e2244cc652130f1c94c8632ab9f42a70bd08435278fc2c30e5d73d07852194
/opt/go-hk-agent-rebuilt/hk_agent/core.py      44b04dd83ca5f192f031bb5541deb5c571241e0c076d086e79a8651909a39f7c
```
⇒ 与 CCV1-139 安装后记录**逐字节一致**，`#245_TOUCHED=NO` ✅

**服务**：`go-hk-agent.service` = `inactive (dead)`（oneshot 正常终态）；`go-hk-agent-preflight-probe.service` = active running。
`ExecStart=/usr/local/libexec/go-hk-agent --run-once`，`User=go-hk-agent`。

**配置 `/etc/go-hk-agent/agent.json`**
```json
{"authority":"GO-COMMAND-CENTER","environment":"HK-STAGING-01",
 "task_verify_key":"/etc/go-hk-agent/keys/task-verify.pub",
 "evidence_signing_key":"/etc/go-hk-agent/keys/evidence-signing.pem",
 "tasks_repo":"git@github.com:chenzhenxi1-sudo/go-control-tasks.git",
 "evidence_repo":"git@github.com:chenzhenxi1-sudo/go-control-evidence.git",
 "tasks_key":".../tasks-read","evidence_key":".../evidence-write",
 "go_source_reader_key":".../github-go-source-reader"}
```

**密钥**
```
task-verify.pub      81 B BEGIN PUBLIC KEY   → ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPCnf8…（= CC task-manifest-signing 公钥）
evidence-signing.pem 119 B BEGIN PRIVATE KEY → PKCS8 **Ed25519**
evidence-signing.pub 81 B
tasks-read / evidence-write / github-go-source-reader（git 凭据齐备）
```

⇒ **HK 已有 Ed25519 evidence 签名能力，且与 CC 的 Task 密钥成对。**
**`c14|isolated_c14|acceptance` grep**：仅 `test_pr.py` 命中（`acceptance` 一词），**无任何 C14 动作**。

**Docker**：业务 10 容器（`go-822-staging-api/redis/caddy/…-worker`）运行中；镜像含 6 个 `go-hk-test-pr:*`（各 ~461 MB）+ `caddy:2.8-alpine`。

**账本**：`/var/lib/go-hk-agent/ledger/agent.sqlite3`（= TEST_PR 的 agent ledger，**非** C14 专属）。

### 8.1 逐条回答

| # | 问题 | 答案 |
|---|---|---|
| 1 | 能否与现有 Agent 完全分离 | **能。** 新增独立 service/脚本，复用 `/etc/go-hk-agent/keys/` 与 ledger 目录之外的独立路径；`go-hk-agent.service` 是 oneshot，天然无冲突 |
| 2 | 是否必须修改 #245 | **不必。** `#245_TOUCHED=NO` 是可达目标（本轮实测三文件未动） |
| 3 | 能否做成独立小 service/script | **能。** 建议 `go-c14-witness.service`（oneshot + timer 或 socket 触发），或干脆一个被 CC 触发的一次性脚本 |
| 4 | 能否复用现有 Evidence signing Ed25519 | **能**（技术上零成本） |
| 5 | 复用会不会混淆 key purpose | **会。** 现有 key 的 purpose 是"HK 执行器签 Evidence"；witness 是"第三方见证签记录"。混用后**审计上无法区分"HK 说跑过了"和"HK 说它看到过这份根"** |
| 6 | 是否更适合以后生成独立 witness key | **是，建议独立 witness key。** 但**本轮不生成**（属 `SECRET_CHANGE=NO` 范围）；正式改造时由 Eason 在 HK 上一次性生成并登记公钥 |
| 7 | 当前机器资源是否足够 | **足够。** witness 只读 bundle、重算 sha256、验签、写一条记录 |
| 8 | 实际运行资源预计 | **近似可忽略**：单次 CPU < 1 s、内存 < 50 MB、磁盘 < 1 MB/次；**远低于** CCV1-141 里"HK 叠加 postgres 沙箱会挤压业务容器"的量级 —— 因为 **Lite 不在 HK 跑沙箱** |

---

## 9. Dual witness PoC

已在本机完整跑通（§6 PoC C），关键点：

- **CC Witness** 与 **HK Witness** 各自**独立重算** `candidate / C13_ROOT / C14_ROOT`（不信任对方结论），各自用**独立 ephemeral key** 签名。
- 验证器**不看 witness 的自我声明**，而是：`signature` + `final_root_recompute` + `c13_root_matches_bundle` + `c14_root_matches_bundle` + `candidate/tree/scope` 五重绑定。
- 结果：`CC=VERIFY_PASS`、`HK=VERIFY_PASS`；`final_acceptance(clean)=ACCEPTED`，且 `authorizes_any_action=false`（AI opinion 不授权任何动作 —— 与 #241 README 的 Owner 责任边界一致）。

```
FINAL_ROOT = SHA256(
    candidate_sha ‖ application_tree ‖ test_scope_sha256 ‖ C13_ROOT ‖ C14_ROOT )
```

---

## 10. Tamper tests（4 例，全部检出）

| # | 篡改 | C13 verify | C14 verify | CC witness verify | final_acceptance | 检出 |
|---|---|---|---|---|---|---|
| T1 | 改 C13 opinion | INVALID_EVIDENCE | VERIFY_PASS | INVALID_EVIDENCE | **INVALID_EVIDENCE** | ✅ |
| T2 | 改 C14 verdict（PASS→FAIL） | VERIFY_PASS | INVALID_EVIDENCE | INVALID_EVIDENCE | **INVALID_EVIDENCE** | ✅ |
| T3 | 改 candidate SHA | INVALID_EVIDENCE | INVALID_EVIDENCE | INVALID_EVIDENCE | **INVALID_EVIDENCE** | ✅ |
| T4 | 改 JUnit hash | VERIFY_PASS | INVALID_EVIDENCE | INVALID_EVIDENCE | **INVALID_EVIDENCE** | ✅ |

**检出机制**：不是"签名不匹配"，而是 **root 摘要独立重算不一致**（`root_rehash=False`）。
**残余**：若攻击者同时改 bundle **并且**持有任一角色私钥，即可重新签名通过 —— 这由 §5 的 OIDC run 绑定 + **双 witness 的"先见先记"** 兜底（见 §16 R4）。

---

## 11. Before → After

| 模块 | CURRENT | → | LITE TARGET |
|---|---|---|---|
| **C13** | 机器门 / 盖章件（`C13_RESULT.json` 硬编码）；AI 版仅存在于 side branch 且从未跑通 | → | GitHub ephemeral runner 上 `openai/codex-action@v1` + `:read-only` + `output-schema`，产出真实 AI opinion，`:read-only` 上下文，独立 run_id |
| **C14** | 需要专用 HK runtime host + 第二个 Docker daemon + 常驻 PostgreSQL（且从未装成） | → | 另一个 GitHub ephemeral runner 上 disposable Docker + `postgres:18.4`；HK 只做 secondary witness |
| **AI execution** | 无 execution id 落盘；同一 `OPENAI_API_KEY` | → | 每个 role 一个独立 run；落 `ai_execution_id`（Codex session id 或自生成）；建议逻辑分离 C13/C14 两个 key |
| **Sandbox** | HK 主机上叠加沙箱（内存 1.6 GB 可用 ⇒ OOM 风险） | → | GitHub-hosted runner（4 vCPU/16 GB 级，零占用 CC/HK）；沙箱镜像 `postgres:18.4-bookworm` + `USER 65532` |
| **Claims** | `durable_claims.DurableClaims`（SQLite，单 Runner，需 reconcile） | → | GitHub run 的一次性语义（run 不可重放）+ CC witness ledger 的 first-seen 记录；`DurableClaims` 降为 OPTIONAL |
| **Evidence** | Git bus（`git_acceptance_bus`，需 git ≥2.38）+ CC-only receipt store | → | bundle(root-signed) 发布到 GitHub Actions artifact + CC/HK witness 记录各落本地 ledger；**不引入 Record 到新库** |
| **Receipt** | HSM P-256 ECDSA + SPKI 指纹 + CRC32C（fail-closed，无凭据装不上） | → | **Ed25519 receipt**（复用 CC 现有 PKCS8 Ed25519，或专用新 key）；schema 字段集不变，仅加 `signature_algorithm` |
| **HSM** | 硬门槛（`no software signing fallback`） | → | **不需要**（`OPTIONAL_ENHANCEMENT`，可将来加回） |
| **CC** | 只有 Task Ed25519 + bridge（6 个 HK_STAGING_* 动作），无 C14/C13 概念 | → | `AcceptanceVerifier` + `WitnessLedger` + `FinalAcceptanceAggregator`；复用 Task signer/canonical/git 凭据/storage 布局 |
| **HK** | TEST_PR 执行器；`go-hk-agent` inactive；无 witness 概念 | → | `AcceptanceWitness`（read bundle → verify → rehash → compare → sign → persist），独立小 service，**`#245_TOUCHED=NO`** |
| **GitHub** | 118 workflow，仅 26 在 main；C13/C14 AI workflow 不在 main；零 `id-token`；`environments=0` | → | 2 个可派发的新 workflow（C13 / C14）落 main；开 `id-token: write`；自定义 `aud` 绑 ephemeral pubkey 摘要；run identity 发布 |

---

## 12. Owner / 老版 GPT / GitHub 侧改动清单（A 类）

> 全部必须在 repo 内完成；本轮**未做任何改动**。

| # | 项 | 现状 | 目标 | 具体文件 | 等级 | 可否直接复用 |
|---|---|---|---|---|---|---|
| A1 | C13 AI review workflow | `v70-r3-ai-cell-pipeline.yml` 的 `c13` job 只存在于 `ops/codex-coding-runner-pilot-20260914`，从未跑通 | 落 `main`，可 `workflow_dispatch`，产出真实 C13 opinion | `.github/workflows/c13-lite-review.yml`（**新建**） | **MEDIUM** | **prompt/`output-schema`/`:read-only`/artifact 约定 1:1 复用** |
| A2 | C14 AI review workflow | 同上（`c14` job） | 落 `main`，独立 run | `.github/workflows/c14-lite-review.yml`（**新建**） | **MEDIUM** | 同上 |
| A3 | AI review 调用 | `openai/codex-action@v1` 已在本 repo 成功 | 沿用；固定 `model` / `effort`，把 Codex session id 写入产物 | A1/A2 内 | **SMALL** | ✅ 直接复用 |
| A4 | C13/C14 execution 分离 | 已由 job/runner 结构保证，但无字段级证明 | 加 `c13_opinion_seen_before_seal=false` + `c13_opinion_sha256=null`；C14 job 的 artifact 白名单不含 C13 | A1/A2 | **SMALL** | 结构已复用，仅补证明 |
| A5 | bundle schema | 老版 `EVIDENCE.json` / `C13_SOURCE_BINDING.json` 字段不全（无 `ai_execution_id` / `opinion_sha256` / `junit_sha256` 等） | 采用 §4.3 的字段集；正式 schema 文件 | `.github/workflows/…` + `control-plane/c13-c14-lite/contracts/*.schema.json`（**新建**） | **MEDIUM** | #241 的 `GO_C13_INDEPENDENT_OPINION_V2` / `GO_C14_INDEPENDENT_OPINION_V1` 字段集可复用 |
| A6 | GitHub run binding | 老版只记 `github.run_id`/`github.job`/`run_attempt` 进文本 | 加 `id-token: write` + `core.getIDToken("go-acceptance:<role>:<pubkey_sha256>")`，把 JWT 与其 sha256 一并发布 | A1/A2 | **MEDIUM** | **无先例**，`REMOTE_POC_REQUIRED`（§5.3） |
| A7 | evidence publication | `upload-artifact@v4` + SHA256SUMS 已在用 | 沿用；额外发布 root 记录与（可选）JWT | A1/A2 | **SMALL** | ✅ 直接复用 |
| A8 | 旧 #241 contract 收敛 | #241 用 HSM receipt + 专用 host（Draft/uninstalled） | 按 §7.2 把 receipt 后端换 Ed25519；把 `c13_attestation.py` 的硬编码常量参数化 | `control-plane/c13-c14-v2/*` 或新目录 | **MEDIUM** | 分层设计允许"只换 signer"，`ControlReceiptRoute` 零改动 |
| A9 | `main` 落地 | C13/C14 全在 side branch；`main` 仅 26 workflow | 把 A1/A2（+ schema）合入 `main` | repo | **SMALL（但需 Owner 授权）** | — |
| A10 | Actions secret | `OPENAI_API_KEY` 存在且可用，但**余额曾耗尽** | 保证配额；可选新增 `C13_AI_API_KEY` / `C14_AI_API_KEY` | repo Settings | **SMALL（Owner 资源决策）** | — |
| A11 | Environments（可选） | `environments=0` | 若要让"人是最终授权方"落在平台层：为 C14 建 environment + required reviewer | repo Settings | **SMALL** | `OPTIONAL_ENHANCEMENT` |

---

## 13. 陈震曦 / WorkBuddy / CC 侧改动清单（B 类）

| # | 项 | 目标文件 / 模块 | 服务/配置 | 等级 | 说明 |
|---|---|---|---|---|---|
| B1 | `AcceptanceVerifier` | `control-plane/c13-c14-lite/verifier.py`（新） | 被 bridge 或独立 oneshot 调用 | **MEDIUM** | 复用 #241 `AIAdmissionHost.read_review_opinion` 的 `0700/0600/O_NOFOLLOW/摘要重算` 与 `c13_attestation.verify`；加 §4.3 新字段校验 |
| B2 | `WitnessLedger` | `witness_ledger.py`（新）+ `/var/lib/go-command-center/c13c14-witness-v1/`（0700, service UID） | 独立目录 | **MEDIUM** | 复用 #241 `ReceiptStore` 的 fsync + `os.link` no-overwrite + readback 语义；**去掉 KMS** |
| B3 | `FinalAcceptanceAggregator` | `final_acceptance.py`（新） | 被 B1/B2 调用 | **SMALL** | 产出 `FINAL_ROOT` + 双 witness 记录 |
| B4 | receipt contract 简化 | `kms_receipts.py` → 改为/并列 `ed25519_receipts.py`；`RECEIPT_FIELDS` 加 `signature_algorithm` | `control_receipt_route.py` **不改** | **MEDIUM** | 见 §7.2；**唯一真正需要改动的核心逻辑** |
| B5 | 复用现网密钥 | `/etc/go-command-center/keys/task-manifest-signing.pem`（Ed25519） | 已有 | **SMALL（KEEP）** | 建议另生成一把专用 receipt Ed25519 key（待授权） |
| B6 | git 运行时 | 现网 2.34.1；#241 `GitAcceptanceBus` 要求 ≥2.38 | 仅在走该模块时需要 | **SMALL ~ MEDIUM** | **Lite 可不走**：witness 记录走现有 bridge/agent 通道即可 |
| B7 | Python/依赖 | 现网 3.10.12 + cryptography 3.4.8 | — | **SMALL** | #241 代码无 3.11+/3.12+ 语法（已 grep 确认），3.10 可运行；⚠ 但 `cryptography 3.4.8` 已很旧，建议随改造升级到受支持版本 |
| B8 | C13/C14 action 白名单 | 现网 bridge 仅 6 个 `HK_STAGING_*` 动作，**无 C14/C13 动作** | — | **MEDIUM** | **Lite 可绕开**：若 C13/C14 完全由 GitHub 自驱 + CC/HK 只 witness，则**不需要新增 CC action**；若要 CC 发起 C14，则需扩 bridge allowlist |
| B9 | storage 布局 | `/var/lib/go-command-center/` 现有 0700 模式 | — | **SMALL（KEEP）** | — |
| B10 | Evidence verifier | CC 现有 runner 验签语义 | — | **SMALL（KEEP）** | — |

**B 类总评：MEDIUM。** 无新增硬件、无新增云服务、无 IAM 变更；核心是 **3 个新模块 + 1 次 receipt signer 替换 + 1 组 schema。**

---

## 14. 陈震曦 / WorkBuddy / HK 侧改动清单（C 类）

| # | 项 | 目标 | 是否碰 #245 | 等级 |
|---|---|---|---|---|
| C1 | `AcceptanceWitness`（read bundle → verify → rehash → compare → sign → persist） | `/opt/go-c14-witness/`（新独立路径）+ `go-c14-witness.service`（新 unit，oneshot/timer） | **`#245_TOUCHED=NO`** | **SMALL** |
| C2 | readback / local record | `/var/lib/go-hk-agent-witness/`（新 0700 目录）或独立路径 | NO | **SMALL** |
| C3 | witness 签名 key | 建议**新建独立 Ed25519 witness key**；**本轮不生成** | NO（新路径，不覆盖 `/etc/go-hk-agent/keys/`） | **SMALL** |
| C4 | 网络出口 | 需要到 `token.actions.githubusercontent.com` / `api.github.com`（实测已通 HTTP 200） | NO | **SMALL** |
| C5 | 资源 | 单次 < 1 s CPU / < 50 MB 内存 / < 1 MB 磁盘 | NO | **SMALL** |
| C6 | HK 不再承担 C14 Runner / Docker / PostgreSQL | — | **减少工作**，不新增 | — |

**C 类总评：SMALL。** 目标态 `#245_TOUCHED=NO` 可达。

---

## 15. DROP / KEEP / MODIFY 矩阵

### DROP_FROM_HARD_PATH（Lite 不再作为门槛，仅评估，不改 #241）

| 项 | 理由 |
|---|---|
| Google HSM receipt（P-256 + SPKI 指纹 + CRC32C） | CC 无 KMS 凭据（实测）；AI opinion 本就 keyless（Owner 09-25 已改口径） |
| Google Cloud KMS / WIF | 同上；Lite 不需要任何云 KMS |
| 第三台 C14 ECS / dedicated HK C14 host | C14 计算搬到 GitHub ephemeral runner |
| Dedicated second Docker daemon on HK | 同上；HK 只 witness |
| C14 systemd daemon（HK 常驻） | 改为按需 oneshot witness |
| 常驻 C14 PostgreSQL | GitHub service container / disposable 容器 |
| `durable_claims` 作为硬门槛 + orphan container reconciliation | GitHub run 一次性语义 + witness first-seen 已覆盖；降为 OPTIONAL |
| C13 reviewer P-256 签名 / 签名登记 | **Owner 2026-09-25 已取消** |
| `git_acceptance_bus` 的 git ≥2.38 硬前置 | Lite 不必走该模块（否则需侧装 ≥2.38 git） |
| `Registration Authority` / `Independent Authority` | 不在 `Independent AI Review Execution` 定义内 |

### KEEP

`canonical JSON` ｜ `nonce` ｜ `expiry` ｜ `candidate_sha`/`application_tree` binding ｜ `test_scope_sha256` ｜ CC Task Ed25519 signer/verifier ｜ Task exact readback ｜ JUnit identity 校验 ｜ stdout/manifest hash ｜ `AIReviewGroup` ｜ `principal_id` / `review_execution_id` ｜ C13/C14 opinion schema **字段集** ｜ Git evidence 发布/读回语义 ｜ disposable `postgres:18.4` 沙箱（Dockerfile + payload） ｜ artifact + SHA256SUMS + `upload-artifact@v4` ｜ `codex-action` 调用形态 + `:read-only` + `output-schema` ｜ 双 witness 独立重算 ｜ `authorizes_any_action=false` 语义

### MODIFY

| 项 | 改动方向 |
|---|---|
| `c13_attestation.CANDIDATE/TREE/SCOPE/ARTIFACT_SHA256/RUN_ID` | 从硬编码 #240 常量 → 参数化"当轮冻结候选" |
| `c14_isolated_runner.SCOPE_COMMANDS` + `assert digest(...)==SCOPE` | 同上 |
| receipt 签名后端 | KMS HSM P-256 → Ed25519；`RECEIPT_FIELDS` 加 `signature_algorithm` |
| C13/C14 opinion 记录 | 增补 `github_run_id/run_attempt/workflow_identity/ai_execution_id/prompt_sha256/input_sha256/junit_sha256/stdout_sha256/manifest_sha256/started_at/completed_at` |
| C14 opinion | 增补 `c13_opinion_seen_before_seal=false` / `c13_opinion_sha256=null` |
| 旧 AI workflow | 从 `ops/*` 分支搬 `main`，并拆成两个独立 run |
| `main` 上的 C13/C14 空白 | 新增可派发 workflow |
| CC bridge allowlist | 仅在"要 CC 主动发起 C14"时才需扩展；Lite 可不做 |

---

## 16. Risks / blockers（含"当前设想遗漏的真实阻断"）

| # | 项 | 性质 | 严重度 | 证据 | 处置 |
|---|---|---|---|---|---|
| **R1** | **OpenAI API 余额/配额** | **真实阻断（已发生过）** | **高** | job `104321212179` 真日志：`You have no credits remaining.` ⇒ 12 个 AI job 全灭 | **Owner 资源决策**：保证配额 + 设失效告警。这是任务书清单里**没有**的一条 |
| R2 | `id-token: write` 在本私有 repo 是否真能签发 | 待验证 | 中 | 118 workflow 零 `id-token`；`environments=0` | `REMOTE_POC_REQUIRED`（§5.3 R1/R2），**禁止本轮自行 push** |
| R3 | C13/C14 workflow 不在 `main` ⇒ 不可派发 | 权限/流程 | 中 | `main` 26 workflow，`.github/workflows/c13-*.yml` 404 | 需 **Owner 授权**把 A1/A2 合入 `main` |
| R4 | "不可静默篡改"的边界 | 设计残余 | 中 | §10 全部 tamper 被拒，但**同一持有者重签可过** | OIDC run 绑定 + **双 witness 先见先记**；witness 公钥须**带外登记**（pin） |
| R5 | 私有 repo + User 账号 ⇒ `repo_property_*` 自定义 claim 不可用 | 平台限制 | 低 | OIDC `claims_supported` 实测 36 项，无 `repo_property_*` | 只用 `aud` 自定义 + 标准 claim |
| R6 | OIDC token 仅 5 分钟有效 | 时序 | 低 | 文档 + 多来源一致 | 必须**即时验证并落盘**，不可事后补验 |
| R7 | `cryptography 3.4.8`（CC/HK 现网）过旧 | 安全债 | 低-中 | 实测版本 | 随改造升级；本轮不改 |
| R8 | git 2.34.1 < 2.38 | 依赖缺口 | 低（Lite 可绕） | `git_acceptance_bus` L112-114 硬拒 | Lite 走现有 bridge 通道；否则侧装 ≥2.38 |
| R9 | CC python 3.10.12 vs #241 开发环境 3.12 | 兼容性 | 低 | 已 grep：无 3.11+/3.12+ 语法 | 3.10 可运行；安装时固定解释器 |
| R10 | #241 head 持续漂移 | 流程 | 低 | 今日 `3c2f93d1`→`8322a5c8`→`8e1ad011`→`501c01b3` | **任何实施先冻结 commit SHA**（沿用 CCV1-140 冻结规则） |
| R11 | 同一 `OPENAI_API_KEY` 跑 C13 与 C14 | 审计 | 低 | 现网只有一个 secret | 逻辑分离 `C13_AI_API_KEY` / `C14_AI_API_KEY`；否则显式登记为残余风险 |
| R12 | AI opinion 不可复现（模型非确定性） | 固有 | 低 | 设计使然 | opinion 只作为**一次已发生执行的记录**；冻结输入 + 记录 model/effort/session id |
| R13 | 未设 GitHub environment / required reviewer | 治理（可选） | 低 | `environments=0` | `OPTIONAL_ENHANCEMENT`（A11） |

**`OPTIONAL_ENHANCEMENT`（明确不得作为 Lite 必要条件）**：Google Cloud KMS 的 HSM receipt（把 P-256 加回作为"机器签名"层）｜Sigstore Fulcio/Rekor 透明日志｜GitHub Environment + required reviewer 人工闸门｜专用 HK witness 硬件/独立主机。

---

## 17. Recommended implementation sequence（事实底稿顺序，供 ChatGPT 生成最终改造方案）

1. **Owner 决策点（前置，不可绕过）**
   - D1 AI API 配额与失效告警（R1）
   - D2 是否授权把 C13/C14 workflow 合入 `main`（R3）
   - D3 是否开 `id-token: write` 并允许一次远程 PoC（R2）
   - D4 是否分离 `C13_AI_API_KEY` / `C14_AI_API_KEY`（R11）
   - D5 receipt/witness 用独立新 Ed25519 key，还是复用现网 Task key（§7.2 / §8 问题 6）
2. **`REMOTE_POC_REQUIRED` 最小远程 PoC**（只做一个 workflow，`workflow_dispatch`，`id-token: write`）
   - 打印 token 的 header/payload（**不打印签名**）；断言 `iss` / `aud`（自定义） / `repository` / `run_id` / `sha`
   - 输出：`oidc-real-claims.json` ⇒ 冻结为本阶段验收凭证
3. **GitHub 侧（A1/A2/A5/A6/A7）**：两条独立 workflow（C13、C14），复用旧 prompt/schema；发布 bundle + root + 可选 JWT
4. **一次真实双 run 演练**：确认 `c13_run_id != c14_run_id`、C13 能取到 C14 产物、C14 未见过 C13
5. **CC 侧（B1/B2/B3）**：`AcceptanceVerifier` / `WitnessLedger` / `FinalAcceptanceAggregator`（先 dry-run，不接 live bus）
6. **receipt 简化（B4）**：Ed25519 signer + `signature_algorithm` 字段；跑 #241 现有 101 套件确保不回归
7. **HK 侧（C1/C2/C3）**：独立 `go-c14-witness` service + 独立 witness key；**先验证 `#245_TOUCHED=NO`**
8. **端到端一次**：C13 run → C14 run → CC witness → HK witness → `FINAL_ROOT`
9. **回归**：重跑 §10 四例 tamper + §6 独立性门负例

---

## 18. Final RESULT

```
RESULT = LITE_FEASIBLE_MEDIUM_DELTA

GitHub delta          = MEDIUM   (2 条新 workflow 落 main + bundle schema + run/OIDC 绑定；
                                  旧 prompt/output-schema/codex-action/artifact 纪律可 1:1 复用)
CC delta              = MEDIUM   (3 个新模块 + receipt signer: HSM P-256 → Ed25519；
                                  ControlReceiptRoute 与 Task signer 零改动)
HK delta              = SMALL    (#245_TOUCHED=NO；独立 oneshot witness service；资源近似可忽略)
New hardware required = NO
HSM required          = NO
External new service  = NO       (仅 GitHub + 现有 AI API)
Third-party IdP/Rekor = NO

Local PoC             = PASS     (bundle/签验/双 witness/4 篡改全检出 + OIDC 离线验签 5 负例全拒)
Upstream #241 suite   = PASS     (Linux 离线 Ran 101 tests / OK)
REMOTE_POC_REQUIRED   = YES ×3   (真实 id-token 签发 / 自定义 aud / 双 run 身份)

真实阻断（需 Owner 决策，非技术不可行）:
  R1 OpenAI API 配额 —— 已实证导致旧版 C13/C14 AI 全部失败
  R3 C13/C14 workflow 需授权合入 main
  R2 id-token 契约需一次真实 run 确认

定性纪律（不得越界表述）:
  本轮 = OFFLINE_FEASIBILITY_AND_LOCAL_POC，不是 C13/C14 验收；
  未产生任何真实 AI opinion；未安装任何东西；未改 #241；未碰 CC/HK 任何文件。
  INDEPENDENT_C14 状态不变；本报告不得被引用为 C14 PASS。
```

---

## 附录 A · 本轮采集到的关键 URL / 路径

- 旧 AI C13/C14 实现（可复用母本）
  `ops/codex-coding-runner-pilot-20260914` → `.github/workflows/v70-r3-ai-cell-pipeline.yml`（449 行，`c13`/`c14` job 在 L325-L449）
  `ops/c01-formal-20260915` → `.github/workflows/c01-formal-run.yml`（453 行）、`c01-gates-from-candidate.yml`、`c01-formal-continuation.yml`
- AI 能力证明：`ops/openai-api-smoke-20260915` → `openai-api-smoke.yml`（run `34961376796`，success，2026-09-15T11:05:12Z）；`ops/c01-runner-repair-20260915` → `c01-codex-action-smoke.yml`（run `34961750411`，success）
- 失败真因日志：run `34950847366` / job `104321212179`
  `raw/job104321212179.log` 第 1436 行 `You have no credits remaining.`
- #241 冻结基线：`501c01b3a829e04452de43b4835fe7c649bc2f5c`（`control-plane/c13-c14-v2/` 34 blobs）
- OIDC discovery 原件：`raw/oidc-configuration.json`、`raw/oidc-jwks.json`

## 附录 B · 证据文件清单

```
.workbuddy/tmp/ccv1-142-lite/
├── gh.py / ghq.py / ghfile.py / ghtree.py     # 只读取件工具（token 不落盘）
├── raw/
│   ├── pr241.json                             # #241 冻结字段
│   ├── pr241_c13c14v2.txt / pr241_controlplane.txt
│   ├── pr241/                                 # 34 个 blob 原文
│   ├── wf/                                    # 18 个 workflow 原文
│   ├── workflows1.json / workflows2.json      # 118 个 workflow 索引
│   ├── job104321212179.log                    # 失败 job 真日志
│   ├── oidc-configuration.json / oidc-jwks.json
├── poc/
│   ├── ccv1_142_poc.py                        # PoC A/B/C
│   ├── ccv1_142_oidc_poc.py                   # PoC-2 OIDC
│   └── run_upstream_suite.sh                  # #241 离线复跑
└── evidence/
    ├── POC-COMMANDS.md                        # 命令/退出码/哈希
    ├── SHA256SUMS.txt                         # 87 个证据文件逐字节哈希
    ├── poc-report.json / poc-run.log
    ├── oidc-poc-report.json / oidc-poc.log
    ├── bundles/  (c13_bundle / c14_bundle / c13_root / c14_root / cc_witness / hk_witness)
    ├── keys/     (4 组 ephemeral 公私钥，仅本 PoC 用)
    └── synthetic-jwks.json
```