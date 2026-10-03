# GO Full Audit — Boss GPT Handoff

**Date**: 2026-10-03
**Audience**: Boss GPT（产品候选与方案的产出方）
**Tone**: 技术、直接、不攻击。目的不是评判，而是让后续方案建立在**可验证的产品事实上**。
**Mode**: READ ONLY。本轮零 mutation。

---

## 0. 先给出本轮可核验的事实底座

| 项 | 值 | 核验方式 |
|---|---|---|
| GitHub main | `7e7aedd556eac986210f1a5474c7b31e04d37a29` | `git fetch` + `rev-parse` |
| HK-STAGING 现场镜像 | `sha256:01632507d0d3…` = `go-hk-test-pr:9f889acf…`（PR #376 head） | 8/8 业务服务 `docker inspect` 同值 |
| DB alembic | `0145_source_latest_index (head)` | 容器内 `alembic current` |
| DB tables | 564 | `information_schema.tables` |
| OpenAPI | 1065 paths / 1101 ops | `curl /openapi.json` |
| 路由（解析） | 1082 声明；`/internal/*` namespace = 710（65.6%）；含 `admin_principal` = 558（51.6%）；写 742 vs 读 340。**namespace ≠ admin-only** | 源码解析 |
| model / table | 563 / 564 | `db/models.py` |
| 前端 | 3 个 mount；consumer 5 入口 / supplier 10+62 / admin 62 | 源码 + 现场 |
| CI workflow | 34（约 6 个跑 pytest） | `.github/workflows/` |
| `RUNTIME_POINTER_DRIFT` | **YES（三处）** | 见主报告 §20 |

---

## 1. 哪些能力是真的资产（请在后续方案里当作前提，不要重造）

1. **酒店库**：`hotel_canonical_profile`（`slug` 唯一、事实来源分层）+ `hotel_content_source_snapshot`（带 `rights_status` + `payload_hash`）+ `hotel_contact_point`（渠道归一 + 唯一约束 + `do_not_contact`）+ `hotel_auto_page_version`（`page_hash` 唯一）。**有来源、有版本、有哈希、有发布状态。**
2. **酒店页面审核台**：`frontend/admin/hotel-direct-review.js` + `hotel_direct_submission_review`。含 `manifest_sha256`/`facts_sha256` 版本守卫与 `REVIEW_CHANGED` 竞态保护。**这是可复用的审核台模式。**
3. **媒体上传管道**：`hotel_partner_media_upload.py` 的工程形状（真实解码校验、像素上限、去重、原子写盘、revision 乐观并发、授权声明强制）。**复形状，不复"公开媒体"语义。**
4. **注册验证码管道**：`registration_verification.py`（单次使用 + 四维限流 + 重发竞态处理）。
5. **逐条条款同意记录**：`registration_decision`（`CONTRACT_ACCEPTED` / `NOTICE_ACKNOWLEDGED` / `DEFERRED` + versions + hashes + TTL）。
6. **认证/会话**：`auth_session`（MFA、CSRF hash）、`refresh_token`（轮换）、`identity_user.token_version`（会话撤销）。
6b. **反向证据（请一并记住）**：563 个 model 中 **560 个在应用源码中被引用**，1 个仅测试引用，**2 个孤儿**。
   ⇒ **GO 的主要问题不是"建了 500 张没人用的空表"**，而是"**大量表确实进入了 service/runtime，但它们服务的是不可达、非闭环或产品规则尚未完成的业务**"。
   ⇒ `ORPHAN_TABLE` 计数低 **≠** 数据库健康；判定标准是 `REACHABILITY`（真人可达路径）。
7. **通用案例容器 + 双签 + 审计**：`commercial_case`、`approval_request`、`audit_event`。
8. **房型映射 / Offer 合并 / 漂移**：`offer_merge_decision`、`offer_drift_state`、`offer_drift_event`、`room_external_identity`、`hotel_external_identity`、`property_mapping_candidate`。
9. **多品类订单运行时 + 幂等 + Outbox**：5 个 `*OrderRuntimeRow`、`idempotency`、`outbox`/`outbox_dead_letter`。
10. **C 端界面**：现场 `/go-app/` 是一个真的像样的商业旅行产品界面。

---

## 2. 哪些之前被错误当作"完成"

