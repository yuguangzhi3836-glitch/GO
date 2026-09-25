# GO C13/C14 Lite 最终改造设计 V2

> 状态：C13/C14 Lite 总体方向已由陈震曦与 Owner 于 2026-09-25 电话确认；C01–C14 固定职责随后由 Owner 进一步统一说明。本版本按 Owner 最新职责基线修订 C13/C14 角色定义。本文用于工程实施，不是二次方案征求。

## 1. 设计目标

在不新增硬件、不新增云信任体系、不新增第三方服务的前提下，使用现有：

- Command Center ECS
- HK-STAGING ECS
- GitHub / GitHub Actions
- 现有 AI API
- 现有 Task / Evidence 签名能力

实现两类**职责不同、执行独立**的长期 AI 审核能力：

- **C13：独立质量验收**
- **C14：宪法、权限、法律、监管、合同与 AI 行为规则审查**

两者都必须对明确候选、范围、证据和结论负责，但**不再把 C14 设计成“第二个 C13”或第二套 Docker/PostgreSQL 质量复测员**。

Lite 的共同目标仍然是：

> **Independent AI Review Execution + tamper-evident + dual-witness**

即审核执行相对独立、结果可验证、可追溯、不可静默篡改，同时不新增第三台 ECS、不依赖 HSM/KMS/WIF。

---

## 2. Owner 最新职责基线

组织关系：

```
真人负责人
   ↓
GO 指挥中心
   ↓
调度中心
   ↓
C01–C14 AI 常设团队
   ↓
香港执行器（现场执行环境）
```

关键边界：

- 指挥中心：接收真人目标与授权，确定优先级和执行边界，控制部署授权。
- 调度中心：拆分、派发、依赖协调、状态跟踪、超时恢复和闭环。
- C01–C14：各自承担固定领域的长期责任。
- 香港执行器：执行正式派发的现场任务；**香港是运行环境，不改变 C01–C14 的责任归属。**
- C12：平台、安全与运维，提供运行环境、权限、安全和部署执行能力。
- C13：独立质量验收。
- C14：宪法、法务与规则。

因此：

> **AI Team 是逻辑责任主体，不等于一台服务器。**

这也是 Lite 不为 C13/C14 单独购买常驻 ECS 的直接组织依据。

---

## 3. “Independent”的正式定义

C13 与 C14 都要求相对于被审核实现保持独立：

```
implementation_execution != c13_execution
implementation_execution != c14_execution
c13_execution != c14_execution
```

这里的 `independent` 表示：

> **Independent AI Review Execution**

它要求：

- fresh AI execution/context；
- 不继承实现 AI 的 conversation/reasoning；
- 不由开发者自测替代；
- 输出绑定候选、范围、证据和结论；
- 审核结果不冒充真人签字或部署授权。

它**不表示**：

- Independent Authority
- Independent Organization
- Independent Cloud Account
- Independent GitHub Account
- Independent Physical Host
- Independent HSM
- Independent Signing Authority

### C13/C14 之间如何保持“相对独立”

因为两者现在审核维度不同，不再要求两边完全“互相隔绝到不知道对方存在”。

正式规则改为：

1. C14 的规则/合规分析必须由自己的 fresh execution 独立形成；
2. C13 的质量验收必须由自己的 fresh execution 独立形成；
3. C13 不继承 C14 的 conversation/reasoning，不把 C14 的判断当作质量测试结论；
4. C14 不继承 C13 的 conversation/reasoning，不把 C13 的测试通过当作规则/合规通过；
5. 如流程上需要，C13 可以读取**已经 sealed 的 C14 状态/适用范围/问题是否闭合**作为准入事实，但不接管 C14 的判断职责；
6. C14 可以读取必要机器事实作为审查证据，但不因此承担 C13 的质量验收职责。

---

## 4. 总体架构

```
                         Human Owner / Operator
                                  |
                                  v
                         Command Center (CC)
                         freeze / authorize
                                  |
                              Scheduler
                  +---------------+---------------+
                  |                               |
                  v                               v
           GitHub C14 Run                  GitHub C13 Run
      rule/compliance review              quality acceptance
        fresh AI context                  fresh AI context
      constitution/permissions          regression/security/
      law/regulation/contracts          recovery/journey tests
             |                               |
          C14 seal                         C13 seal
                  \                       /
                   \                     /
                    +------ sealed -------+
                             bundles
                                |
                    +-----------+-----------+
                    |                       |
                    v                       v
                 CC witness              HK witness
                    +-----------+-----------+
                                |
                           FINAL_ROOT
                                |
                     deployment planning
                                |
                         Hong Kong preflight
                                |
                      explicit human deploy
                          authorization
```

