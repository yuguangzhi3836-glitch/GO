# GO Supplier Onboarding — PM / 产品定义完整性审计

**Task**: GO Supplier Onboarding — PM / 产品定义完整性审计
**Date**: 2026-10-03
**Role**: 酒店 B 端平台产品负责人（PM），不是开发者 / 审核者 / 安全审计者
**Repo**: `yuguangzhi3836-glitch/GO`
**Candidate under audit**: PR #376 HEAD `9f889acfcd36a82c7565b723261ee046c2615314`（OPEN / Draft / 未合并）
**main**: `7e7aedd556eac986210f1a5474c7b31e04d37a29`
**上轮报告**: `GO_SUPPLIER_PRODUCT_AUDIT_20261003.md`（NOT_PRODUCT_READY，P0=2 / P1=7 / P2=9 / P3=4）
**Method**: 纯只读。复用上轮已证明的 `LIVE_BYTES == PR376_SOURCE`（9/9 sha256 全等），本轮全部结论来自源码、模型定义、路由表与现有测试的静态阅读。**零远端 mutation。**

> 本轮与上轮的关系：上轮问「用户能不能走完」；本轮问「GO 有没有把这件事设计成一个产品」。上轮发现的 UI 问题，本轮多数会被追到产品规则缺失这一层。

---

## 1. Executive PM Verdict

### 一句话

**GO 没有一个「供应商入驻」产品。它有一个「账号 + 一个状态枚举」，旁边停着一套真正产品级的酒店库/媒体/审核系统，两套东西从来没有接上。**

### Verdict

> ## `TECHNICAL_PROTOTYPE`（技术原型），不是「半成品」

「半成品」意味着部件的形状是对的、只是没做完。这里不是。这里的问题是：**一个真实酒店成为平台合作伙伴所需要的大部分业务事实，在 GO 里根本没有被定义过**，因此也没有数据模型、没有前台入口、没有后台处理、没有异常闭环。与之形成刺眼对比的是隔壁的酒店库系统 —— 那一套有 canonical 实体、有来源快照、有原图授权、有审核工作台、有发布门禁、有回滚。**投入的工程能力是真实的，只是没有投在这一条链路上。**

### 三个决定性事实（每条都已验证，详见 §5–§9）

**① 入驻流程是一个封闭死循环，没有任何出口。**（`DEADLOCK-01`）

- 审批主体资料（`decide_profile(APPROVE)`）**强制要求**一个已 APPROVED 的 `HotelRegistrationDirectRow`，且其 canonical hotel 的 `go_direct_state ∈ {GO_DIRECT_VERIFIED, GO_DIRECT_LIVE}` —— 否则 `APPROVED_HOTEL_REGISTRATION_REQUIRED`。
- 要产生这条 registration，必须调 `POST /v1/supplier/hotels/{hotel_id}/go-direct-registration` —— 需要**已知一个 canonical `hotel_id`**。
- 供应商**唯一能看到自己 `hotel_id` 的地方**是 `#/property` 与 `#/hotel-webpage` —— 但它们调用的 `/v1/supplier/*` 全部被 `supplier_principal` 门禁拦截，在 `CONTRACT_ACTIVE` 之前一律 `403 SUPPLIER_ONBOARDING_INCOMPLETE`。
- 而 `CONTRACT_ACTIVE` 正是要靠这次审批才能到达。

  **⇒ 每一个出口都通向自己。** 唯一走得通的方式是**运维人员脱离系统**把 canonical `hotel_id` 告诉供应商，供应商再**手工调一个没有任何界面的接口**。
  佐证：开发方自己的测试 `test_supplier_onboarding_requires_existing_hotel_truth_and_contract` 不得不**直接用 SQL 插入** `HotelCanonicalProfileRow(go_direct_state='GO_DIRECT_VERIFIED')` 和 `HotelRegistrationDirectRow(state='APPROVED')` 才能跑通审批。测试名字本身就是承认。

**② 审核员没有工作台，也没有队列 —— 连后端都没有。**（`NO-REVIEW-QUEUE`）

- 全前端对 `/internal/v1/supplier-onboarding/...` 的引用数 = **0**。
- 后端只有 2 个**动作**端点（`profile-decision` / `contract-decision`），需要调用者**事先知道 `supplier_id`**；**没有任何列表/队列端点**能回答「现在有哪些待审申请」。
- `/internal/v1/admin/queues`（管理端「异常队列」）的 7 个队列是 `payment_reconciliation / external_recovery / refund_failures / supplier_liability / risk_review / connector_health / outbox_dead_or_retry` —— **没有 onboarding**。
- `CommercialCaseRow` 有 `sla_due_at` 字段，但入驻路径**从不赋值**（`register_account` 写 `sla_due_at=None`），`owner_id` 存的是**申请人自己**的 `user_id`，不是审核员。
- 结论标记：**`BACKEND_CAPABILITY_WITHOUT_PRODUCT`**，而且比这个更弱 —— **连能力都不完整**（无队列、无列表、无分配）。
  对比：隔壁 `hotel-direct-review.js` 是一个**完整可用的审核台**（酒店身份对照、房型映射、原图授权、冲突文案、哈希守卫的 approve/publish/revoke）。同一份代码库里，酒店图片有审核台，供应商入驻没有。

**③ 真正需要的领域对象，基本都不存在。**（§13）

| 现实业务事实 | GO 里有什么 |
|---|---|
| 酒店改名 / 换牌 / 摘牌 | ❌ 无别名表、无名称历史（`TravelEntityAliasRow` 属旅游实体，非酒店） |
| 谁认领了这家酒店 | ❌ 无 claim 对象（现有 5 个 `*Claim*` 模型全属其它域） |
| 一家酒店多个员工 | ❌ 无 membership 表；`IdentityUserRow.supplier_id` 是**单值列** ⇒ 一人一供应商，结构上排除了多酒店/多集团 |
| 换经营主体 / 换地址 / 更新营业执照 | ⚠️ `HotelPartnerChangeRequestRow` 有 `HIGH_RISK={LEGAL,ADDRESS,BRAND,QUALIFICATION}` 定义了字段组，但**全代码库没有任何地方把它的 state 改成 APPROVED/REJECTED** ⇒ 变更申请是**只写不读的死队列** |
| 营业执照 / 身份证 / 合同 的实体文件 | ❌ 四个 `*_ref` 字符串字段；无文档对象、无版本、无保留期 |
| 合同（生成/版本/到期/续签/签署） | ❌ 无 supplier 合同模型；只有 `contract_ref`（必填字符串）+`contract_version`（可选字符串） |
| 统一社会信用代码 / 执照有效期 / 注册地址 | ❌ 完全不采集（`SupplierProfileBody` 无这些字段；registry 里那个 USCC 是**平台自己**的） |
| 任何入驻通知（邮件/站内信/短信） | ❌ 无 supplier 通知模型；状态迁移只写 `AuditEventRow`，不写 outbox、不发信 ⇒ 用户只能靠反复登录猜结果 |

### 关于 CONTROL_AHEAD_OF_PRODUCT

任务要求独立判断。我的结论是：

> **`CONTROL_AHEAD_OF_PRODUCT` = YES，且程度严重。**

证据不是「代码多」，而是**分布**：管理端一级导航**实测 62 项**（`application/frontend/admin/config.js`，`grep -o "label:'[^']*'"` 计数），其中**第 11–40 项连续 30 项**全是「恢复控制 / 恢复实验 / 恢复学习 / 恢复数据治理 / 学习事件控制 / 恢复发布治理 / 运行时发布安全 / 运行遥测治理 / 运行遥测可信 / 运行身份生命周期 / 运行身份重签发 / 凭证授权 / 联邦信任执行 / 外部信任与多地域 / 信任传播与恢复 / 信任平面独立与容灾 / 信任混沌与就绪 / 持续混沌与豁免 / 豁免暴露与技术债 / 异常债务清理 / 企业风险组合 / 企业风险偏好 / 企业风险预测 / 预测校准与准确性 / 预测模型主备治理 / 预测统计晋级 / 预测漂移与刷新 / 预测训练与可复现 / 预测制品供应链 / 预测服务证明」，**而「供应商入驻审核」一项都没有**（最接近的只有第 55 项「供应商管理」= 只读 registry 表）。

同一份代码库里：`identity_user` 只有 15 个字段、`CommercialCaseRow` 把整条入驻业务塞进两个 JSON blob；而 `models.py` 有 **583,862 字节**、**700+ 张表**。

这不是"安全做得太严"，是**产品侧没有定义，所以工程把能力投到了不需要产品定义的地方**。`approval_request` / `audit_event` / 双签 / 哈希 / 保留期这些是有价值的（见 §15），但它们**解决的是"已经存在的东西别出错"，而当前阶段的问题是"那个东西还不存在"**。

---

## 2. What product are we actually building?

从代码能反推出的产品意图，只有一个**半句话**：

> 「酒店可以自己注册一个 GO 合作伙伴账号，提交主体与酒店资料，等 GO 人工审核，通过后签合同，然后进入经营后台。」

这句话在代码里被实现成了：**一个 12 字段表单 + 一个 10 值状态枚举 + 两个需要知道 `supplier_id` 的审批 POST**。

而现实业务需要的是一整套对象（酒店、经营主体、申请、资料、审核、合同、通知、关系、变更），这些对象 GO 里**要么没有、要么是 JSON blob 里的一个 key、要么是只写不读的孤儿表**。

**更值得注意的**：代码里存在一条**完全不同、且更像产品**的路 —— 酒店库（hotel-autopage）：

```
HotelCanonicalProfileRow（canonical 酒店，slug 唯一，canonical_json 存全部事实，go_direct_state）
  ↑ HotelContentSourceSnapshotRow（来源快照，带 hash 与 rights_status）
  ↓ HotelContactPointRow（联系方式，按渠道归一 + 去重约束 + do_not_contact + 营销资格）
  ↓ HotelAutoPageVersionRow（页面版本，带 page_hash 唯一）
  ↓ HotelRegistrationDirectRow（酒店 ↔ 供应商 GO Direct 注册，SUBMITTED→APPROVED）
  ↓ 管理端 hotel-page-factory / hotel-direct-review 工作台（含原图授权、房型映射、发布门禁）
```

这条线有来源、有版本、有授权、有审核、有发布、有回滚。**它才是 GO 真正的"酒店接入"产品。** 而「供应商入驻」这条线**没有跟它连上**（见 `DEADLOCK-01`）—— 两套系统各自成立，中间缺一件东西：**"这家酒店由这家供应商代表"的确认动作**。

所以严格回答"我们在建什么产品"：

- **已建成（且质量真实）**：全国酒店数字基础设施（建库 / 页面 / 图片授权 / 发布审核）。
- **未建成**：供应商关系建立（身份 → 主体 → 酒店认领 → 合同 → 开通）。
- **当前实际交付给酒店的**：一个注册表单。

---

## 3. Personas