| 之前的样子 | 实际状态 | 证据 |
|---|---|---|
| 供应商入驻"已实现" | **死循环，不可达** | `decide_profile(APPROVE)` → `APPROVED_HOTEL_REGISTRATION_REQUIRED`；产生前置 registration 需已知 `hotel_id`；而获取 `hotel_id` 的界面被 `supplier_principal` 门禁挡在 `CONTRACT_ACTIVE` 之前。开发方测试必须 `s.add(...)` 直接插库。 |
| 供应商审核"有接口" | **无队列、无列表、无界面、绕过权限** | 前端对 `/internal/v1/supplier-onboarding/...` 引用 0；`admin_queues` 不含 onboarding；两端点用 `admin_principal`（只查 actor_type） |
| 变更管理"已建" | **只写不读** | `hotel_partner_change_request` 会写入 `SUBMITTED`，**全库无代码推进 state** |
| 合同管理 | **只是两个字符串** | `contract_ref` + `contract_version` 落在 JSON blob；全库无 supplier 合同模型 |
| 文件管理 | **无上传** | 4 个 `*_ref` 文本字段；0 `UploadFile` 路由；0 `input[type=file]` |
| C 端"能订房" | **详情页是夹具、供给与支付未接** | `GET /v1/consumer/hotels/hotel_test` → `GO Hotel`；`AOLUGUYA_REAL_INVENTORY/RATE/PAYMENT_CONFIGURED=false` |
| 安全"已治理" | **66 条无显式鉴权声明 → 分类后 35 条 `AUTH_REQUIRED`（25 条 `/internal/*`）；19 条按设计公开、5 条已机器签名、2 条已体内鉴权** | 现场 `GET /internal/v1/merge/drift` 200 返回真实业务数据；逐条表见 `UNAUTHENTICATED_ROUTE_CLASSIFICATION_20261003.md` |
| runtime "指针一致" | **三处 drift** | pointer=PR320 / 现场=PR376 / candidate=DEPTH48 pr52 |

---

## 3. 哪些产品规则根本没定义

后续任何方案**不得**默认这些已经决定。共 25 项（PM 专项 15 + 全项目 10）。最关键的 8 项：

| # | 待决问题 | 为什么它决定表结构 |
|---|---|---|
| D-1 | **Supplier 代表什么**（公司 / 酒店 / 经营方 / 账号容器） | 决定 `supplier` 与 `legal_entity` 是否存在 |
| D-2 | **账号 ↔ 供应商的基数**（多酒店？多员工？多集团？） | 决定 `identity_user.supplier_id` 是否必须拆成关系表 |
| D-3 | **酒店身份用什么匹配**（名称/别名/地址/经纬度/电话/OTA ID/USCC） | 决定 `hotel_alias` 与判重算法 |
| D-4 | **认领规则**（谁能认领、依据、已认领怎么办、双人认领怎么裁） | 决定 `hotel_claim` / `ownership_dispute` |
| D-8 | **合同怎么产生与签署**（模板？电子签？线下？属于谁？多店共签？） | 决定 `contract` / `contract_version` |
| D-7 | **证件与合同的隐私模型**（谁能看、留多久、注销后怎么处理、要不要加密） | 决定 `document` / `document_version` / retention |
| D-10 | **审核组织模型**（谁审、几级、主体与合同是否分离、SLA） | 决定 `review` / `review_finding` / assignment |
| **D-15** | **`SUPPLIER LEGAL-ENTITY VERIFICATION` 与 `HOTEL RELATIONSHIP / CLAIM VERIFICATION` 的阶段边界**：创建账号需要什么 / 主体认证在哪一步 / 酒店搜索·匹配·认领在哪一步 / 酒店关系审核在哪一步 / 两者彼此前置关系 / 什么条件最终解锁经营后台。**不是"先建库 vs 先认证"的二选一**（含 3 个 PM decision options） | **决定整条 B 端链路能否解开（当前 cyclic precondition 的根因）** |

---

## 4. 哪些 PR / 测试模式造成了"假完成感"

七种，全部有真实样例。**这是本轮最重要的交接内容。**

| # | 模式 | 真实样例 |
|---|---|---|
| 1 | `TABLE EXISTS → 功能完成` | `hotel_partner_change_request` 有表有写入，state 永不推进 |
| 2 | `API EXISTS → 功能完成` | `profile-decision` / `contract-decision` 存在，但无队列无界面且结构上批不了；另：**约 75% 后端路由无前端调用方**（这是 `INVESTIGATION_SIGNAL`，**不等于 ORPHAN**，见 §6A-A） |
| 3 | `STATE EXISTS → 流程完成` | `supplier_onboarding_state.py` 有 10 状态，前端未穷举 ⇒ `CONTRACT_PENDING` 死路 |
| 4 | `TEST PASSES → 产品完成` | `test_supplier_onboarding_hk_unified.py` 全绿，**自己 SQL 插数据**；测试名 `requires_existing_hotel_truth_and_contract` 自证 |
| 5 | `EVIDENCE EXISTS → 业务验收完成` | `hotel_page_production_acceptance.py:306` 用**合成 supplier** `rc13-supplier-{batch}` 跑注册审批；且跑完 `delete(HotelRegistrationDirectRow)` 抹掉 |
| 6 | `CI GREEN → 用户可用` | 34 个 workflow 中 ~28 个是 canonical/receipt/admission/VERIFY（验证**交付链**），仅 ~6 个跑测试 |
| 7 | `PR MERGED / RUNTIME DEPLOYED → 产品正确` | 三处指针互不一致（见 §0） |