香港执行器仍保留原有部署前检查、正式执行、健康检查与证据回传职责。

**Lite 只是不再把 C13/C14 团队身份绑定到香港机器。**

---

## 5. 候选与审核范围冻结

任何正式 C13/C14 opinion 都必须绑定明确对象。

共同至少包含：

- repository
- candidate_commit_sha
- application_tree
- task_id / request_id
- nonce
- issued_at
- workflow identity / workflow SHA
- reviewer prompt SHA256
- reviewer execution identity

### C13 额外绑定

- quality_test_scope_sha256
- JUnit / stdout / manifest / runtime evidence hashes

### C14 额外绑定

- rule_review_scope_sha256
- constitution/policy/permission/contract/legal evidence hashes
- applicable-rule set/version
- AI behavior review scope（如适用）

继续使用现有 CC Task Ed25519 机制签发和绑定任务事实。

---

## 6. C14 Lite：宪法、法务与规则

C14 的固定职责按 Owner 最新基线定义为：

> **GO 宪法、权限边界、法律监管、合同合规及 AI 行为审查；持续跟踪规则变化、运营合规问题及整改闭环。**

C14 **不是第二个质量测试团队**。

### 6.1 C14 适用范围

当候选触及以下任一事项时，C14 进入适用状态：

- GO 宪法或权责边界
- 权限模型 / IAM / 高权限动作
- 数据使用、隐私或监管要求
- 合同、供应商或条款约束
- AI 行为边界、工具调用边界
- 资金/订单/用户权益相关规则约束
- Owner 已明确要求 C14 审查的其他规则域

若本轮候选没有触及上述范围，C14 可以输出：

```
NOT_APPLICABLE
```

但必须说明：

- candidate
- review scope
- 为什么不适用
- 所依据的规则版本

不得简单跳过而无记录。

### 6.2 C14 输入

允许读取：

- Frozen Candidate / Diff
- 相关设计/合同/规则文档
- GO 宪法及权限边界
- 相关 API / IAM / data-flow 变化
- 必要的静态分析和机器证据
- 已知运营/整改证据

不得继承：

- 实现 AI conversation/context
- 业务开发者的自我结论作为最终审查结论
- 历史候选的 PASS 自动迁移到新 SHA

### 6.3 C14 执行

- GitHub-hosted ephemeral runner
- fresh AI execution/context
- read-only reviewer profile
- structured output schema
- 不执行部署
- 原则上不需要完整 Docker/PostgreSQL 回归环境

如果某条规则确实需要机器事实，可运行**范围化的静态/规则检查**或读取 C13/CI 已产生的机器事实，但不得把这变成重复整套 C13 质量验收。

### 6.4 C14 输出

建议状态：

- `PASS_SCOPED`
- `FAIL`
- `BLOCKED`
- `NOT_APPLICABLE`

至少包含：

- candidate_sha / application_tree
- rule_review_scope_sha256
- applicable_rules / versions
- evidence digests
- github_run_id / run_attempt / workflow identity
- ai_provider / ai_model / ai_execution_id
- prompt_sha256 / input_sha256 / opinion_sha256
- findings
- blocking_issues
- remediation status
- verdict
- issued_at
- C14_ROOT

C14 的问题如果适用，必须在进入部署资格前闭合。

---

## 7. C13 Lite：独立质量验收

C13 的固定职责按 Owner 最新基线定义为：

> **开发成果独立验收、回归、安全与恢复验证、跨端旅程验收；持续开展运营质量抽验、故障修复复验及发布资格判断。**

C13 不承担被验收功能的开发，不能以开发者自测代替独立验收。

### 7.1 C13 Machine Test Job

该 job 可以执行 Candidate Code，但不得拥有：

- AI API key
- SSH deployment key
- CC/HK privileged credential
- Production credential

执行：

- checkout exact candidate SHA
- verify application tree
- disposable Docker sandbox
- PostgreSQL 18.4（如本轮范围需要）
- frozen quality test scope
- regression/security/recovery/journey checks
- JUnit / stdout / manifest / runtime observations
- SHA256 digest

测试完成后临时 runner/container/database 销毁。

**原 #241 已在 GitHub-hosted runner 证明 Docker + PostgreSQL 18.4 可以运行，这项能力正式归入 C13 Lite。**

### 7.2 C13 AI Review Job

该 job：

- 使用 fresh AI execution/context
- 有 C13 AI API credential
- 不执行 Candidate Code
- 只读 Frozen Source + Machine Evidence + 验收标准
- 不继承实现 AI 的 conversation/reasoning
- 不把 C14 的结论当作质量测试结论