| Persona | 现实里他要做的事 | GO 里他能做什么 | 判定 |
|---|---|---|---|
| **A1 酒店老板 / 总经理** | 授权某人代表酒店注册；签合同 | 能注册；**无法上传执照**（无上传）；**看不到自己在第几步** | `MISSING` |
| **A2 收益经理 / 电商经理 / 前厅经理**（最可能的实际操作者） | 被老板叫来"上去注册一下" | 能填表；被要求填「营业执照资料引用」「法定代表人姓名」——**他通常没有执照原件、也不知道法人姓名**；没有"我不知道/由主体负责人补"的路径 | `CONTRADICTORY`（要求超出角色权限） |
| **A3 销售** | 提供联系人/电话/地址 | 可填；手机号无任何用途（无短信、不验证、模型里没有 phone 列） | `MISSING` |
| **A4 IT** | 可能负责对接、后续账号管理 | **无法给同事开第二个账号**（无成员/邀请机制） | `MISSING` |
| **A5 集团总部人员** | 一次注册覆盖 N 家酒店 | **结构上不可能**：`IdentityUserRow.supplier_id` 是单值列 ⇒ 一个账号只有一个供应商 | `MISSING` |
| **A6 第三方代运营** | 代表**多个不同业主**的酒店 | **结构上不可能**（同上）；且无代运营授权模型 | `MISSING` |
| **A7 已在平台上的酒店管理员** | 改名/换牌/换地址/换主体/更新执照/合同续签/终止合作 | 唯一的机制是 `HotelPartnerChangeRequestRow`，而它**永远停留在 SUBMITTED**（无任何代码把它置为 APPROVED/REJECTED） | `MISSING`（死队列） |
| **B GO 平台运营 / 审核员** | 收申请 → 看酒店与主体 → 看证明文件 → 判重 → 判是否已有经营方 → 请求补件 → 驳回/批准 → 处理争议认领 → 审合同 → 留痕 | **无队列、无列表端点、无审核台**；只有两个需要预先知道 `supplier_id` 的动作端点；证明文件**不存在**（只有字符串）；判重与认领**不存在**；合同**无对象** | `BACKEND_CAPABILITY_WITHOUT_PRODUCT`（且能力本身不完整） |

用户方的关键约束被违反得很彻底：

- "不能假设注册人一定是法人 / 一定知道所有主体资料 / 一定有营业执照原件" —— 表单**要求**法人姓名 + 执照引用。
- "不能假设一定只管理一家酒店" —— schema **假设**只管理一家。
- "不能假设一定知道合同签署权限" —— 合同步骤要求提供"已盖章合同资料引用"，且**没有说明谁可以签**。

---

## 4. End-to-end business journey

把现实业务事实与 GO 的实现逐格对齐（左＝现实需要发生的事实，右＝GO 现状）：

| # | 现实业务事实 | GO 实现 | 缺口性质 |
|---|---|---|---|
| 1 | 有人决定代表某家酒店加入 | 自由文本注册（`/bff/auth/supplier/register`） | 部分 |
| 2 | 平台确认这个人有权代表这家酒店 | ❌ 无授权模型、无代运营授权、无经办授权校验（`authorization_ref` 是可选字符串） | **规则未定义** |
| 3 | 平台识别"这家酒店"是哪一家 | ❌ 酒店名是自由文本，**从不与 canonical hotel 匹配** | **规则未定义** |
| 4 | 平台判重（是否已存在 / 已被认领） | ❌ 完全没有。唯一的唯一性检查是 email（`USERNAME_ALREADY_REGISTERED`） | **规则未定义** |
| 5 | 平台采集经营主体法定信息 | ⚠️ 只采 `organization_name` + `legal_representative_name`；**无 USCC、无注册地址、无执照有效期** | 部分 |
| 6 | 平台收证明文件 | ❌ 4 个文本字段，**无上传**（§8） | **能力缺失** |
| 7 | 提交 → 进入待审 | ✅ `UNDER_REVIEW` 写进 `CommercialCaseRow.payload_json` | 可用 |
| 8 | 审核员看到它 | ❌ 无队列、无列表、无界面 | **产品缺失** |
| 9 | 审核员请求补件（精确到哪一项） | ⚠️ 只有一个自由文本 `review_note`，**无 item-level finding** | 部分 |
| 10 | 审批通过 | ❌ **结构上不可达**（`DEADLOCK-01`） | **设计死锁** |
| 11 | 合同生成 / 发送 / 签署 / 归档 | ❌ 无对象。只有两个字符串 | **规则未定义** |
| 12 | 开通 | ✅ `CONTRACT_ACTIVE` 解锁 `/v1/supplier/*` | 可用 |
| 13 | 通知申请人每一步结果 | ❌ 零通知（§11） | **能力缺失** |
| 14 | 变更 / 续签 / 退出 | ❌ 死队列 + 无入口 | **能力缺失** |

**这张表就是本轮的结论**：第 1、7、12 格能工作；**第 2、3、4、6、8、10、11、13、14 格缺失或死锁**。而第 2/3/4/6/11 格属于"产品规则还没决定"，**任何数据库设计只要落在这些格子上，就是在把未决规则固化进 schema**。

---

## 5. Account & Identity

（逐项，按任务要求标记 `DEFINED / PARTIAL / MISSING / CONTRADICTORY`）

| # | 问题 | 现状 | 判定 |
|---|---|---|---|
| 1 | 什么是"账号"？ | `IdentityUserRow`：user_id / username / password_hash / actor_type / **supplier_id（单值）** / roles(JSON) / status / token_version + MFA/SSO 字段。**15 个字段，无 email 独立列、无 phone 列** | `PARTIAL` |
| 2 | Email 是否登录名？ | 是。`username` 存 email | `DEFINED` |
| 3 | Email 是否唯一？ | `username` 有 `unique=True` + `USERNAME_ALREADY_REGISTERED`（含 IntegrityError 竞态兜底） | `DEFINED` |
| 4 | 手机号是否唯一？ | **模型里没有 phone 列。**注册表单收 `phone`，写进 `CommercialCaseRow.payload_json.profile`（自由文本，可空，无唯一性、无归一） | `MISSING` |
| 5 | 手机号是否必须验证？ | 否。全流程唯一验证通道是 email 验证码；`registration_email` 只发验证码 | `MISSING` |
| 6 | 一个 Email 能否管理多家酒店？ | 不能。`supplier_id` 是单值列；一个 supplier 也**只能有一个 `HotelPartnerPropertyRow` 被关联**（`decide_profile` 只写一个 `hotel_id`） | `CONTRADICTORY`（与集团/多店现实冲突） |
| 7 | 一个酒店能否有多个员工账号？ | 不能。无 membership 表、无邀请端点 | `MISSING` |
| 8 | 一个账号能否属于多个 Supplier / 集团？ | 不能（单值列） | `MISSING` |
| 9 | 忘记密码怎么处理？ | **不存在任何找回密码路由**（`password-reset` / `forgot` / `reset-password` 全库 0 命中） | `MISSING` |
| 10 | Email 已存在时用户看到什么？ | 后端 `USERNAME_ALREADY_REGISTERED`；前端映射表无此项 ⇒ **原样显示** | `CONTRADICTORY`（文案与意图不符） |
| 11 | 手机已存在时可以透露多少信息？ | 不适用（无手机身份） | `MISSING` |
| 12 | 如何防账号枚举同时保证体验？ | 无策略。注册端点直接告知"已注册"，是**有意的可用性选择**，但没有任何产品化的引导（"去登录"/"找回密码"），而找回密码又不存在 | `PARTIAL`（半截） |
| 13 | 员工离职后账号如何交接？ | 无机制。存在 `HostedStaffRoleRow`（酒店前台托管域）与 `HostedShiftHandoverRow`（交班），但**都不属于供应商域** | `MISSING` |
| 14 | 管理员怎么邀请第二个用户？ | 无端点、无界面 | `MISSING` |

**PM 判断**：`identity_user` 这张表**只能表达"一个人 = 一个供应商 = 一家酒店"**。这是**产品规则被写死在 schema 里**的典型 —— 而且写进的是一个大概率错误的规则。**任何"多酒店/多员工/集团"的产品决定都会要求改这张表的结构（加关联表），不是加字段。**

---

## 6. Hotel identity / duplicate / claim / rename

### 6.1 现状

- **canonical hotel 是存在的**：`HotelCanonicalProfileRow(hotel_id PK, slug UNIQUE, canonical_json, field_provenance_json, completeness_bps, go_direct_state, page_state)`。
- **供应商与酒店的关系**存在，但是 `HotelRegistrationDirectRow(hotel_id, supplier_id, state, reviewed_by, ...)` —— 这是"GO Direct 注册"的**结果对象**，不是独立的"关系/认领"对象。它没有关系类型（业主？管理方？代运营？）、没有生效期、没有终止。
- **供应商自己的酒店声明**是另一个对象：`HotelPartnerPropertyRow(property_id, supplier_id, name_zh, name_en, group_name, brand_name, address_json, lat/lon, contacts_json, legal_json, ...)`。
- ⚠️ **ID 语义冲突**：`CommercialCaseRow.property_id` 在通过审批时被赋值为 **canonical `hotel_id`**（`supplier_onboarding_state.py:134`：`row.property_id = registration.hotel_id`），而 `HotelPartnerPropertyRow.property_id` 是**另一个 ID 空间**。**同一个列名在两个表里指两样东西。**

### 6.2 逐项

| # | 问题 | 现状 | 判定 |
|---|---|---|---|
| 1 | 用户输入酒店名后是否搜索已有酒店？ | **不搜索。**`hotel_name` 是裸 `required` 文本框，无 autocomplete、无建议、无匹配 | `MISSING` |
| 2 | 用什么匹配？ | 不适用。**平台侧也没有**：没有任何 supplier-onboarding 相关的匹配调用。（`GET /v1/hotel/search` 存在，但服务 consumer 搜索，与入驻无关） | `MISSING` |
| 3 | 找到疑似酒店后用户如何确认？ | 不适用 | `MISSING` |
| 4 | 已被别人认领怎么办？ | 无概念 | `MISSING` |
| 5 | 两人声称同一家酒店怎么办？ | 无概念。现有 5 个 `*Claim*` 模型（`VerticalCapacityClaimRow` / `CatalogCashFareClaimRow` / `TravelerClaimRow` / `PostStayDispute*`）**全部属于其它域** | `MISSING` |
| 6 | 酒店尚不存在怎么办？ | 不适用（不存在"新建 vs 认领"的分支） | `MISSING` |
| 7 | 酒店名称变更怎么办？ | 只有 `HotelPartnerPropertyRow.name_zh` 可改；改名走 `HIGH_RISK` 变更申请 ⇒ **死队列**（§6.3） | `MISSING` |
| 8 | 是否保留酒店名称历史？ | ❌ 无名称历史表。唯一近似物 `TravelEntityAliasRow` 属旅游实体域 | `MISSING` |
| 9 | 酒店实体 / 经营主体 / Supplier Account 是否被混成一个？ | **是，被混了。**`decide_profile` 把 `HotelRegistrationDirectRow.hotel_id` 直接写进 `CommercialCaseRow.property_id`，而供应商侧的 `HotelPartnerPropertyRow` 又是第三个身份。三者之间没有类型化的关系对象 | `CONTRADICTORY` |
| 10 | 一个经营主体能否经营多家酒店？ | 结构上不行（`supplier_id` 单值 + `decide_profile` 单 `hotel_id`） | `CONTRADICTORY` |
| 11 | 一家酒店能否发生经营主体变更？ | 无路径 | `MISSING` |