**统计佐证**：399 个测试文件中有 **83 个直接向 DB INSERT**；498 处 `.add()` / `SessionLocal.begin()`。这些测试证明的是**前置条件被正确断言**，不是**真人可以走通**。

---

## 5. 新的 DONE DEFINITION（请在此后所有方案中采用）

> ### 一个业务功能，只有**同时**满足以下 10 项，才允许称为 `PRODUCT_DONE`：
>
> | # | 条件 | 判定方式 |
> |---|---|---|
> | 1 | **PRODUCT RULE DEFINED** | 该功能的业务规则已被明确写出（谁、在什么条件下、结果是什么），且不以"实现如此"代替规则 |
> | 2 | **DATA MODEL** | 有承载该业务事实的对象（不是 JSON blob 里的一个 key） |
> | 3 | **SUCCESS PATH** | 真人（或系统）从入口到成功结果的完整路径可达 |
> | 4 | **FAILURE PATH** | 失败时给出**可理解的原因**，且原因与实际原因一致 |
> | 5 | **USER UI** | 用户侧有可操作界面 |
> | 6 | **OPERATOR UI（如需要）** | 需要人工处理的地方有工作台 + 队列 |
> | 7 | **RECOVERY** | 出错后用户或运营能自行恢复 |
> | 8 | **NOTIFICATION（如需要）** | 关键状态变化会主动告知相关方 |
> | 9 | **REAL JOURNEY TEST** | 有一条**不插入数据库、不使用合成主体**的端到端测试 |
> | 10 | **RUNTIME ACCEPTANCE** | 在真实运行环境上被验收过 |
>
> ### 否则必须分别标记为：
>
> | 标记 | 含义 |
> |---|---|
> | `DESIGN_ONLY` | 只有设计/文档，没有实现 |
> | `BACKEND_ONLY` | 有 service/API/表，但没有真人使用入口 |
> | `UI_ONLY` | 有界面，但后台能力不存在 |
> | `TECHNICAL_PROTOTYPE` | 技术骨架能跑，业务事实不完整 |
> | `DELIVERY_ONLY` | 只有交付/部署正确性，与产品正确性无关 |
> | `CONTROL_ONLY` | 治理能力自洽，但不产生面向用户/运营的产品结果 |
> | `WRITE_ONLY` | 可提交，但没有任何人处理 |
> | `TEST_ONLY` | 只能由测试构造的状态/路径 |

### 对每个新提交的方案的强制自检（请写在方案里）

```
PRODUCT_RULE:       <规则原文，或写 UNDEFINED>
REAL_JOURNEY_TEST:  <引用一条不插库的真实端到端测试；没有就写 NONE>
OPERATOR_UI:        <需要人工处理时的入口；不需要就写 NOT_REQUIRED 并说明>
FAILURE_REASON:     <失败时用户看到什么；与真实原因是否一致>
DONE_LABEL:         PRODUCT_DONE | DESIGN_ONLY | BACKEND_ONLY | UI_ONLY |
                    TECHNICAL_PROTOTYPE | DELIVERY_ONLY | CONTROL_ONLY |
                    WRITE_ONLY | TEST_ONLY
```

**若 `PRODUCT_RULE: UNDEFINED`，该方案不得进入 schema 设计阶段** —— 先出规则。

---

## 6. 以后任何功能必须从"真人 journey"开始

**新的方案模板（顺序不可颠倒）：**

```
1. PERSONA          —— 谁（具体到岗位）
2. JOB TO BE DONE   —— 他要完成什么
3. START → STEPS → SUCCESS
                    —— 真人能看见的每一步
4. FAILURE → REASON → RECOVERY
                    —— 出错时他看到什么、能不能自己恢复
5. OPERATOR         —— 需要人工吗？在哪工作？队列在哪？
6. BUSINESS OBJECT  —— 业务事实存在哪个对象里
7. STATE            —— 状态与转移（每个状态都要有用户可见的下一步）
8. RULE             —— 规则（不是实现）
9. DATA MODEL       —— 前面都定了才建
10. RUNTIME ACCEPTANCE
```