如本轮 C14 适用，C13 可以读取一个**sealed prerequisite summary**：

```
C14 status
C14 scope
C14 issues_closed
C14_ROOT
```

但无需读取或继续 C14 的完整推理上下文。

### 7.3 C13 输出

至少包含：

- candidate_sha / application_tree
- quality_test_scope_sha256
- github_run_id / run_attempt / workflow identity
- ai_provider / ai_model / ai_execution_id
- prompt_sha256 / input_sha256 / opinion_sha256
- junit_sha256 / stdout_sha256 / manifest_sha256
- quality findings / remaining risks
- verdict: `PASS_SCOPED / FAIL / BLOCKED`
- issued_at
- C13_ROOT

---

## 8. 业务开发、C14、C13 的正式顺序

按 Owner 最新流程：

```
业务团队开发 / 自测
        |
        v
相关 C14 规则/合规审查
        |
   如有问题 -> 业务团队整改
        |
        v
C14 对最终候选形成 sealed PASS / NOT_APPLICABLE
        |
        v
C13 对同一最终候选进行独立质量验收
        |
        v
CC 形成部署方案
        |
        v
调度中心派香港执行器做部署前检查
        |
        v
真人明确授权
        |
        v
香港执行器部署 / 健康检查 / 回传证据
```

### 候选一致性要求

如果 C14 审查后发生代码/配置/规则影响范围内的修改：

> C14 最终 closure 和 C13 quality acceptance 必须重新绑定**修改后的同一候选 SHA**。

不能拿旧候选的 C14 PASS 给新候选使用。

---

## 9. GitHub Run Identity

### V1 必选

不新增外部服务。

CC 与 HK 可分别使用 GitHub API 只读复核：

- run_id
- repository / workflow / SHA
- status/conclusion
- artifact ID/digest
- run_attempt

并与 C13/C14 bundle 逐项匹配。

### V1.1 可选增强

真实 PoC 通过后，可增加 GitHub OIDC：

- `id-token: write`
- custom `aud`
- repo/workflow/sha/run identity
- ephemeral public-key hash binding

OIDC 不作为 Lite V1 硬门槛。

不引入 Sigstore/Fulcio/Rekor。

---

## 10. Bundle 与 Root

C13 与 C14 分别生成职责不同的 canonical bundle：

```
C13_ROOT = SHA256(canonical C13 quality bundle)
C14_ROOT = SHA256(canonical C14 rule/compliance bundle)
```

两者都必须绑定：

- candidate
- scope
- GitHub run
- AI execution
- evidence digests
- verdict
- timestamp

但两者的 evidence 类型不同：

- C13：质量测试/回归/运行证据
- C14：宪法/权限/法律/监管/合同/AI 行为规则证据

---

## 11. CC 改造

CC 不跑 AI、不跑 Docker、不跑 PostgreSQL。

增加：

### ReviewVerifier

分别验证：

- C13 quality bundle
- C14 rule/compliance bundle
- candidate consistency
- GitHub run/artifact readback
- execution independence
- evidence digests

### WitnessLedger

保存 first-seen、no-overwrite 的 C13/C14/FINAL witness 记录。

### FinalAcceptanceAggregator

建议：

```
FINAL_ROOT = SHA256(
  candidate_sha
  || application_tree
  || C13_ROOT
  || C14_ROOT_or_NA_record
)
```

其中：

- C14 适用：必须绑定 C14_ROOT
- C14 不适用：必须绑定 sealed `NOT_APPLICABLE` record，而不是空值

### CC witness key

建议独立 Ed25519 witness key。

不需要：

- HSM
- KMS
- WIF
- P-256 receipt
- Docker
- PostgreSQL
- ECS 扩容

---

## 12. HK 改造与原职责保持

HK 现有职责不被 Lite 取代：

- 正式派发现场任务
- 部署前检查
- 部署执行
- 停止/回滚/恢复
- 健康检查
- 关键业务验证
- 回传证据

部署前检查覆盖：

- 版本一致性
- 环境配置
- 资源与依赖
- 数据库迁移条件
- 备份恢复
- 停止条件

**不重复整套 C13 业务验收。**

Lite 仅可额外增加 lightweight witness：

```
read sealed review bundles
+ GitHub API readback
+ recompute hashes
+ sign witness
+ persist first-seen record
```

目标：

`#245_TOUCHED=NO`

HK witness 不等于 C13 或 C14，不改变团队责任归属。

---

## 13. Deployment Eligibility

最终部署资格不再简单写成“C13 PASS + C14 PASS”一刀切。