### 6.3 变更申请是"只写不读"的死队列（重要）

`hotel_partner_core.py:23`：`HIGH_RISK={'LEGAL','ADDRESS','BRAND','QUALIFICATION'}` —— **产品经理要的四类变更，词表定义得完全正确**。
`hotel_partner_core.py:268`：命中高风险字段时创建 `HotelPartnerChangeRequestRow(state='SUBMITTED')`。

**但全代码库搜索"把 `HotelPartnerChangeRequestRow.state` 改成 APPROVED/REJECTED"的结果为 0。** 唯一的 `change-requests/{id}/approve` 路由属于 `recovery/learning` 域（另一件事）。

⇒ 换牌、改名、换地址、换主体、更新资质：**提交后永久停在 SUBMITTED，没有任何人可以批准或驳回。** 这是"产品规则定义了、界面没有、审核面没有"的最纯粹样本。

### 6.4 `CONTROL_AHEAD_OF_PRODUCT` 的一个具体证明

`hotel_page_production_acceptance.py:306`：
```python
reg = hotel_autopage_factory_service.register_for_go_direct(
    target, f"rc13-supplier-{batch_id}", actor, {"evidence":[{"kind":"STAGING_ACCEPTANCE"}]})
decision = hotel_autopage_factory_service.decide_registration_direct(reg[...], actor, {"decision":"APPROVE"})
```
GO Direct 的"注册 → 审批 → 验证"链路是**用合成供应商 ID（`rc13-supplier-<batch>`）跑通的**。也就是说：**这条链路的验收从未遇到过一个真实的、走完注册流程的供应商。** 与之配套的是 `hotel_page_production_acceptance.py` 里还有 `delete(HotelRegistrationDirectRow)...` 的清理逻辑，说明验收是"跑完即抹掉"的。

---

## 7. Legal entity / organization model

| # | 问题 | 现状 | 判定 |
|---|---|---|---|
| 1 | Supplier 代表什么？ | **不明确。**`supplier_id` 同时被用来指"账号容器"（`IdentityUserRow`）、"酒店持有者"（`HotelPartnerPropertyRow`）、"GO Direct 注册方"（`HotelRegistrationDirectRow`）。**没有 legal entity 对象** | `CONTRADICTORY` |
| 2 | `organization_name` 与 `hotel_name` 的业务关系？ | **未定义。**注册表单两个都收（都必填），没有任何校验或说明二者关系；后端只是各自存进 `payload_json.profile` | `MISSING` |
| 3 | 是否采集 USCC / 法定代表人 / 企业注册地址 / 执照有效期 / 酒店经营地址？ | **法定代表人**：采集（`legal_representative_name`）。**USCC：不采集**。**企业注册地址：不采集**（只有酒店的 `street_address`）。**执照有效期：不采集**。**酒店经营地址**：采集（省/市/详细地址，自由文本）。⚠️ `registry.json` 里的 `unified_social_credit_code: null` 是**平台自己**的，不是供应商的 | `MISSING` ×4 |
| 4 | 营业执照变更怎么办？ | 无路径（只能走死队列） | `MISSING` |
| 5 | 一个主体多酒店怎么办？ | 不可能 | `MISSING` |
| 6 | 品牌方与实际经营方不同怎么办？ | 无模型（`HotelPartnerPropertyRow` 有 `brand_name`/`group_name` 字符串，但没有"品牌授权方 ≠ 经营方"的关系表达） | `MISSING` |
| 7 | 第三方管理公司注册怎么办？ | 无模型（无代运营授权、无委托关系） | `MISSING` |
| 8 | 总部集中签约、单店运营怎么办？ | 无模型 | `MISSING` |

**PM 判断**：`SupplierProfileBody` 一共 12 个字段，其中只有 2 个（`organization_name` / `legal_representative_name`）与"法律主体"有关，**且都不足以在法律上确定一个主体**（没有 USCC 就没有唯一性）。所以 `supplier` 这个概念**在领域层还是空的** —— 它是一个账号 ID，不是一个法律实体。

---

## 8. Document lifecycle

### 8.1 结论：所需文件类型全部无实现；但**一套高质量的文件管道已经存在，只是用错地方**

**所需文件类型（营业执照 / 身份证明 / 授权委托书 / 门头照片 / 经营证明 / 合同 / 补充协议）**：

| 文件 | 现状 |
|---|---|
| 营业执照 | `business_license_ref` —— **纯字符串**（`String`/Pydantic `str\|None`），必填 |
| 法人 / 经办人身份证明 | `identity_document_ref` —— 纯字符串，必填 |
| 门头照片 | `storefront_photo_ref` —— 纯字符串，必填 |
| 经办授权委托书 | `authorization_ref` —— 纯字符串，可选 |
| 已盖章合同 | `contract_ref` —— 纯字符串，必填 |
| 补充协议 / 其它证明 | 无字段 |

**全产品上传能力盘点**：

| 位置 | 是否有上传 |
|---|---|
| 供应商入驻 / 主体认证 / 合同 | ❌ 0 个 `input[type=file]`；0 条 `UploadFile` 路由 |
| 酒店营销图片（`/v1/supplier/properties/{id}/media-uploads`） | ✅ **有，而且做得很好** |

`hotel_partner_media_upload.py` 是一套**真正工程级**的文件管道：base64 收件 → `MAX_IMAGE_BYTES` 限制 → PIL `verify()` + `load()`（拒绝截断像素）→ DecompressionBomb 防护 → 40M 像素上限 → 格式白名单 `{JPEG, PNG, WEBP}` → 拒绝动图 → 最小分辨率 720×1280 → sha256 去重 → `.part` 临时文件 + `os.fsync` 原子落盘 → 基于 `revision` 的乐观并发 → 授权声明强制（`rights_holder` + `evidence_reference` + `usage_scope=['DISTRIBUTE_ON_GO']`）→ 发布需 `CANONICAL_PUBLICATION_REVIEW_REQUIRED`。

**但它同时说明三件事**：

1. **格式白名单里没有 PDF、没有 HEIC。**营业执照/合同扫描件、手机 HEIC 拍照**都无法通过**。
2. **`_authorize` 要求 `HotelPartnerPropertyRow` 属于该 supplier**，且路由挂在 `supplier_principal` 门禁后 ⇒ **入驻期间完全不可用**（入驻期间供应商没有任何 property，且门禁 403）。
3. **`ALLOWED_ROLES` 是图片角色**（HERO/GALLERY/ROOM）⇒ 语义上排除了"证件/合同"这类**非公开**文件。

> **PM 核心判断（对应任务里那句"身份证、营业执照、合同不能与酒店宣传照片按同一种公开媒体资产处理"）**：
> 现存媒体管道**恰恰是按公开宣传资产设计的** —— 它的产出物有 `original_url`（`/v1/supplier/properties/…/media-uploads/…/original`）、有"可发布"概念、进的是**同一个媒体索引**。
> 而营业执照、身份证、盖章合同是**受限文件**：不能公开访问、不能进 media index、访问应限于申请人 + 审核员、需要有保留期与删除规则。
> **因此：不能复用这条管道，只能复用它的工程形状。**（这既是 §16 的"不要重建"项，也是 §19 的 V2 必做项。）

### 8.2 逐项判断（任务列的 28 项）

| # | 项 | 现状 |
|---|---|---|
| 1 | 支持格式（JPG/JPEG/PNG/PDF/HEIC） | 仅 JPEG/PNG/WEBP；**PDF ❌、HEIC ❌** |
| 2 | 单文件大小限制 | ✅ 有（`MAX_IMAGE_BYTES`），但只对图片 |
| 3 | 文件数量限制 | ⚠️ 发布请求有 `0 < len <= 500`，上传本身无计数上限 |
| 4 | 多页 PDF | ❌ 不支持（无 PDF） |
| 5 | 手机拍照 | ⚠️ iOS 默认 HEIC ⇒ 直接失败 |
| 6 | 图片压缩 | ❌ 无（原图入库，仅校验尺寸下限） |
| 7 | EXIF 处理 | ❌ 无任何 EXIF 处理（**营业执照/身份证内嵌 GPS 不会被剥离**） |
| 8 | MIME 校验 | ✅ 不信任声明，靠 PIL 解码判定真实格式 |
| 9 | 扩展名伪造 | ✅ 天然免疫（不看扩展名） |
| 10 | 病毒/恶意文件 | ❌ 无（`PIL.verify()` 只挡"不是合法图片"） |
| 11 | 上传中断恢复 | ⚠️ 有 `.part` + `finally: unlink`，但**无断点续传**；base64 整包提交，大文件中断即重传 |
| 12 | 预览 | ✅ 有（`GET .../original`，且不主动下载） |
| 13 | 替换 | ⚠️ 通过"新 role 生成新 asset"实现，不是原地替换 |
| 14 | 删除 | ❌ 无删除端点 |
| 15 | 重新提交 | ⚠️ 可重新上传（新 asset_id） |
| 16 | 文件版本 | ⚠️ asset 有 `revision`（乐观并发用），但不是"用户可见的版本历史" |
| 17 | 审核员看到哪一个版本 | ⚠️ 审核台按 `manifest_sha256` + `facts_sha256` 锁定所见版本（**这点做得好**） |
| 18 | 旧版是否保留 | ✅ 保留（按 digest 命名，天然多版本共存） |
| 19 | 谁能访问 | ⚠️ `_owned_asset` 校验 supplier + property + source_type（**供应商侧**）；但媒体索引是**共享的** |
| 20 | 下载权限 | ⚠️ 同上；无"仅审核员可下载受限文件"的概念 |
| 21 | 存储位置 | ⚠️ 本地媒体缓存目录（`cache.files_dir`）+ 事务型 SQLite 元数据 |
| 22 | 静态文件是否公开可访问 | ⚠️ `original` 走鉴权端点（好）；但 `/v1/hotel-media/{asset_id}` 是**另一个不带供应商校验**的读取口 |
| 23 | at-rest 加密 | ❌ 无 |
| 24 | application-level encryption | ❌ 无（媒体按 digest 明文落盘） |
| 25 | backup | ❌ 无（对接手的媒体捕获流程而言） |
| 26 | retention | ❌ 无（媒体永久保留；**而 C14/registry 那侧对"留存期限"反复声明 UNKNOWN**） |
| 27 | 用户注销/合作终止后的处理 | ❌ 无 |
| 28 | audit log | ✅ 有（`MEDIA_DRAFT_BOUND` / `MEDIA_PUBLICATION_REQUESTED` 写入 `core._audit`） |

**PM 判断**：对**图片**而言，8-9-17-18-28 这几项做得好，值得保留。对**证件/合同**而言，**1-2-3-5-7-10-14-19-20-23-26-27 全部缺失，且其中多项属于必须先有产品规则（保留多久、谁能看、要不要加密）才能建表。**