**禁止的顺序**（当前大量 PR 采用的就是这个顺序）：

```
表 → API → state → 测试 → Evidence → CI 绿 → 认为完成
```

---

## 6A. 本轮新增的两条判定规则（请并入 DONE DEFINITION 的判据）

### A. `NO_FRONTEND_CALLER != ORPHAN`

统计显示约 75% 的后端路由没有前端调用方 —— 这是 **`INVESTIGATION_SIGNAL`**，**不是**"75% 的 API 是废物"。

无前端调用方**可以**来自：worker、webhook、机器对机器回调、自动化、外部集成、内部 service 动作。

只有**同时**满足以下五项，才允许判定 `ORPHAN`：

```
no frontend caller
+ no worker caller
+ no machine caller
+ no external integration caller
+ no test/runtime product path
```

佐证：worker 模块对 model class 的直接引用计数为 **0**（全部经 service 层），说明"用代码引用关系推断调用关系"本身不可靠 —— 因此该统计只能作信号，不能作结论。

### B. 每一项 `SECURITY_CONTROL` 必须回答 `REAL_FAILURE_PREVENTED = ?`

- 写不出具体故障 ⇒ 写 **`NONE`** ⇒ **不加这个控制**。
- 该规则**对称适用**：既用于阻止"过度治理"，也用于阻止"什么都不做"。
  - 若某控制回答不出真实故障（例：为不存在的对象建留存期/跨境门禁）⇒ 不加。
  - 若某缺口对应**真实且正在发生**的故障（例：35 条应锁未锁的接口、匿名可写评价、匿名可创建预占）⇒ **必须补**，不得以"避免过度治理"为由跳过。

**避免从一种极端走到另一种极端**：本项目此前的偏差是"治理过度"；本轮更正口径后，**不得**反转为"安全什么都不用做"。判据只有 `REAL_FAILURE_PREVENTED`。

---

## 7. 不得再用"存在性"替代产品闭环",

**请在本轮之后，对所有"GO 已完成 X"的表述，要求同时给出：**

| 必须回答 | 不合格的回答 |
|---|---|
| 哪个**真人**能走完？ | "接口已经实现" |
| **在哪**走完？ | "有对应的表" |
| **失败了看到什么**？ | "测试通过了" |
| **谁处理**（如需要人工）？ | "Evidence 已归档" |
| **怎么恢复**？ | "CI 是绿的" |
| **有没有通知**？ | "已经合并到 main" |
| **有没有不插库的端到端测试**？ | "部署 VERIFY_OK" |

**任何一条答不出来，就不算完成，只能按 §5 的标记归档。**

---

## 8. 本轮最需要 Boss GPT 配合的三件事

1. **D-15 的决断**：定义 **`SUPPLIER LEGAL-ENTITY VERIFICATION` 与 `HOTEL RELATIONSHIP / CLAIM VERIFICATION` 的阶段边界** —— 各自是什么业务事实、在入驻的哪一步发生、彼此前置关系如何、最终什么条件解锁经营后台。**这一条不定，B 端整条链路无法推进。**（当前设计同时要求两者，形成 cyclic precondition。**注意：这不是"先建库后认证 vs 先认证后建库"的二选一，而是把两个阶段的先后关系定义清楚。** 完整表述与 3 个 PM decision options 见 `GO_FULL_AUDIT_ERRATA_20261003.md` E-6。）
2. **不要为未决规则出 schema 方案**：`hotel_claim` / `hotel_alias` / `contract` / `document` / `legal_entity` / `membership` / `notification` 这 7 类，规则未定前出表结构会绑定错误决定。
3. **把"运营工作台"当作一等交付物**：入驻审核、酒店认领、合同审核都需要运营界面。当前 62 项运营导航里有 30 项治理，**入驻审核 0 项**。

---

## 9. 明确的边界说明（避免误读）

- 本轮**没有**主张"GO 全是问题"。§1 列出的 10 项是真资产，其中酒店库与审核台的质量高于多数同类系统。
- 本轮**没有**主张"治理没有价值"。`audit_event` / `approval_request` / 条款决策 / 验证码管道都是有价值的基础设施。
- 本轮唯一主张是：**工程能力被投在了不产生产品结果的地方，而用户必须走通的那条链路是断的；并且缺少一个"完成"的定义，导致前者被误读为后者。**
- 所有结论均可核验；凡证据不足处一律标 `UNKNOWN`，未做补齐。