正式逻辑：

```
C13 = PASS_SCOPED
AND
(
  C14 = PASS_SCOPED
  OR C14 = NOT_APPLICABLE with sealed scope/basis
)
AND
candidate/root/evidence valid
    -> DEPLOYMENT_ELIGIBLE
```

以下情况不可进入部署资格：

- C13 FAIL / BLOCKED
- C14 FAIL / BLOCKED
- C14 applicable issue 未闭合
- C13/C14 绑定的 candidate 不同
- Evidence/run/hash/witness 无法验证

即使 `DEPLOYMENT_ELIGIBLE`：

```
authorizes_any_action = false
```

仍需真人通过 Command Center 对明确版本、环境和范围下达部署指令。

---

## 14. 持续运营

C13/C14 不是“一次发布完就结束”的临时 gate：

### C13

持续负责：

- 运营质量抽验
- 故障修复复验
- 回归复验
- 发布资格判断
- 受影响范围补验

### C14

持续负责：

- 规则变化跟踪
- 权限边界审查
- 法律监管变化
- 合同/供应商合规
- AI 行为规则问题
- 整改闭环

部署完成后责任不转移给香港或 C12。

---

## 15. 防篡改语义

本系统不宣称“文件永远不能被修改”。

它保证：

> **历史 C13/C14 结果一旦被修改，就无法继续通过 Root 重算、GitHub run/artifact readback 和 CC/HK 双见证冒充原始结果。**

安全目标仍为：

> **tamper-evident + dual-witness**

而不是构造 external independent authority。

---

## 16. Before -> After

| 模块 | 旧/当前方向 | Lite V2 |
|---|---|---|
| C13 | 独立质量验收概念正确，但 AI opinion 未真正跑通 | GitHub ephemeral machine test + fresh AI quality review |
| C14 | 曾被逐渐实现成“香港第二套运行验收/独立复测” | **宪法/权限/法律/监管/合同/AI 行为独立审查** |
| C14 Docker/PG | 曾被设计为专用 C14 runtime | **移除；质量 sandbox 归 C13** |
| AI 独立 | execution identity 不完整 | C13/C14 各自 fresh execution/context |
| HK | 一度被当成 C14 runtime 承载点 | 恢复为现场执行环境；Lite 仅可加轻量 witness |
| CC | Task/bridge/ledger | 增 review verifier + witness ledger + final aggregator |
| HSM/KMS/WIF | 曾为 C14 硬门槛 | 从 Lite 主链移除 |
| 新 ECS | 曾拟为 C14 购买 | 不需要 |
| 成本 | 常驻 C14 基础设施 + AI | GitHub/AI 按需执行 |

---

## 17. 实施责任

### 陈震曦 + WorkBuddy：GitHub

- C14 rule/compliance workflow
- C13 quality acceptance workflow
- 复用旧 AI reviewer prompt/output-schema/codex-action 形态
- 参数化 candidate/scope
- bundle/root/schema
- run/artifact readback metadata
- execution independence
- CI / PoC

### 陈震曦 + WorkBuddy：CC

- ReviewVerifier
- WitnessLedger
- FinalAcceptanceAggregator
- CC witness key
- dry-run/readback/integration

### 陈震曦 + WorkBuddy：HK

- 可选 lightweight AcceptanceWitness
- HK witness key / ledger
- 保证 #245 不变
- 不改变现有香港部署执行职责

### Owner

- C01–C14 职责与业务规则
- API 额度/账号级资源
- 必要 repo Settings 权限
- 最终 merge / deployment decision

### Owner GPT

- 阅读本 PR
- 向 Owner 做白话解释

不负责重新设计或施工。

---

## 18. 实施前工程验证

1. AI API 当前额度可用
2. C14 rule/compliance workflow 可正式派发
3. C13 quality workflow 可正式派发
4. 两边 fresh AI execution/context 可记录
5. C14 最终状态与 Candidate SHA 可绑定
6. C13 Machine Evidence + AI opinion 可绑定
7. GitHub API run/artifact readback
8. CC/HK witness PoC
9. 如启用 OIDC，再单独做真实 `id-token: write` PoC

---

## 19. 最终一句话

> **C13 按 Owner 定义承担独立质量验收，C14 按 Owner 定义承担宪法、权限、法律、监管、合同及 AI 行为规则审查；两者均使用 GitHub 按需临时 Runner 和彼此独立的 AI execution/context，对明确候选与证据形成 sealed opinion，再由现有 CC/HK 进行完整性见证；不新增常驻硬件，不再把 C14 误实现成第二套质量复测服务器。**