> 任务里明确说"不要为了安全而过度设计"。我同意，并且反过来指出：**现在的问题不是"证件文件安全不够"，而是"证件文件根本不存在"**。先把文件收上来、能看能替换能审，再谈加密。同时**唯一一条现在就该守住的线**：受限文件**不能**进公开媒体索引、不能有公开 `original_url` —— 这一点如果按现状照抄媒体管道，会造成真实的信息暴露。

---

## 9. Admin review operations

模拟审核员的一天：

| # | 问题 | 现状 | 判定 |
|---|---|---|---|
| 1 | 新申请出现在哪里？ | **不出现。**无队列、无列表端点、无界面 | `MISSING` |
| 2 | 有没有"待审核队列"？ | ❌ 无。`/internal/v1/admin/queues` 的 7 个队列不含 onboarding | `MISSING` |
| 3 | 如何排序？ | 不适用（无队列）；`priority` 字段存在但注册时硬编码 `"MEDIUM"` | `MISSING` |
| 4 | 有没有申请时间？ | ✅ `CommercialCaseRow.created_at` / `payload_json.submitted_at` | `DEFINED` |
| 5 | 有没有 SLA？ | ❌ 字段存在（`sla_due_at`），入驻路径**从不赋值**；通用案例框架 `commercial_constitution.open_case` 会赋 SLA，但入驻不走它 | `CONTRADICTORY`（有字段无行为） |
| 6 | 审核员点进去看到什么？ | 不适用（无界面）。**API 也看不到**：没有 GET 详情端点（只有 `GET /bff/supplier/onboarding`，是**申请人自己**看的，走 `supplier_account_principal`） | `MISSING` |
| 7a | 能看到账号信息？ | ❌ 无审核侧视图 | `MISSING` |
| 7b | 能看到企业主体？ | ⚠️ 只有 API 返回的 JSON blob（需自建工具） | `MISSING` |
| 7c | 能看到酒店信息？ | ⚠️ 同上，且**与 canonical hotel 无关联** | `MISSING` |
| 7d | 能看到上传资料？ | ❌ 资料不存在 | `MISSING` |
| 7e | 能看到历史操作？ | ⚠️ `AuditEventRow` 有（`SUPPLIER_REGISTRATION_TERMS_ACCEPTED`），但无审核侧视图 | `PARTIAL` |
| 7f | 能看到重复匹配结果？ | ❌ 不判重 | `MISSING` |
| 7g | 能看到酒店当前认领状态？ | ❌ 无认领概念 | `MISSING` |
| 8 | 如何批准？ | `POST /internal/v1/supplier-onboarding/{supplier_id}/profile-decision`，需**预知 supplier_id** + **预知 registration_direct_id**，且只在注册已 APPROVED 时成功 | `PARTIAL`（且见 `DEADLOCK-01`） |
| 9 | 如何退回？ | 同一端点 `decision='NEEDS_CHANGES'` | `DEFINED` |
| 10 | 是否必须填写退回原因？ | ❌ 不必须。`note: str\|None = None` | `MISSING` |
| 11 | 能否精确标记"哪一项需要修改"？ | ❌ 只有一个自由文本 `review_note`，**无 item-level finding** | `MISSING` |
| 12 | 用户修改后审核员看到 diff 还是整份重审？ | ❌ 都没有。无 diff、无版本快照；`save_profile` 是 `{**old, **clean}` 覆盖式合并 ⇒ **审核员无法知道改了什么** | `MISSING` |
| 13 | 谁审核过？ | ✅ `payload_json.reviewed_by` | `DEFINED` |
| 14 | 有没有审核历史？ | ❌ 只有"最后一次"（`reviewed_by`/`reviewed_at`/`review_note` 被覆盖）。**无审核历史表** | `MISSING` |
| 15 | 合同审核是不是同一个工作台？ | ❌ 是第二个动作端点（`contract-decision`），同样无界面、无队列 | `MISSING` |
| 16 | 是否有权限区分主体审核员 / 合同审核员？ | ❌ **没有**。两个端点都用 `admin_principal`（只校验 `actor_type=='GO_ADMIN'`），**完全不使用权限系统**。现有权限词表 `admin:read/orders/finance/trust/rules/connector/approve` 里没有任何入驻相关项 | `MISSING` |
| 17 | 审核员误操作后怎么恢复？ | ❌ 无撤销、无回滚。`decide_profile` 无前置状态校验之外的任何补偿；一旦 `NEEDS_CHANGES` 用户不改就无法回头 | `MISSING` |

### 标记

> **`BACKEND_CAPABILITY_WITHOUT_PRODUCT` = YES（供应商入驻审核）**
> 且有两点比这个标记更糟：
> - 「后端能力」本身不完整：**无队列、无列表端点、无详情端点**。审核员唯一能做的动作是"在两个已知 id 上 POST"。
> - 「后台界面」这件事上，**同一代码库里有反例**：`hotel-direct-review.js` 是完整审核台（冲突文案、房型映射、原图授权、哈希守卫的 approve/publish/revoke、`REVIEW_CHANGED` 竞态保护）。**能力不是做不到，是没做在这一条线上。**

---

## 10. Contract lifecycle

| # | 问题 | 现状 | 判定 |
|---|---|---|---|
| 1 | 合同由谁生成？ | **无生成方。**没有任何模板、渲染或生成代码 | `MISSING` |
| 2 | 用户在哪里下载？ | 无处。没有下载端点 | `MISSING` |
| 3 | 模板还是个性化？ | 未定义。只有 `contract_version`（可选字符串，用户自填） | `MISSING` |
| 4 | 签署方式（电子签/下载盖章上传/线下）？ | 未定义。UI 只说「已盖章合同资料引用」——**暗示线下盖章，但既不能上传，也没有说明签署主体与签署流程** | `MISSING` |
| 5 | 合同属于 Supplier / Legal Entity / Hotel？ | 未定义（因为 legal entity 对象不存在）。数据挂在 `CommercialCaseRow.payload_json.contract` | `MISSING` |
| 6 | 一份合同能覆盖多家酒店吗？ | 不能（一 supplier 一 hotel） | `MISSING` |
| 7 | 合同版本如何管理？ | 无管理。`contract_version` 是自由字符串 | `MISSING` |
| 8 | 到期怎么办？ | 无到期概念（无有效期字段） | `MISSING` |
| 9 | 续签怎么办？ | 无 | `MISSING` |
| 10 | 补充协议怎么办？ | 无 | `MISSING` |
| 11 | 主体变更怎么办？ | 无 | `MISSING` |
| 12 | 合同被退回怎么办？ | ✅ `CONTRACT_NEEDS_CHANGES` + `contract_review_note`（但 h1 文案错误，见上轮 `H1-COLLISION`） | `PARTIAL` |
| 13 | 已批准合同谁能查看？ | 无对象、无访问规则 | `MISSING` |

**PM 判断**：合同在 GO 里**不是对象，是两个字符串**。而合同是整条入驻链路上**唯一有法律约束力的产物** —— 它现在的完整度是 `contract_ref`（必填）+ `contract_version`（可选）。这是本轮**最大的"产品规则未定义"缺口**，也是最不该现在建表的地方。

补充证据：全库 `class .*(Contract|Agreement)` 只命中 `VerticalPrebookContractRow`（门票预售合约）与 `CatalogCreditContractRow`（信用合约），**都不是供应商合作合同**。

---

## 11. Notification / support

| 事件 | 页面状态 | Email | 手机 | 消息中心 | 联系客服 |
|---|---|---|---|---|---|
| 注册成功 | ✅ 直接进 `酒店主体认证` | ❌ | ❌ | ❌ | ❌ |
| 验证码 | ✅ 页内提示 | ✅ 唯一实装的邮件 | ❌ | — | ❌ |
| 提交成功 | ✅ 进 `资料正在审核` | ❌ | ❌ | ❌ | ❌ |
| 审核中 | ✅ 静态页 | ❌ | ❌ | ❌ | ❌ |
| **审核退回** | ⚠️ 只有下次登录才看到 | ❌ | ❌ | ❌ | ❌ |
| **审核通过** | ⚠️ 只有下次登录才发现变了 | ❌ | ❌ | ❌ | ❌ |
| **合同待签** | ⚠️ 只有下次登录才发现 | ❌ | ❌ | ❌ | ❌ |
| **合同退回** | ⚠️ 只有下次登录才发现 | ❌ | ❌ | ❌ | ❌ |
| 合同通过 | ⚠️ 只有下次登录才发现 | ❌ | ❌ | ❌ | ❌ |
| 账号开通 | ⚠️ 只有下次登录才发现 | ❌ | ❌ | ❌ | ❌ |

**证据**：
- 供应商域**没有通知模型**。全库只有 `ConsumerNotificationRow`（消费者）与 `HostedReservationNotificationRow`（酒店前台托管预订）。
- `supplier_onboarding_state.py` 的 5 个状态迁移函数（`save_profile` / `submit_profile` / `decide_profile` / `submit_contract` / `decide_contract`）**全部只写 `row.updated_at`** —— 不写 `OutboxRow`、不写事件、不发信。（`grep send_code|send_email|notify|Notification` 在这两个 service 文件里 **0 命中**）
- 唯一的通知能力是 `registration_email.send_code`，**只发验证码**，签名是 `SEND_CODE`，无法承载业务通知。

**"用户卡死时有没有人可以找？"—— 没有。**
- 入驻页只有「退出登录」一个按钮。
- 唯一的对外渠道是 `privacy.html`（"隐私与数据权利"），它对应 `PrivacyRequestRow`，服务的是**个人信息权利申请**（查阅/更正/删除/撤回/注销/限制/转移），**不是业务支持**。
- `#/help`（帮助与工单）路由存在，但它属于**入驻完成之后**的后台导航（`hiddenNav`），而且在入驻期间根本渲染不出来。

---

## 12. Exception & dispute handling

| 异常 | 现状 |
|---|---|
| 重复酒店申请 | ❌ 无检测、无处理流程 |
| 两家供应商认领同一酒店 | ❌ 无检测、无处理流程（无 claim 对象、无争议对象） |
| 已认领酒店被他人再申请 | ❌ 无拦截（没有"已存在关系"检查） |
| 资料造假 | ❌ 无流程（无资料可比对；无审核 finding 模型） |
| 主体与酒店关系不成立 | ⚠️ 靠审核员自由文本 + 只有一个 `APPROVED_HOTEL_REGISTRATION_REQUIRED` 的硬门 |
| 审核争议 / 申诉 | ❌ 无。供应商没有申诉入口；`PostStayDispute*` / `StayDisputeRow` 属交易售后域 |
| 账号被冒用注册 | ❌ 无流程 |
| 变更申请被拒后回退 | ❌ 变更申请根本不会被处理 |

**PM 判断**：入驻域的异常处理**完全不存在**。而"重复酒店""两家认领同一家""酒店已被别人注册"这三件事，是**任何酒店平台上线第一天就会遇到**的问题，也是商务团队最常被投诉的问题。目前没有任何机制。

---

## 13. Domain model completeness

### 任务要求的 17 个对象，逐一对照

| 对象 | GO 里的对应物 | 状态 |
|---|---|---|
| Account | `IdentityUserRow` | ✅ 存在（但 `supplier_id` 单值，语义过载） |
| User | 与 Account 同一张表 | ⚠️ 未分离 |
| Supplier | **没有 supplier 表**。`supplier_id` 是一个字符串，散落在 `IdentityUserRow` / `HotelPartnerPropertyRow` / `HotelRegistrationDirectRow` / `CommercialCaseRow` | ❌ **缺失** |
| Legal Entity | 无 | ❌ **缺失** |
| Hotel | `HotelCanonicalProfileRow`（canonical） | ✅ 存在 |
| Hotel Alias | 无 | ❌ **缺失** |
| Hotel Claim | 无 | ❌ **缺失** |
| Supplier ↔ Hotel relationship | 只有 `HotelRegistrationDirectRow`（GO Direct 注册的**结果**，无类型、无生效期、无终止） | ⚠️ 部分（形状不对） |
| Membership / Staff | 无（`HostedStaffRoleRow` 属另一域） | ❌ **缺失** |
| Application | 无独立表；= `CommercialCaseRow(case_type='SUPPLIER_ONBOARDING')` | ⚠️ 借壳 |
| Document | 无 | ❌ **缺失** |
| Document Version | 无 | ❌ **缺失** |
| Review | 无（只有 `reviewed_by`/`reviewed_at`/`review_note` 三个字段，且被覆盖） | ❌ **缺失** |
| Review Finding | 无 | ❌ **缺失** |
| Contract | 无 | ❌ **缺失** |
| Contract Version | 无（一个自由字符串） | ❌ **缺失** |
| Notification | 无（供应商域） | ❌ **缺失** |

### 已有且值得保留的对象（不是垃圾）

- `IdentityUserRow` / `AuthSessionRow` / `RefreshTokenRow` —— 会话与令牌模型完整（含 `token_version` 撤销、MFA、SSO）。
- `RegistrationDecisionRow` —— **按条款逐项**记录决策（`CONTRACT_ACCEPTED` / `NOTICE_ACKNOWLEDGED` / `DEFERRED`）+ 版本 + 哈希 + 过期。这是**真实的产品级对象**，值得保留。
- `RegistrationChallengeRow` / `RegistrationRateRow` —— 验证码的持久化、单次使用、多维限流（地址/对端/全局/冷却），设计正确。
- `AuditEventRow` —— 审计。
- `ApprovalRequestRow` —— 通用双签。
- `HotelCanonicalProfileRow` / `HotelContentSourceSnapshotRow` / `HotelContactPointRow` / `HotelAutoPageVersionRow` —— 酒店库，产品级。
- `HotelRegistrationDirectRow` —— 酒店↔供应商关系**结果**（有 reviewed_by/reviewed_at，可审计）。
- `HotelPartnerPropertyRow` / `HotelPartnerRoomTypeRow` 等 —— 供应商自营酒店资料，产品级。
- `CommercialCaseRow` —— **通用案例容器**（case_type + state + priority + owner + sla_due_at + payload + evidence + version）。这是一个**正确形状**的抽象，只是入驻没有把它用满。

### 结构性缺陷（三条）

1. **ID 语义冲突**：`CommercialCaseRow.property_id` 存的是 canonical `hotel_id`；`HotelPartnerPropertyRow.property_id` 是另一个 ID 空间。同名不同物。
2. **业务数据堆在 JSON blob**：`payload_json.profile` / `payload_json.contract` / `review_note` 全在 blobs 里 ⇒ **无法做约束、无法做索引、无法做 diff、无法做 item-level finding**。这正是"改了什么"回答不了的根因。
3. **`supplier_id` 语义过载**：同时表示账号容器、酒店持有者、注册方。只要产品需要"多酒店/多员工/多主体"，这个字段就必须被拆掉。

---

## 14. Database readiness

### 分类

#### A. `DOMAIN_STABLE` —— 可以建，也可以保留（规则已确定、且已被真实执行验证）

| 对象 | 为什么稳定 |
|---|---|
| `identity_user` + `auth_session` + `refresh_token` | 认证规则明确；单 supplier 假设**是当前唯一被实现的行为**（但见下方警告） |
| `registration_challenge` / `registration_rate` / `registration_decision` | 验证码与条款同意规则已定，逐项决策 + 哈希 + TTL 已实现且被测试 |
| `audit_event` | 规则通用 |
| `approval_request` | 通用双签，与业务规则解耦 |
| `hotel_canonical_profile` | canonical 酒店主键 + slug 唯一 + 事实来源分层，**已在生产路径使用** |
| `hotel_content_source_snapshot` | 来源快照 + rights_status + hash，规则清楚 |
| `hotel_contact_point` | 渠道归一 + 唯一约束 + do_not_contact + 营销资格，规则清楚 |
| `hotel_auto_page_version` | 页面版本 + page_hash 唯一 |
| `hotel_partner_property`（及 room_type / policy / ari / inbox） | 供应商自营资料，规则清楚、字段明确 |
| 媒体 asset 索引 + 授权声明 | 上传/授权/发布规则已完整实现并验证 |

> ⚠️ 对 `identity_user` 的警告：**它稳定，但它的"一个用户一个 supplier"假设是产品规则，不是技术必然。** 如果产品决定要支持多酒店/多员工/集团，**这张表要动结构（加关联表），不是加字段**。建议现在建、同时**在 V2 立刻引入 membership 抽象**，避免以后做大迁移。

#### B. `DOMAIN_PARTIAL` —— 可以做 provisional model，但不能当最终 production contract

| 对象 | 缺什么规则 |
|---|---|
| `supplier` 实体本体 | "supplier 到底代表什么"没定（公司？经营方？账号容器？） |
| `supplier ↔ hotel` 关系 | 关系类型（业主/管理方/代运营/集团）、生效期、终止、变更历史 —— 全未定 |
| `application`（入驻申请） | 字段集本身还没定（缺 USCC、执照有效期、注册地址）；应否独立成表未定 |
| `document` / `document_version` | 格式、大小、保留期、访问模型、是否加密 —— 全未定（§8） |
| `review` / `review_finding` | 审核组织模型（谁审、几级、是否分离主体/合同）未定 |
| `change_request` | `field_group` 词表已有（LEGAL/ADDRESS/BRAND/QUALIFICATION）但**决策面完全没有**；建了也只是一个更规范的死队列 |
| `notification` | 渠道（邮件/站内/短信/企微）、订阅、模板 —— 全未定 |
| SLA / assignment / priority | 有字段无规则；"谁负责哪一单、多久必须处理"未定 |

#### C. `PRODUCT_RULE_UNDEFINED` —— **现在建表 = 把未决的产品规则固化进 schema，应暂停**

| 对象 | 为什么现在不能建 |
|---|---|
| `hotel_alias` / `hotel_name_history` | 名称匹配规则未定（用什么匹配：名称？地址？经纬度？电话？OTA ID？USCC？）；匹配算法未定 ⇒ 表结构会决定算法 |
| `hotel_claim` / `ownership_dispute` | **认领规则完全未定**：谁能认领、依据什么、已认领怎么办、两人同时认领怎么办、争议怎么裁 |
| `supplier_membership` / `staff` / `invitation` | 角色词表、权限模型、邀请流程、离职交接 —— 全未定 |
| `contract` / `contract_version` | **生成方、模板还是个性化、电子签还是线下、属于谁、多店是否共签、到期续签补签** —— 全未定。这是最不该现在冻结的一张表 |
| `legal_entity` | 是否采 USCC、执照有效期、注册地址；主体与酒店的关系是否要落库 —— 未定 |
| `document_retention_policy` | 保留期本身在 registry 里反复声明 `RETENTION_SCHEDULE_UNCONFIRMED` ⇒ **平台自己都承认规则未定** |
| `onboarding_sla_policy` / `reviewer_assignment` | 审核组织模型未定（几人审核、是否分级、是否专职） |

### 明确回答

> **「以当前产品成熟度，现在应该继续建 Supplier onboarding production schema，还是先暂停并完成产品定义？」**
>
> **答：以"Supplier onboarding"为单位 —— 暂停 production schema，先完成产品定义。**
>
> 理由不是"建数据库不好"，而是**具体哪一格不能建**：入驻链路的核心对象（legal entity / claim / alias / document / review finding / contract / notification / membership）**恰好全部落在 C 类**。它们不是"实现还没写"，而是"规则还没定"。**在这些格子上建表，等于用 schema 替产品做决定，而这些决定后来一定会被推翻，代价是数据迁移。**
>
> **但 A 类应该照常建、而且应该继续建**：`hotel_canonical_profile` 及其酒店库一族、认证/会话/条款决策、audit、媒体管道 —— 这些规则已定、已被真实路径使用、且不依赖未决的入驻规则。**老板想继续"建库"，酒店库那一半是对的；被暂停的应该只是"供应商入驻"那一半。**

---

## 15. Existing backend capabilities worth keeping

**这些不要推倒重来。**

| 能力 | 位置 | 为什么值得留 |
|---|---|---|
| 认证 / 会话 / 令牌 | `IdentityUserRow` / `AuthSessionRow` / `RefreshTokenRow` + `identity_service` | 会话撤销（`token_version`）、MFA 绑定、SSO 字段、CSRF，模型完整 |
| 注册验证码管道 | `registration_verification.py` / `registration_email.py` | 单次使用、多维限流（冷却/地址/对端/全局）、hmac 摘要、失败态标记、重发竞态处理（`on_conflict_do_update` + `RETURNING`）—— **设计质量高** |
| **逐项条款决策记录** | `RegistrationDecisionRow` | 按 term 记 `CONTRACT_ACCEPTED` / `NOTICE_ACKNOWLEDGED` / `DEFERRED` + 版本 + 哈希 + 过期。**这是整个入驻链路里最产品级的一块** |
| 通用案例容器 | `CommercialCaseRow` | case_type + state + priority + owner + sla_due_at + payload + evidence + version。**形状正确**，入驻只是没用满 |
| 通用双签审批 | `ApprovalRequestRow` + `admin:approve` | 与业务解耦，可复用于入驻审批 |
| 审计 | `AuditEventRow` | 注册时已写入 `SUPPLIER_REGISTRATION_TERMS_ACCEPTED` + 决策元数据 |
| **酒店库（整套）** | `HotelCanonicalProfileRow` / `HotelContentSourceSnapshotRow` / `HotelContactPointRow` / `HotelAutoPageVersionRow` / `hotel_autopage_factory` / `hotel-discovery` / `hotel-infrastructure` | 有来源、有版本、有哈希、有联系点归一、有 `do_not_contact`、有发布状态。**这是 GO 真正的资产** |
| **媒体上传与授权管道** | `hotel_partner_media_upload.py` + `media_harvester` | 尺寸/格式/像素/动图校验、verify+load、sha256 去重、原子落盘、revision 并发、授权声明强制。（**只可复用形状，不可复用公开媒体语义**） |
| **酒店页面审核工作台** | `hotel-direct-review.js` + `hotel_direct_submission_review` | 冲突文案、房型映射、原图授权、`manifest_sha256`/`facts_sha256` 版本守卫、`REVIEW_CHANGED` 竞态保护、approve/publish/revoke。**直接可以作为供应商审核台的设计蓝本** |
| 供应商自营资料域 | `hotel_partner_core`（property / room_type / policy / ari / inbox / change_request） | 字段完整；`HIGH_RISK` 词表正确；`FOUR_STATE`（YES/NO/UNKNOWN/NOT_APPLICABLE）避免了"用空值表达'不知道'" |
| 供应商侧工作台（入驻之后） | supplier console 全部视图 + 移动端 IA | 上轮已确认：**这一层是个像样的产品** |

---

## 16. Things that were overbuilt too early

### 16.1 `CONTROL_AHEAD_OF_PRODUCT` 的量化证据

- 管理端一级导航**实测 62 项**，其中**第 11–40 项连续 30 项**全是「恢复 / 信任 / 混沌 / 豁免 / 预测 / 遥测 / 身份生命周期与重签发 / 联邦信任 / 信用平面容灾 / 异常债务清理」类。
- 对比：**供应商入驻审核项 = 0**（最接近的只有第 55 项「供应商管理」，且它是只读 registry）。
- `models.py` = **583,862 字节**，而 `supplier_onboarding_state.py`（整条入驻业务逻辑）= **188 行**。

### 16.2 具体清单：哪些属于过早优化 / 过早治理

| 属于过早治理的东西 | 为什么"现在做"是错的 |
|---|---|
| 恢复控制 / 恢复实验 / 恢复学习 / 恢复数据治理 / 学习事件控制 / 恢复发布治理 / 运行时发布安全 / 运行遥测治理 / 运行遥测可信 | 这些优化的是「已上线系统的自愈与观测」。**供应商入驻这条链路上，一个真实供应商都还没走通过。** |
| 运行身份生命周期 / 身份重签发 / 凭证授权 / 联邦信任执行 / 外部信任与多地域 / 信任传播与恢复 / 信任平面独立与容灾 | 这些是**多地域、多信任域**成熟后期的问题。当前是单 HK staging、单一运营方。 |
| 信任混沌与就绪 / 持续混沌与豁免 / 豁免暴露与技术债 / 异常债务清理 | 混沌工程的前提是有稳定运行的生产系统。**当前生产里没有供应商入驻数据流。** |
| 企业风险组合 / 风险偏好 / 风险预测 / 预测校准 / 预测统计晋级 / 预测漂移 / 预测训练可复现 / 预测制品供应链 / 预测服务证明 | 预测模型治理需要**历史样本量**。入驻域的样本量是 0。 |
| 对"留存期限 / 跨境 / 接收方清单"做条款级门禁 | 而注册文件本身还不存在（§8）。**先管住一个还不存在的东西的保留期。** |
| 条款发布门禁做到哈希级 + 逐项决策 + 过期 | ⚠️ 这块**不算过度**（见 §15），但它反衬出一个反差：**条款的严肃程度远高于入驻业务本身。** |

### 16.3 一个格外值得点名的反差

`registry.json` 里，平台为自己的协议登记了 6 项 `unresolved`、要求逐项批准记录、要求 `delivery_verified`、要求 `cross_border_assessment`。
而**同一份代码库里，一个真实酒店要提交营业执照这件事，连一个上传字段都没有。**

> **治理的颗粒度 ≫ 业务的颗粒度。** 这就是 `CONTROL_AHEAD_OF_PRODUCT` 最直观的样子。

---

## 17. Things that were deferred but should have been P0

以下是**明确知道缺、但被当成"以后再做"**的核心能力。这些不是 nice-to-have。

| # | 被延后的东西 | 为什么它应该是 P0 | 证据 |
|---|---|---|---|
| 1 | **文件上传（证件 / 合同）** | 没有它，"提交主体资料"这个动作在语义上是空的 —— 用户提交的是一串字符串，审核员审不了 | 0 `UploadFile`；4 个 `*_ref` 文本字段；`REQUIRED_PROFILE_FIELDS` 却要求它们非空 |
| 2 | **酒店判重 / 认领** | 上线第一天就会遇到"这家酒店已经被别人注册了" | 无匹配、无 claim、无拦截 |
| 3 | **审核队列 / 审核台** | 没有它，申请提交后**没有人知道它存在** | 无队列端点、无列表端点、0 前端引用 |
| 4 | **合同对象** | 合同是唯一有法律约束力的产物，现在只是两个字符串 | 无 Contract 模型；`contract_ref` 必填字符串 |
| 5 | **找回密码** | 任何商业产品的基本项；供应商一旦忘记密码即永久失去账号 | 全库 0 命中 |
| 6 | **入驻结果通知** | 用户必须靠反复登录猜审批结果 | 无通知模型、无 outbox 写入 |
| 7 | **变更 / 续签 / 退出** | 已上线酒店的日常运营必然需要 | 变更申请只写不读；续签/退出无路径 |
| 8 | **多酒店 / 多员工 / 集团** | 直接决定 `identity_user` 与 `supplier` 的表结构，**越晚改代价越大** | `supplier_id` 单值列 |
| 9 | **主体法定标识（USCC）** | 没有它无法在法律上唯一确定一个主体，也无法判重 | 表单无此字段 |

### `DEFERRED_CORE_REQUIREMENT` = YES

> 有明确证据表明这些能力**被告知缺失却没有进入实施**：
> - 上轮已发现的 `KNOWN-01` / `KNOWN-02` 是**同一批**缺口的一层皮（420px 布局、条款文案），而它们下面的东西更根本。
> - 代码里存在**完整的上传管道**，却被限定在"营销图片"这一用途，说明团队**有能力做文件处理，只是没把证件文件排进范围**。
> - 代码里存在**完整的审核工作台**（酒店图片），说明团队**有能力做审核界面，只是没把供应商审核排进范围**。
> - `CommercialCaseRow` 有 `sla_due_at` 却从不赋值、`HotelPartnerChangeRequestRow` 有 `state` 却从不推进 —— 典型的"**表建了，功能没排期**"。
>
> 三条合起来指向同一件事：**这些不是"技术做不到"，是"范围里没有"。**

---

## 18. Missing product decisions

以下每一项都必须由产品（+法务/运营）先给出决定，**否则任何数据模型都建不稳**。这是 §14 C 类的展开。

| # | 待决问题 | 影响的对象 |
|---|---|---|
| D-1 | **Supplier 代表什么？**公司 / 酒店 / 经营方 / 账号容器 | `supplier`、`legal_entity`、全部关系 |
| D-2 | **账号与供应商是多对多还是一对一？**一个账号能否管多店？一个酒店能否多账号？ | `identity_user.supplier_id`、`membership` |
| D-3 | **酒店身份用什么匹配？**名称 / 别名 / 地址 / 经纬度 / 电话 / OTA ID / USCC —— 优先级与容错 | `hotel_alias`、判重算法 |
| D-4 | **认领规则？**谁能认领、依据什么证据、已认领怎么办、双人认领怎么裁 | `hotel_claim`、`ownership_dispute` |
| D-5 | **酒店改名 / 换牌 / 换主体的规则？**谁发起、要什么证据、生效时点、对已有订单的影响 | `change_request` 决策面、`hotel_alias` |
| D-6 | **采不采 USCC / 执照有效期 / 注册地址？**如果采，怎么验证？ | `legal_entity`、`application` 字段集 |
| D-7 | **证件与合同文件的隐私模型？**谁能看、保留多久、注销/终止后怎么处理、要不要加密 | `document` / `document_version` / retention |
| D-8 | **合同怎么产生与签署？**模板？个性化？电子签？线下？属于谁？多店共签？ | `contract` / `contract_version` |
| D-9 | **续签 / 补签 / 到期提醒的规则？** | `contract`、`notification` |
| D-10 | **审核组织模型？**谁审、几级、主体审核与合同审核是否分离、SLA 多久、谁兜底 | `review`、`review_finding`、`onboarding_sla_policy` |
| D-11 | **通知渠道与订阅？**邮件 / 站内 / 短信 / 企微，哪些事件必须发、谁来发 | `notification` |
| D-12 | **员工角色与权限词表？**店主 / 收益 / 运营 / 只读 / 离职交接 | `membership`、`roles` |
| D-13 | **退出合作（offboarding）流程？**订单结转、资料撤回、主体解绑、记录保留 | `offboarding` |
| D-14 | **补件的粒度？**按字段 / 按文件 / 按整份 | `review_finding` |
| D-15 | **入驻是否允许"先建库、后认证"？**即供应商能否在审批通过前先建立自己酒店的资料 | 整个 `DEADLOCK-01` 的解开方式 |

> **D-15 是最关键的一条。** 现在的死锁正是因为设计上要求"先有已核验的酒店，才批主体"，但产品上又不允许供应商在审批前接触酒店库。**这两条规则必须选一条。**

---

## 19. Recommended scope for Supplier Onboarding V2

> 如果由我接任 PM，只允许做一个集中版本，我会这样划范围。

### V2 的目标（一句话）

**让一家真实酒店在无人指导的情况下走完入驻，并让一名运营人员在不碰数据库的情况下完成审核。**

### V2 范围内的 8 件事

**① 解开死锁（先做，其它都要靠它）**
二选一，我推荐第 2 条：
- (a) 保持"先有酒店库"，但**在入驻流程里加入"认领/匹配已有酒店"这一步**（用户输入酒店名 → 平台搜索 canonical → 用户确认 → 建立 claim）；或
- (b) **允许"先建主体、后挂酒店"**：主体审批只审主体（营业执照 + USCC + 法人 + 授权），酒店关系作为**独立第二步**，解锁条件从"酒店已核验"降为"主体已核验"。

**② 主体 = 真实法律实体**
新增 `legal_entity` 概念 + 采 `统一社会信用代码`（唯一键，用它判重）+ `注册地址` + `营业执照有效期`。`organization_name` 与 `hotel_name` 的关系写进产品规则并在 UI 上解释。

**③ 真正的文件上传（受限文件域，独立于公开媒体）**
- 复用 `hotel_partner_media_upload` 的**工程形状**（大小/格式/解码/去重/原子写/并发），**不复用它的公开媒体语义**。
- 新增：PDF 支持、HEIC 转码或明确拒绝并提示、EXIF 剥离（**证件必须**）、受限存储桶、**仅申请人 + 审核员可访问**、无公开 URL、删除与替换、保留期。

**④ 审核工作台（供应商入驻版）**
直接**照抄 `hotel-direct-review.js` 的形态**：待审队列 → 详情（账号 / 主体 / 酒店 / 文件预览 / 历史）→ item-level finding（勾选哪一项不合格）→ 退回 / 批准 → 版本守卫。**含一个真正的「待审核队列」端点。**

**⑤ 全套状态文案 + 通知**
每个状态：我在第几步 / 还差什么 / 下一步是什么 / 要等多久 / 出问题找谁。**至少 3 个事件必须发邮件**：提交成功、退回、通过。

**⑥ 找回密码**

**⑦ 多酒店 / 多员工 / 集团（结构决定，越早越好）**
引入 `supplier ↔ hotel` 关系表（带类型：业主/管理方/代运营，带生效期）+ `membership` 表（user ↔ supplier ↔ property + role）。**即使 V2 UI 只暴露"一账号一业务"，表结构也要先对。**

**⑧ 变更闭环**
把已经存在的 `HIGH_RISK={LEGAL,ADDRESS,BRAND,QUALIFICATION}` 变更申请**接上决策面**（谁批、在哪批、批完怎么生效）。

### V2 明确不做

- 合同生成 / 电子签：**只定义接口与状态，不做实现**（因为 D-8 未决）。V2 先用"上传已盖章合同 + 人工登记版本"，但必须有 `contract` 对象承载它，不能再是字符串。
- 短信 / 企微通知：先用邮件。
- 预测 / 混沌 / 信任平面类：**完全不碰**。

### V2 的验收标准（PM 版，不是工程版）

> 给 10 家真实酒店发链接（其中 1 家已存在、1 家已被竞对注册、1 家改名过、1 家是集团旗下、1 家是第三方代运营）：
> - 不需要给任何一家打电话解释；
> - 运营人员全程不碰数据库；
> - 每一次状态变化，申请人**在下一次打开页面时已经知道**，且知道为什么；
> - 审核员能精确说"第 3 项不合格"，申请人只改第 3 项。

---

## 20. What NOT to rebuild

**以下东西已经对了，不要推倒重来。**

1. **认证 / 会话 / 令牌**（含 `token_version` 撤销、MFA、SSO 字段、CSRF）—— 直接用。
2. **注册验证码管道**（限流、单次使用、重发竞态）—— 直接用，质量高于大多数商业实现。
3. **逐项条款决策记录 `RegistrationDecisionRow`** —— 保留这个对象与语义（`CONTRACT_ACCEPTED` / `NOTICE_ACKNOWLEDGED` / `DEFERRED`）。**这是全链路最产品级的一块。**
4. **`CommercialCaseRow` 通用案例容器** —— 形状正确，只是要给它补 review/SLA/assignment 的规则，而不是另起炉灶。
5. **`ApprovalRequestRow` 双签** —— 可直接用于入驻审批。
6. **`AuditEventRow`** —— 直接扩展事件类型即可。
7. **整个酒店库**（canonical profile / source snapshot / contact point / auto page version / discovery / infrastructure）—— **不要动**，这是 GO 的资产。
8. **媒体上传的工程形状**（校验、去重、原子写、revision 并发、授权声明）—— **复形状，不复语义**。
9. **`hotel-direct-review.js` 审核台的交互与竞态保护模式**（`manifest_sha256`/`facts_sha256` 守卫 + `REVIEW_CHANGED`）—— **作为供应商审核台蓝本**。
10. **供应商自营域**（property / room_type / policy / ari / inbox）与 **`FOUR_STATE`（YES/NO/UNKNOWN/NOT_APPLICABLE）** —— 这个四态设计避免了"用空值表达不知道"，值得扩散到主体资料。
11. **入驻之后的供应商工作台（含移动端 IA）** —— 上轮已确认它是像样的产品。

---

## 21. Launch readiness verdict

假设明天商务团队拿到 10 家真实酒店名单：

| PM 必须回答的问题 | 答案 | 状态 |
|---|---|---|
| 我敢不敢把注册链接发出去？ | **不敢。**注册今天全死（上轮 P0），即使修好，流程在"提交资料"和"等待结果"两处会断 | 🔴 |
| 预计有多少需要人工指导？ | **10 家全部。**因为(a) 要求用户填"资料引用"且无处上传；(b) 没有进度提示；(c) 结果不通知 | 🔴 UNKNOWN→ALL |
| 一个酒店注册需要多久？ | **UNKNOWN。**没有任何一家走通过；且流程里存在一个不可达节点 | 🔴 UNKNOWN |
| 平台每天能审核多少家？ | **0（无审核台）。**且**无法批准** —— 见 `DEADLOCK-01` | 🔴 0 |
| 谁负责处理异常？ | **UNKNOWN。**无队列、无分配、无 SLA（字段不赋值）、无兜底角色 | 🔴 UNKNOWN |
| 重复酒店怎么处理？ | **UNKNOWN。**不判重、无 claim、无争议流程 | 🔴 UNKNOWN |
| 文件放哪？ | **没有文件。**资料是字符串；唯一的存储是公开媒体目录 | 🔴 |
| 合同谁管？ | **UNKNOWN。**无合同对象、无负责人、无流程 | 🔴 UNKNOWN |
| 用户忘密码谁处理？ | **没人能处理。**无找回功能 | 🔴 |
| 审核员在哪工作？ | **没有地方。**无队列、无界面 | 🔴 |
| 数据出了问题怎么查？ | ⚠️ 有 `AuditEventRow` + 可查数据库（需工程介入）；**运营侧无自服务** | 🟡 PARTIAL |

### Verdict

> ## `NOT_LAUNCH_READY`

**关键 UNKNOWN 计数：7 / 11**（其余 2 项为 🔴 明确不可用，2 项为部分可用）。

**给老板的一句话**：今天这 10 家酒店名单发不出去；而且不是"改个文案就好了" —— **商务、运营、产品三方在这条链路上都没有可用的工具，有些人（审核员）连工作的地方都没有。**

---

## MANDATORY MATRIX

| Product Capability | Product rule defined? | Backend exists? | Frontend supplier exists? | Admin UI exists? | Database model exists? | Failure recovery exists? | Production-ready? | Evidence |
|---|---|---|---|---|---|---|---|---|
| Account creation (email+password) | YES | YES | YES | n/a | `identity_user` | PARTIAL | PARTIAL | `bff.py:123-167`；`IdentityUserRow` |
| Phone identity / verification | **NO** | NO | collects free text | n/a | **NO column** | NO | **NO** | `IdentityUserRow` 无 phone；`SupplierRegisterBody.phone` |
| Multi-hotel per account | **NO** | NO | NO | NO | `supplier_id` 单值 | NO | **NO** | `models.py:1116` |
| Multi-staff per supplier | **NO** | NO | NO | NO | NO | NO | **NO** | 无 membership 表/端点 |
| Multi-supplier per user | **NO** | NO | NO | NO | NO | NO | **NO** | 同上 |
| Password recovery | **NO** | NO | NO | NO | NO | **NO** | **NO** | `password-reset|forgot` 0 命中 |
| Account enumeration control | PARTIAL | PARTIAL | NO | n/a | n/a | NO | NO | `USERNAME_ALREADY_REGISTERED` 原样显示 |
| Staff handover / offboarding | **NO** | NO | NO | NO | NO | NO | **NO** | `HostedStaffRoleRow` 属另一域 |
| Hotel duplicate detection | **NO** | **NO** | NO | NO | NO | NO | **NO** | `duplicate` 在入驻路径 0 命中 |
| Hotel canonical identity | YES | YES | read-only partial | YES（酒店库） | `hotel_canonical_profile` | PARTIAL | PARTIAL | `models.py:7260`；`hotel-page-factory.js` |
| Hotel alias / name history | **NO** | NO | NO | NO | NO（`TravelEntityAliasRow` 属旅游实体） | NO | **NO** | grep `Alias|FormerName|NameHistory` |
| Hotel claim / dual claim | **NO** | NO | NO | NO | NO | NO | **NO** | 5 个 `*Claim*` 全属其它域 |
| Hotel rename / rebrand | **NO** | PARTIAL（`HIGH_RISK` 词表） | NO | NO | `change_request` 只写不读 | NO | **NO** | `hotel_partner_core.py:23,268` |
| Legal entity model | **NO** | NO | NO | NO | **NO** | NO | **NO** | 无 `legal_entity`；无 `supplier` 表 |
| USCC / licence validity collection | **NO** | NO | NO | NO | NO | NO | **NO** | `SupplierProfileBody` 12 字段无此项 |
| **Document upload (licence/ID/contract)** | **NO** | **NO** | NO（文本引用） | NO | NO | NO | **NO** | 0 `UploadFile`；0 `input[type=file]` |
| Image upload (marketing) | YES | YES | YES | YES | media index + rights | YES（revision/verify） | NEAR-READY | `hotel_partner_media_upload.py` |
| PDF / HEIC support | **NO** | NO | NO | NO | NO | NO | **NO** | `MEDIA_IMAGE_FORMAT_NOT_ALLOWED` |
| Document version / preview / replace / delete | **NO** | PARTIAL（asset revision） | NO | PARTIAL | NO | NO | **NO** | 无删除端点；无版本历史 |
| Document retention / access model | **NO** | NO | NO | NO | NO | NO | **NO** | registry `RETENTION_SCHEDULE_UNCONFIRMED` |
| **Application review queue** | **NO** | **NO list/queue endpoint** | n/a | **NO** | 借用 `commercial_case` | NO | **NO** | `admin_queues` 7 队列无 onboarding |
| Item-level review finding | **NO** | NO（自由文本） | NO | NO | NO | NO | **NO** | `review_note` 单字段 |
| Review history / diff | **NO** | PARTIAL（audit rows） | NO | NO | NO | NO | **NO** | `reviewed_by` 被覆盖 |
| Reviewer role separation | **NO** | NO（`admin_principal` 无权限） | n/a | NO | NO | NO | **NO** | 权限词表无入驻项 |
| **Contract lifecycle** | **NO** | **NO** | NO | NO | **NO** | NO | **NO** | 只有 `contract_ref` + `contract_version` |
| Notifications (supplier) | **NO** | NO | NO | NO | **NO**（无 supplier notification 表） | NO | **NO** | 状态迁移不写 outbox |
| Support / contact channel | **NO** | PARTIAL | PARTIAL（隐私申请页） | NO | `privacy_request` | NO | NO | 入驻页仅"退出登录" |
| Business state machine | PARTIAL | YES | PARTIAL | NO | enum in `payload_json` | NO | NO | `supplier_onboarding_state.py` |
| **Onboarding approval reachability** | — | **DEADLOCK** | — | **NO** | — | NO | **NO** | `supplier_onboarding_state.py:124-132` + `deps.py:37-53` |
| SLA | PARTIAL | **NO（字段从不赋值）** | NO | NO | column `sla_due_at` | NO | **NO** | `register_account` 写 `None` |
| Change request closed loop | PARTIAL | **write-only** | NO | NO | `hotel_partner_change_request` | NO | **NO** | 无 APPROVED/REJECTED 写入 |
| Offboarding / termination | **NO** | NO | NO | NO | NO | NO | **NO** | `deactivate|offboard|terminate` 0 命中 |
| Terms consent record | YES | YES | YES | n/a | `registration_decision` | YES（hash+TTL） | **GOOD** | `models.py:8168` |
| Auth / session / RBAC | YES | YES | YES | YES | `auth_session`/`refresh_token` | YES | **GOOD** | `models.py:1127-1152` |
| Audit log | YES | YES | n/a | YES | `audit_event` | YES | **GOOD** | `bff.py:138-148` |
| Hotel library (canonical/source/page) | YES | YES | read-only | **YES** | 多表 | YES | **GOOD** | `hotel_autopage_factory` 等 |

---

## FINAL QUESTIONS

### 1. 当前 GO Supplier onboarding 是"完整产品""半成品""技术原型"还是别的什么？

**技术原型（`TECHNICAL_PROTOTYPE`）**，且是**被真正产品级的邻接系统包围的技术原型**。

不是"半成品"，因为半成品意味着部件形状对了只差完工。这里的形状本身就不对：**账号有了、状态枚举有了、但"申请""资料""审核""合同""通知""关系"这些对象都不存在**。它更像是一个**验证"注册 → 状态机 → 门禁"这个技术骨架能跑通**的原型。

### 2. 当前最大问题是？请给事实依据。

**"以上多项"，但根因顺序非常清楚：**

1. **产品规则未定义（根因）** —— 酒店靠什么匹配、谁能认领、合同怎么签、文件保留多久、审核怎么组织：**15 个待决问题（§18）全部未决**。证据：`hotel_claim` / `hotel_alias` / `contract` / `membership` / `document` 这些对象在 583KB 的 `models.py` 里**一个都没有**。
2. **领域模型错误/缺失** —— `supplier_id` 语义过载 + 单值；`CommercialCaseRow.property_id` 与 `HotelPartnerPropertyRow.property_id` 同名不同物；业务数据堆在 JSON blob 导致无法 diff/约束。证据：`models.py:1116`、`supplier_onboarding_state.py:134`。
3. **运营后台缺失** —— 无队列、无列表、无审核台、无权限分离、无 SLA。证据：前端 0 引用；`admin_queues` 不含 onboarding。
4. **缺功能** —— 上传、通知、找回密码、变更闭环、退场。
5. **设计死锁** —— 审批不可达。证据：测试必须直接 INSERT 数据库。
6. **UI 差** —— 这是**最表层**的一条（上轮的 22 条），而且它多半是上面 5 条的结果而不是原因。

**结论：UI 做得差是最小的那个问题。**

### 3. 现在继续大规模建 Supplier onboarding 数据库，是否合适？

**不合适 —— 但只针对"Supplier onboarding"这一段。**
反对理由不是抽象的：**入驻链路的核心对象恰好全部属于 `PRODUCT_RULE_UNDEFINED`（§14 C 类）**。在 claim / alias / contract / document / membership / notification 这些对象上建 production 表，等于**用 schema 替产品做决定**，而这些决定后来一定会被推翻，代价是数据迁移。

**酒店库那一段应该继续建**（§14 A 类）—— 那些规则已定、已被真实路径使用。

### 4. 哪些数据库对象现在已经稳定，可以保留/继续？

`identity_user` / `auth_session` / `refresh_token` / `registration_challenge` / `registration_rate` / `registration_decision` / `audit_event` / `approval_request` / `hotel_canonical_profile` / `hotel_content_source_snapshot` / `hotel_contact_point` / `hotel_auto_page_version` / `hotel_partner_property`（及 room_type / policy / ari / inbox）/ 媒体 asset 索引与授权声明。

⚠️ 一条警告：`identity_user` 的"一用户一 supplier"是**产品规则而非技术必然**，建议在 V2 **立刻引入 membership 抽象**，避免以后做结构迁移。

### 5. 哪些表现在不应该建，因为产品规则还没决定？

**`hotel_claim` / `ownership_dispute`、`hotel_alias` / `hotel_name_history`、`contract` / `contract_version`、`legal_entity`、`document` / `document_version`、`supplier_membership` / `staff` / `invitation`、`notification`、`document_retention_policy`、`onboarding_sla_policy` / `reviewer_assignment`、`review` / `review_finding`。**

（这几张表的共同点：**它们每一个的形状都会替 15 个待决问题中的至少一个做决定。**）

### 6. 如果由你接任 PM，只允许做一个集中版本 Supplier Onboarding V2，你会定义什么范围？

见 §19。范围一句话：**"让一家真实酒店在无人指导下走完入驻，并让一名运营人员在不碰数据库的情况下完成审核。"** 八件事：解开死锁 → 主体成为真实法律实体（USCC）→ 真正的受限文件上传 → 供应商审核工作台 + 队列 → 全套状态文案与通知 → 找回密码 → 多酒店/多员工/集团的关系结构 → 变更闭环。

### 7. 哪些现有后端能力应该保留，避免推倒重来？

见 §15 的 12 项。最该保留的四项：**注册验证码管道**、**逐项条款决策记录**、**整个酒店库**、**酒店图片审核台的交互与哈希守卫模式**（直接作为供应商审核台蓝本）。

### 8. 哪些旧设计属于"过早优化 / 过早治理"？

见 §16。最集中的是管理端那 **30 项连续**「恢复 / 信任 / 混沌 / 豁免 / 预测 / 遥测 / 身份重签发 / 联邦信任 / 信用平面容灾 / 异常债务清理」导航项，以及**对"还不存在的注册文件"做留存期/跨境/接收方清单级别的治理门禁**。

一句话：**治理的颗粒度 ≫ 业务的颗粒度。**

### 9. 从 Product Owner 视角，目前最容易被 PR/CI/Evidence 误导的地方是什么？

**四个具体的误导机制：**

1. **"测试通过"会被读成"产品可用"。** `test_supplier_onboarding_hk_unified.py` 的名字是 `requires_existing_hotel_truth_and_contract` —— **测试名字本身就在说"必须先有酒店真相"**，而且它**直接用 SQL 插入** canonical hotel 和 APPROVED registration。CI 绿灯代表"这套强耦合关系被正确断言"，**不代表任何供应商能走通**。这是最危险的一条。

2. **"有端点"会被读成"有功能"。** `profile-decision` 端点存在 ⇒ 看起来"审核有了"。实际是：无队列、无列表、无界面、需预知 2 个 ID、且大概率返回 `APPROVED_HOTEL_REGISTRATION_REQUIRED`。

3. **"有表/有字段"会被读成"有业务"。** `CommercialCaseRow.sla_due_at` 存在 ⇒ 看起来 SL​A 有了（入驻路径从不赋值）。`HotelPartnerChangeRequestRow` 存在 ⇒ 看起来变更管理有了（state 永远停在 SUBMITTED）。**字段存在感会制造功能存在感。**

4. **"数字会自我引用"** —— 比如上轮那个 `release_gate` 的 `reason` 字段：BFF 已经把真实原因（`LIVE_EMAIL_VERIFICATION_REQUIRED`）返回出来了，前端从没读过；如果只看 API 响应或监控面板，会认为"诊断信息已经具备了"。**信息被生产出来 ≠ 信息被使用。**

> **给 PO 的一个检查动作**：以后看 PR/CI 时，对每一个"供应商入驻"相关的能力，先问一句 **"这条路的终点是一个真实供应商的账号里能看到的东西吗？"** 如果答案不是"能"，那它就是 §16 的治理层，不是 §19 的产品层。

### 10. "老板只需要看 5 分钟"的产品现实摘要

---

**① 我们做完的和没做完的**

做完的：**全国酒店库**（建库、来源、图片授权、页面发布、审核台）—— 这一套是真的，质量高，是资产。
没做完的：**"一家酒店怎么变成我们的合作伙伴"** —— 这条链路只有一个注册表单。

**② 现在的实际状态**

一家酒店**注册不了**（今天整个注册表单是死的）。
就算注册打开，他会在**第二步卡死** —— 我们要他填"营业执照资料引用"，但**系统里没有上传文件的地方**，从头到尾一个都没有。

**③ 一个更根本的问题：审批走不通**

我们设计上要求"先有已核验的酒店，才能批准供应商"。
但供应商在批准之前，**看不到也做不了任何酒店相关的操作**（系统会拦他）。
**这是一个闭环，没有出口。**
我们自己写测试的时候，是**直接往数据库里插数据**才跑通的。测试的名字就叫"需要先有酒店真相"。

**④ 运营那边的工作台**

我们没有给审核员做后台。没有待审列表、没有审核界面。
现在两个审批接口，需要你**先知道对方的 ID**，而且**大概率会报错说"缺少已批准的酒店注册"**。
**审核员现在没有地方可以工作。**
（对比：酒店图片审核我们是做了完整工作台的 —— 所以不是做不到，是没排进范围。）

**⑤ 缺的东西里，哪些是"必须现在决定"的**

- 酒店怎么判断是不是同一家？**没规则**（不改的话，上线第一天就会有"这家酒店被别人注册了"的投诉）
- 两家公司抢同一家酒店怎么办？**没规则**
- 合同怎么产生、怎么签、归属于谁？**没规则**（现在合同就是两个文本框）
- 身份证、营业执照、合同的文件放哪、谁能看、留多久？**没规则**
- 一个集团能一次注册 N 家酒店吗？**结构上不行**（一个账号只能绑一家）
- 员工离职、换人、加人？**没有**

**⑥ 关于"继续建库"**

**建库那一半继续建，是对的。**
**但"供应商入驻"这一半的数据库建议先停一下** —— 因为要建的那几张表（酒店认领、名称历史、合同、文件、员工关系），**每一张的形状都会替一个还没做的产品决定拍板**。现在建，以后一定要迁。

**⑦ 一句总结**

> **我们花了大量工程把"别出错"做到了很细 —— 双签、哈希、审计、保留期、预测、混沌、信任平面。
> 但"这件事本身"还没定义完：一个酒店要交什么、交给谁、谁来看、看完怎么办。
> 现在最该做的不是继续加治理，而是把这条链路当成一个产品，从头定义一遍。**

---

## 附录 A：本地产物与可删除性

| 路径 | 内容 |
|---|---|
| *(local ephemeral detached worktree at PR376 head; not archived, reproducible via `git worktree add`)* | PR376 detached worktree（`git worktree remove` 可摘除） |
| `.../shots/` `.../shots-fixture/` | 上轮现场与夹具截图 |
| `.../audit-browser.mjs` `.../fixture-render.mjs` `.../probe.mjs` 及 `*-results.json` | 上轮审计工具与结果 |
| `GO_SUPPLIER_PRODUCT_AUDIT_20261003.md` | 上轮报告（本轮 §1/§18 引用它） |
| `GO_SUPPLIER_PM_PRODUCT_AUDIT_20261003.md` | 本报告 |

## 附录 B：未执行的 mutation（明确声明）

- ❌ 未修改任何 GitHub PR / branch / commit / merge
- ❌ 未 push、未 commit
- ❌ 未部署、未修改 HK-STAGING、未修改 Production
- ❌ 未修改数据库
- ❌ 未创建任何供应商账号、未调用任何审批端点
- ❌ 未新增任何治理体系、未设计 C13/C14
- ✅ 本轮为**纯静态阅读**：`git fetch` + `git worktree add` + 读取源码，**未对 staging 发起任何请求**

因此**不需要回滚**。
