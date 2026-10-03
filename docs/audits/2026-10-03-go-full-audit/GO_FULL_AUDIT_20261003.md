# GO FULL PRODUCT + PM + ENGINEERING AUDIT — 主报告

**Date**: 2026-10-03
**Mode**: READ ONLY / INVESTIGATION ONLY。零 mutation（无 commit / push / PR / deploy / DB 写 / 配置改）。
**Inventory / coverage map**: `GO_FULL_AUDIT_INVENTORY_20261003.md`
**前序专项**: `GO_SUPPLIER_PRODUCT_AUDIT_20261003.md`（用户体验）、`GO_SUPPLIER_PM_PRODUCT_AUDIT_20261003.md`（产品定义）

---

## 1. Executive Verdict

**GO 今天不是"一款产品"，也不是"一个半成品"，而是"三个成熟度差异极大的部分拼在一起"。**

| 部分 | 状态 | 一句话 |
|---|---|---|
| **C 端（`/go-app/`）** | **REAL_PRODUCT（界面）/ PARTIAL_PRODUCT（交易）** | 看起来、用起来像一个真的商业旅行产品；但背后的供给与支付**没有接通**，酒店详情页返回的是**测试夹具** |
| **酒店库 / 酒店页面 / 媒体 / 审核台** | **REAL_PRODUCT** | 有 canonical 实体、来源快照、原图授权、版本哈希、发布门禁、完整审核工作台。**这是 GO 真正的资产** |
| **B 端（`/supplier-console/`）** | **TECHNICAL_PROTOTYPE** | Supplier frontend defines **72 route/surface entries: 10 primary + 62 hidden**；入驻链路是死循环、必要对象不存在、审核员无工作台（见 PM 专项） |
| **运营后台（`/go-admin/`）** | **PARTIAL_PRODUCT + CONTROL_ONLY** | 62 项导航，其中连续 30 项是恢复/信任/混沌/预测/遥测治理；**供应商入驻审核 0 项** |
| **治理 / 恢复 / 信任 / 预测 / 风控** | **CONTROL_ONLY** | **占全部 API 约 26.5%（287 条，按声明文件口径）／28.2%（305 条，路径去重 union）**，自洽可运行，但不产生任何面向真人用户或运营人员的产品结果（口径见 §23 与 `GO_FULL_AUDIT_ERRATA_20261003.md` E-7） |
| **交付 / 运行时** | **DELIVERY_CORRECTNESS 合格，PRODUCT_CORRECTNESS 无关** | 8/8 服务跑同一镜像、字节可验证；但 runtime 指针、compose 定义、current-state 文档**三处全部与实际不符** |

### 一处必须强调的反向证据（E-10）

> **GO 的主要问题不是"建了 500 张完全没人用的空表"。**
> 563 个 model 中 **560 个在应用源码中被引用**、1 个仅测试引用、**2 个孤儿**（`connector_property_mapping_audit`、`stay_credit_redemption_quote`）。
> 真正的问题是：**大量表确实进入了 service/runtime，但它们服务的是不可达、非闭环、或产品规则尚未完成的业务。**
> 因此 **`ORPHAN_TABLE` 计数低 ≠ 数据库健康**；判定标准是 `REACHABILITY`（真人可达路径）。

### 核心判定

> ## `REAL_PARTS + PROTOTYPE_PARTS + LARGE CONTROL_ONLY MASS`
> 不是"部分成熟、部分原型"这么简单 —— 而是**大量工程被投在了不产生产品结果的地方**，同时**用户真正需要的那条链路（B 端入驻）是断的**，而**看起来很完整的 C 端背后没有真实供给**。

### 量化：本轮的三个决定性数字

1. **治理族路由占全部 API 约四分之一**：按**声明文件**口径 = **287 / 1082 = 26.5%**；按**路径去重 union** 口径 = **305 = 28.2%**。
   ⚠️ 口径说明：`recovery`(290) + `trust`(183) + `risk`(121) + `forecast`(97) 的**求和 691 是非互斥统计，不得当作占比使用** —— `forecast` 97/97 全部是 `recovery` 路径的子串（例：`/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast/…`）。见 `GO_FULL_AUDIT_ERRATA_20261003.md` E-7。
2. **`/internal/*` namespace = 710 / 1082 = 65.6%**（这是 URL namespace，**不是**鉴权口径）；**依赖集合含 `admin_principal` 的路由 = 558 / 1082 = 51.6%**（这是 auth principal 口径）。两者不可混为一谈。写路由 (742) 是读路由 (340) 的 **2.2 倍**。
3. **34 个 CI workflow 中只有约 6 个跑 pytest**，其余约 28 个是 governance / canonical / receipt / admission / evidence 流水线。

### 本轮 finding 分级（最终）

**P0 = 4 ｜ P1 = 10 ｜ P2 = 6 ｜ P3 = 3（共 23 条）**
较初版（5/10/7/3 = 25）的变化：`SEC-01` 口径收窄但保持 P0；**撤回 1 条错误 finding（原 `SEC-08`）**；新增 3 条已核实的安全项（`SEC-10/11/12`）；`models.py`／`shared/app.js` 拆分由 NEXT 移入 LATER 并降为 P3。逐项见 `GO_FULL_AUDIT_ERRATA_20261003.md` E-11/E-12。

对照：`db/models.py` = 8,195 行 563 个类，而 `supplier_onboarding_state.py`（整条 B 端入驻业务逻辑）= 188 行；前端 JS 总量只有 3,932 行。

---

## 2. What GO actually is today

**从源码能反推出的真实形态**：

一个**多品类旅行交易平台的后端骨架 + 一套自研的酒店数字基础设施 + 一个看起来完整的 C 端界面 + 一座巨大的治理机器**，其中：

- **能对真人工作的**：C 端浏览界面、酒店库与页面生产、图片授权与发布审核、注册验证码与条款同意记录、认证与会话。
- **不能对真人在工作的**：B 端入驻（死循环）、运营端审核（无工作台）、支付（未接通）、外部供给（测试模式）、AI（无 provider）。
- **对谁也不工作的**：约 287–305 条治理/恢复/信任/预测路由 —— 它们服务的是一个**还没有真实流量的系统**。

**它是什么产品？** 从代码里找不到答案。没有统一的落地页（`/` → 404），没有统一的产品前门，三个表面（`/go-app/`、`/supplier-console/`、`/go-admin/`）是三套独立观感，注册协议里写的运营主体是"构行人工智能（黑龙江）有限公司"，而产品名是"GO SI DIRECT / GO 旅行 / GO 合作伙伴平台 / GO 全生态运营管理系统"四个不同名字。

---

## 3. What is genuinely working（REAL_ASSET，不要推倒）

以下每一项都经过源码或现场验证，**方向与实现都正确**。

| # | 资产 | 证据 |
|---|---|---|
| 1 | **酒店库（canonical hotel + 来源快照 + 联系点 + 页面版本）** | `HotelCanonicalProfileRow(slug UNIQUE, canonical_json, field_provenance_json, completeness_bps, go_direct_state, page_state)`；`HotelContentSourceSnapshotRow`（带 `rights_status` + `payload_hash`）；`HotelContactPointRow`（渠道归一 + `uq_hotel_contact_point_value` + `do_not_contact` + 营销资格）；`HotelAutoPageVersionRow(page_hash UNIQUE)`。**有来源、有版本、有哈希、有授权、有发布状态。** |
| 2 | **酒店页面审核工作台** | `frontend/admin/hotel-direct-review.js`：冲突文案映射、房型对应、原图授权、`manifest_sha256` + `facts_sha256` 版本守卫、`REVIEW_CHANGED` 竞态保护、approve/publish/revoke 三态。**这是全仓库最像产品的一块前端。** |
| 3 | **媒体上传与授权管道** | `hotel_partner_media_upload.py`：PIL `verify()`+`load()`（拒绝截断）、DecompressionBomb 防护、40M 像素上限、格式白名单、拒绝动图、最小分辨率、sha256 去重、`.part`+`os.fsync` 原子写、`revision` 乐观并发、授权声明强制。 |
| 4 | **注册验证码管道** | `registration_verification.py`：单次使用、多维限流（冷却/地址/对端/全局）、hmac 摘要、失败态标记、`on_conflict_do_update(...).returning(...)` 处理重发竞态。质量高于多数商业实现。 |
| 5 | **逐项条款同意记录** | `RegistrationDecisionRow`：按 term 记 `CONTRACT_ACCEPTED` / `NOTICE_ACKNOWLEDGED` / `DEFERRED` + `versions` + `hashes` + `expires_ms`。 |
| 6 | **认证 / 会话 / 令牌** | `AuthSessionRow`（`auth_method`, `mfa_verified_at`, `csrf_token_hash`）、`RefreshTokenRow`（`token_hash` UNIQUE + 轮换）、`IdentityUserRow.token_version`（会话撤销）、MFA 绑定、SSO 字段。 |
| 7 | **通用案例容器 + 双签审批 + 审计** | `CommercialCaseRow`（case_type/state/priority/owner/sla_due_at/payload/evidence/version，形状正确）、`ApprovalRequestRow`、`AuditEventRow`。 |
| 8 | **C 端界面** | 现场 `/go-app/`：`GO 旅行`，h1「说出你的旅行想法」，5 品类 tab、5 项底部导航、2 张入口卡（GO SI / GO Offer）、3 个价值主张（直联/推荐/礼遇）、3 张旅行灵感卡。**匿名访问零页面级 JS 错误，只有 1 个预期 401。** |
| 9 | **房型映射与 Offer 合并/漂移** | `OfferMergeDecisionRow`、`OfferDriftStateRow`、`OfferDriftEventRow`、`PropertyMappingCandidateRow`、`RoomExternalIdentityRow`、`HotelExternalIdentityRow`。 |
| 10 | **多品类订单运行时** | `HotelOrderRuntimeRow` / `FlightOrderRuntimeRow` / `RailOrderRuntimeRow` / `MobilityRideOrderRuntimeRow` / `MobilityRentalOrderRuntimeRow`，各自被 16–28 处引用。 |
| 11 | **支付编排骨架** | `PaymentOrchestrationRow`、`PaymentOrderRoot*`、`PaymentOrderFactBinding`、`IdempotencyRow`、`OutboxRow`/`OutboxDeadLetterRow`。结构正确，只是没有真实 PSP。 |
| 12 | **7 个后台 worker 真实在跑** | outbox / recovery / reconciliation / judgment / mobile-engagement / mobile-push / mobile-push-receipt，全部 Up 4h，同一镜像。 |

---

## 4. What only looks complete

| # | 看起来完成的东西 | 实际状态 | 证据 |
|---|---|---|---|
| 1 | **"供应商入驻"** | **死循环，不可达** | `decide_profile(APPROVE)` 要求已 APPROVED 的 `HotelRegistrationDirectRow` + canonical `go_direct_state∈{VERIFIED,LIVE}`；产生它需已知 `hotel_id`；而供应商唯一能看到 `hotel_id` 的界面被 `supplier_principal` 门禁挡在 `CONTRACT_ACTIVE` 之前。开发方测试必须**直接 SQL 插数据**才跑通。 |
| 2 | **"供应商审核"** | **无队列、无列表、无界面** | 前端对 `/internal/v1/supplier-onboarding/...` 引用 **0**；`admin_queues` 7 个队列不含 onboarding；两个 decision 端点用 `admin_principal`（只查 actor_type）**绕过权限系统**。 |
| 3 | **"C 端可以订酒店"** | **酒店详情页返回测试夹具** | `GET /v1/consumer/hotels/hotel_test` → 200，`{"hotel_id":"hotel_test","name":"GO Hotel","city":"东京，日本",...}` —— `hotel_test` 就是供应商入驻测试里用的那个夹具 ID。 |
| 4 | **"C 端首页"** | **未鉴权 + 硬编码 demo** | `GET /v1/consumer/home` → 200，`{"brand":"GO","headline":"发现全世界，直接向官方预订","hotel_search":{"city_code":"TYO","check_in":"2026-09-0…"}}` |
| 5 | **"外部供给已接入"** | **测试模式** | 现场 env：`AOLUGUYA_DIRECT_TEST_MODE=true`、`AOLUGUYA_REAL_INVENTORY_CONFIGURED=false`、`AOLUGUYA_REAL_RATE_CONFIGURED=false`、`AOLUGUYA_REAL_PAYMENT_CONFIGURED=false` |
| 6 | **"AI 能力"** | **无 provider** | 现场 `GO_AI_PROVIDERS_JSON=`（空） |
| 7 | **"运营有后台"** | **平台级队列存在，业务级审核不存在** | `admin_queues` 覆盖 payment/external/refund/liability/risk/connector/outbox；**不含 supplier onboarding / hotel claim / contract / document** |
| 8 | **"有 62 项运营功能"** | **30 项是治理导航** | 见 inventory §3 |
| 9 | **"变更管理"** | **只写不读** | `HotelPartnerChangeRequestRow` 有 `HIGH_RISK={LEGAL,ADDRESS,BRAND,QUALIFICATION}` 且会创建 `SUBMITTED` 记录，但**全库无任何代码把它改为 APPROVED/REJECTED** |
| 10 | **"有 API 文档"** | **是对外公开的** | `/openapi.json` 852,802 B 公开 200；`/docs` Swagger UI 公开 200 |
| 11 | **"有测试"** | **83 个测试文件直接向 DB INSERT** | 498 处 `.add()`/`SessionLocal.begin()` —— 大量测试绕开产品路径 |
| 12 | **"runtime 指针一致"** | **三处 drift** | 见 §20 |

---

## 5. User Audit — Consumer

现场渲染（Chrome，1920/1440×900 + 390×844）：`/go-app/`

### 5.1 实际能做的

| Journey 步骤 | 状态 | 证据 |
|---|---|---|
| 打开站点 | ✅ | 200，`GO 旅行` |
| 看到产品定位 | ✅ | h1「说出你的旅行想法」；副标「发现全世界，直接向官方预订」 |
| 看到品类 | ✅ | 酒店 / 机票 / 火车票 / 租车 / 景点玩乐 |
| 看到价值主张 | ✅ | GO 直联 / GO 推荐 / GO 礼遇 |
| 看到旅行灵感 | ✅ | 京都 / 马尔代夫 / 里斯本 三张卡（真实图片） |
| 底部导航 | ✅ | 首页 / 行程 / 收藏 / 消息 / 我的 |
| 注册入口 | ✅ | 顶部「注册」按钮 |
| 注册后流程 | ⚠️ UNKNOWN | 未创建真实账号（边界禁止） |

### 5.2 实际问题

| Finding | 说明 | 证据 |
|---|---|---|
| `CON-01` **无统一产品前门** | `https://staging-api.goaidirect.com/` → **404**（JSON `{"detail":"Not Found"}`）。用户必须知道 `/go-app/` 才能进。三个表面互不相链。 | browser + curl |
| `CON-02` **桌面端是"手机栏"** | 1440×900 下内容列宽约 **440px**，两侧各留 ~500px 空白。C 端是移动优先设计，**没有做桌面布局**。 | `shots/consumer-desktop.png` |
| `CON-03` **匿名访问即触发接口探测** | 首屏即请求 `/v1/consumer/me` 并 401。属正常，但结合 §21 的未鉴权数据面，暴露面比预期大。 | 网络日志 |
| `CON-04` **`/internal/v1/demo/orders/{order_id}/complete-stay` 未鉴权** | 一个名字里带 `demo` 的路由在生产面**无鉴权且能变更订单**（源码确认，未调用）。 | `api_routes.json` |
| `CON-05` **酒店详情 = 夹具** | `hotel_test` / `GO Hotel` / `东京，日本` | curl |
| `CON-06` **首页硬编码** | `city_code: TYO`、`check_in: 2026-09-0x` | curl |
| `NOT_AUDITED` | 支付成功/失败路径、真实下单、退款到账 —— 需创建真实数据，边界禁止。**但 `AOLUGUYA_REAL_PAYMENT_CONFIGURED=false` 已经说明真实支付未接通。** | — |

**Consumer verdict**：**REAL_PRODUCT（界面层） / PARTIAL_PRODUCT（能力层）**。界面是真实资产；**界面背后是夹具与未接通的供给**。

---

## 6. User Audit — Supplier

复用前两轮专项结论（同 PR376 head，字节已验证），**不重复举证**。

| 结论 | 出处 |
|---|---|
| 注册今天 100% 不可用，且原因说错（把邮件服务问题说成条款问题） | `GO_SUPPLIER_PRODUCT_AUDIT_20261003.md` BLOCKER-1 |
| 12 个入驻字段中 4 个是「资料引用」纯文本，**全产品 0 个文件上传** | 同上 BLOCKER-2 |
| 420px 竖条跨 5 个入驻页面 | 同上 UI-WIDTH-01 |
| 无找回密码、原始枚举暴露、无通知 | 同上 |
| **入驻审批不可达（死循环）** | `GO_SUPPLIER_PM_PRODUCT_AUDIT_20261003.md` §1 ① |
| **审核员无队列无界面；两个 decision 端点绕过权限系统** | 同上 §1 ② |
| **12 个必要领域对象缺失**（Supplier/LegalEntity/HotelAlias/HotelClaim/Membership/Document/DocumentVersion/Review/ReviewFinding/Contract/ContractVersion/Notification） | 同上 §13 |
| **变更申请只写不读** | 同上 §6.3 |

**本轮新增（全项目视角）**：

| Finding | 说明 | 证据 |
|---|---|---|
| `SUP-01` **入驻之后 62 个隐藏界面** | `hiddenNav` 62 项 vs `partnerPrimaryNavMax: 7` 的自我声明。**Supplier frontend 定义了 72 个 route/surface：10 primary + 62 hidden。hidden surface 不代表同时可见的导航项；该数字用于说明信息架构复杂度，不直接等于用户可见入口数量。** | `supplier/config.js` |
| `SUP-02` **供应商数据面全部由单一门禁控制** | `supplier_principal`：`CommercialCaseRow.state ∉ {CONTRACT_ACTIVE, BUSINESS_ENABLED}` ⇒ 403 `SUPPLIER_ONBOARDING_INCOMPLETE`。**一个未完成的入驻功能，直接封锁了 46 条 `/v1/supplier/*` 路由。** | `security/deps.py:37-53` |
| `SUP-03` **B 端 UI 与 C 端 UI 是两套设计语言** | C 端是卡片式移动优先暖色调；B 端是 420px 居中登录卡 + 深蓝 shell；`privacy.html` 是第三套内联样式。 | 截图对比 |

**Supplier verdict**：**TECHNICAL_PROTOTYPE**（同 PM 专项）。

---

## 7. User Audit — Admin / Operations

现场渲染：`/go-admin/` → 登录页 `GO 全生态运营管理系统`，副标「系统自动运行 · 人只处理异常」，含「企业 SSO 登录」按钮，并显示 `当前环境暂未强制 MFA。测试期间可使用用户名和密码登录；正式启用后将要求完成 MFA 绑定与动态码验证。`

### 7.1 运营人员的一天（按代码能力推演）

| 我早上要处理的 | 有没有 | 在哪 |
|---|---|---|
| 支付对账异常 | ✅ | `/internal/v1/admin/queues` → `payment_reconciliation` |
| 外部操作恢复 | ✅ | `external_recovery` |
| 退款失败 | ✅ | `refund_failures` |
| 供应商赔付责任 | ✅ | `supplier_liability` |
| 风险事件复核 | ✅ | `risk_review` |
| 连接器健康 | ✅ | `connector_health` |
| Outbox 死信 | ✅ | `outbox_dead_or_retry` |
| **新供应商入驻申请** | ❌ | **无队列、无列表、无界面** |
| **酒店认领/重复酒店** | ❌ | **无概念** |
| **合同审核** | ❌ | **无对象** |
| **证件/资料审核** | ❌ | **无文件** |
| **内容/页面审核** | ✅ | `/internal/v1/hotel-autopage/direct-submission-reviews` + `hotel-direct-review.js`（**完整可用**） |
| **客诉/支持** | ⚠️ | 只有 `PrivacyRequestRow`（个人信息权利申请），不是业务支持 |

### 7.2 Findings

| Finding | 说明 |
|---|---|
| `ADM-01` **异常队列不含任何入驻类工作** | 7 个队列全是交易/连接器/风控类 |
| `ADM-02` **30/62 导航项属治理，且不对应真人日常** | 见 inventory §3 |
| `ADM-03` **平台管理端点有未鉴权缺口** | `GET /internal/v1/merge/drift` 200 返回真实业务数据；`GET /internal/v1/connectors/health/all` 200；`GET /internal/v1/p0/design-code-freeze/status` 200；见 §21 |
| `ADM-04` **管理登录页暴露测试模式** | 「当前环境暂未强制 MFA。测试期间可使用用户名和密码登录」 |
| `ADM-05` **`/docs` 与 `/openapi.json` 公开** | Swagger UI 200，全 API schema 852KB 公开 |

**Admin verdict**：**PARTIAL_PRODUCT（交易/风控运营可用） + CONTROL_ONLY（30 项治理） + MISSING（入驻运营 0）**。

---

## 8. Cross-domain journeys

### 8.1 一个真实酒店成为合作伙伴（端到端）

`AGENT: 酒店 → 平台`。这是**最关键的跨域链路**。

```
[1] 打开 /go-app/ 或 /supplier-console/        ✅ 可达（但 / 是 404，无前门）
[2] 注册供应商账号                              ⛔ 全控件 disabled（邮件验证 readiness=false）
[3] 收到验证码                                  ⛔ 邮件服务未就绪
[4] 填主体资料                                  ⛔ 4 个字段要求"资料引用"，无上传
[5] 提交 → 待审                                 ✅ 状态写入
[6] 运营人员看到这条申请                        ⛔ 无队列、无列表、无界面
[7] 运营人员批准                                ⛔ DEADLOCK-01：结构上不可达
[8] 生成/签署合同                               ⛔ 无合同对象
[9] 开通经营后台                                ⛔ 卡在 [7]
```

**结果：该链路 3/9 步可达，且第 7 步是死循环。**

### 8.2 一个消费者订一间酒店

```
[1] 打开 /go-app/                              ✅
[2] 搜索酒店                                    ⚠️ 供给未接通（AOLUGUYA_REAL_INVENTORY_CONFIGURED=false）
[3] 查看详情                                    ⚠️ 返回 hotel_test 夹具
[4] 下单 (POST /v1/offers/{id}/prebook)         ⚠️ 无鉴权，路径存在
[5] 支付 (POST /v1/orders/{id}/payments)        ⚠️ 受 legacy_order_access 保护；真实 PSP 未接通
[6] 查看订单 / 取消 / 退款                       ⚠️ 路径存在，运行时（`AOLUGUYA_REAL_PAYMENT_CONFIGURED=false`）
```

**结果：界面可走，数据面不可信；真实交易未接通。**

### 8.3 一张图片从酒店到公开页面

```
[1] 供应商上传原图 (POST /v1/supplier/properties/{id}/media-uploads)   ✅ 管道完整（受门禁保护 ⇒ 入驻期不可用）
[2] 声明权利 (rights_holder + evidence_reference + DISTRIBUTE_ON_GO)   ✅ 强制
[3] 绑定 (bind, revision 乐观并发)                                      ✅
[4] 提交发布申请 (request_publication, fingerprint 去重)                ✅
[5] 管理员审核 (hotel-direct-review, manifest_sha256 + facts_sha256)    ✅ 完整工作台
[6] 批准 + 发布                                                         ✅
```

**结果：这条链路是完整的 —— 除了第 1 步在供应商入驻完成前不可达。**

### 8.4 支付失败 → 退款 → 对账

路径全部存在（`omnichannel_payment.py` 13 路由、`refund` 20 路由、`reconciliation-worker` 在跑、`admin_queues` 有 `refund_failures` / `payment_reconciliation`）。**但真实 PSP 未接通 ⇒ `NOT_AUDITED`（无法验证成功/失败路径的实际行为）。**

---

## 9. PM Product Architecture

```
PERSONA → JOB TO BE DONE → DOMAIN → CORE JOURNEY → BUSINESS OBJECT → STATE → OPERATOR → SUCCESS CONDITION
```

| Persona | JTBD | Domain | Business Object | Operator | Verdict |
|---|---|---|---|---|---|
| 消费者 | 找到并预订一间房 | Consumer / Hotel | `OfferRow` / `OrderRow` / `PreorderRow` | 系统 + 供应商 | PARTIAL（界面 REAL，供给未接） |
| 消费者 | 管理行程 | Trip / Vault | `ConsumerTripMemberRow` / `ProfileImportJobRow` | 用户自己 | PARTIAL |
| 酒店经营者 | 加入平台并经营 | Supplier / Hotel | **`Application` / `LegalEntity` / `HotelClaim` / `Document` / `Contract` 全部缺失** | **无人** | MISSING |
| GO 运营（交易） | 处理异常与退款 | Ops | `PaymentOrchestrationRow` / `RefundRow` | 运营 | PARTIAL |
| GO 运营（内容） | 审核酒店页面与图片 | Hotel library | `HotelRegistrationDirectRow` / media index | 运营 | **REAL** |
| GO 运营（入驻） | 审供应商 | Supplier | **无对象** | **无工作台** | MISSING |
| GO 风控/治理 | 恢复/信任/预测 | governance | 数十个 `*Row` | 治理岗 | CONTROL_ONLY |

**架构级判断**：GO 的"产品结构图"里，**唯一完整闭合的一列是"内容审核"**（酒店页面/图片）。交易列缺供给与支付；入驻列缺对象与运营；治理列没有服务对象。

---

## 10. Personas / Jobs（全项目）

| Persona | 存在于代码？ | 有 JTBD？ | 有完成路径？ |
|---|---|---|---|
| 消费者（匿名） | ✅ `consumer.py` | ✅ 浏览 | ✅（夹具） |
| 消费者（注册） | ✅ `consumer_identity.py` | ✅ 下单 | ⚠️ |
| 酒店经营者 | ✅ `supplier` 域 | ⚠️ 部分 | ⛔ |
| 酒店员工（第 2 个账号） | ❌ | ❌ | ⛔ |
| 集团 / 第三方代运营 | ❌ | ❌ | ⛔ |
| GO 交易运营 | ✅ | ✅ | ✅ |
| GO 内容审核 | ✅ | ✅ | ✅ |
| GO 入驻审核 | ❌（无界面） | ✅ | ⛔ |
| GO 治理岗 | ✅（30 项） | ⚠️ | ✅（但服务对象不存在） |
| 平台工程/交付 | ✅（28 个 workflow） | ✅ | ✅ |
| 客服/支持 | ❌ | ❌ | ⛔ |

---

## 11. Domain-by-domain product verdict

| Domain | Verdict | 依据 |
|---|---|---|
| Hotel library（建库/来源/联系点/页面版本） | **REAL_PRODUCT** | `hotel_autopage_factory` 38 路由 + 完整模型 + 现场使用 |
| Hotel page 审核 + 媒体授权 | **REAL_PRODUCT** | `hotel-direct-review.js` 完整审核台 |
| Registration / 条款 / 验证码 / 隐私 | **REAL_PRODUCT** | `RegistrationDecisionRow` 逐项决策 + 限流管道 |
| Auth / Session / RBAC | **REAL_PRODUCT** | 会话撤销 + MFA + SSO + CSRF |
| Consumer 界面 | **REAL_PRODUCT** | 现场渲染质量高 |
| Consumer 交易 | **PARTIAL_PRODUCT** | 供给未接通、详情=夹具、支付未接通 |
| Orders（多品类运行时） | **PARTIAL_PRODUCT** | 5 个 `*OrderRuntimeRow` 真实被引用；无真实流量 |
| Suppliers（自营资料域） | **PARTIAL_PRODUCT** | `hotel_partner_core` 字段完整；被门禁封锁 |
| **Supplier onboarding** | **TECHNICAL_PROTOTYPE** | 死循环 + 对象缺失 |
| Flights / Rail / Ride / Rental / Attraction | **PARTIAL_PRODUCT** | 路由与模型存在（13–51 条），供给未接通 |
| Payment / Refund | **FOUNDATION_ONLY** | 编排骨架完整，PSP 未接通 |
| Search / Discovery / Merge / Routing | **PARTIAL_PRODUCT** | merging/routing 是真实资产 |
| Trip / Vault / GO ID | **PARTIAL_PRODUCT** | `personal_travel_vault.py` 32 路由 |
| Mobile | **PARTIAL_PRODUCT** | 3 个 worker 在跑；`mobile.py` 25 路由 |
| Notification | **FOUNDATION_ONLY** | 仅 `ConsumerNotificationRow` + `HostedReservationNotificationRow`；**供应商域无通知** |
| Support / Help | **FOUNDATION_ONLY** | 仅 `PrivacyRequestRow` |
| Reviews / Truth / Rating | **PARTIAL_PRODUCT** | `truth.py` 15 路由；部分未鉴权 |
| Admin 运营（交易/风控） | **PARTIAL_PRODUCT** | 7 个真实队列 |
| Admin 运营（入驻） | **MISSING** | 0 |
| Governance / Recovery / Trust / Forecast / Risk | **CONTROL_ONLY** | **287（文件口径）／305（路径 union）** 路由、无产品结果 |
| Command Center / Control Plane / Delivery | **CONTROL_ONLY** | 28 个 workflow |
| AI / Inference | **FOUNDATION_ONLY** | provider 为空 |
| **Hotel alias / claim / membership / document / contract** | **MISSING / PRODUCT_RULE_UNDEFINED** | 见 PM 专项 §13。⚠️ **口径说明**：这些对象**根本不存在**，因此**不适用 `ORPHAN`** —— `ORPHAN` 仅用于"已建但无人使用"的对象（见 §17 定义）。 |

---

## 12. Product rules missing（跨全项目）

除 PM 专项已列的 15 项（D-1…D-15）外，全项目层面新增：

> **D-15 已按 PM 口径更正（不再是"先建库 vs 先认证"的假二选一）**：真正需要 Product Owner 决定的是 **`SUPPLIER LEGAL-ENTITY VERIFICATION` 与 `HOTEL RELATIONSHIP / CLAIM VERIFICATION` 的阶段边界** —— 各自是什么业务事实、在流程哪一步发生、彼此前置关系如何、主体通过后能做什么、酒店匹配/认领在哪一步、最终什么条件解锁经营后台。含 3 个 PM decision options（Option A 主体先行 / Option B 关系先行 / Option C 并行双闸）。完整表述见 `GO_FULL_AUDIT_ERRATA_20261003.md` E-6，并取代 `GO_SUPPLIER_PM_PRODUCT_AUDIT_20261003.md` §18 中的原 D-15 表述。
> **核心要求不变**：必须消灭 `APPROVE SUPPLIER` requires `APPROVED HOTEL REGISTRATION` 而 `HOTEL REGISTRATION PATH` requires `APPROVED SUPPLIER` 构成的 **cyclic precondition**。

| # | 缺的规则 | 影响域 |
|---|---|---|
| P-1 | **统一产品身份**：GO 到底叫什么？谁是运营主体？四个产品名如何统一？ | 全域 |
| P-2 | **统一入口**：消费者/供应商/运营是否应有前门与互链？ | 全域 |
| P-3 | **真实供给从哪来**：GO 自营？OTA 授权？酒店直连？三者关系未定义 | Consumer / Supply |
| P-4 | **真实支付由谁承担**：平台代收？直付酒店？分账？ | Payment |
| P-5 | **"GO SI / GO Offer / GO 直联 / GO 推荐 / GO 礼遇 / GO Truth / GO 星级" 与交易的关系** | Consumer |
| P-6 | **C 端搜索与 B 端酒店库的供给关系** | Hotel |
| P-7 | **谁承担售后**（平台/供应商/酒店）—— 决定了 dispute 与 refund 的对象模型 | Order / Refund |
| P-8 | **通知的渠道与责任域** | Notification |
| P-9 | **客服体系是否存在** | Support |
| P-10 | **多品类是同一产品还是六个产品**（6 个 vertical 共用订单模型，但运营导航分 6 项） | Vertical |

---

## 13. Product contradictions

| # | 矛盾 | A 方 | B 方 | 证据 |
|---|---|---|---|---|
| C-1 | 供应商能否用草稿条款注册 | 注册页文案「条款正式确认后可提交入驻申请」 | 后端常量 `formal_terms.required_for_account=false` + `account_stage=True` | PM 专项 §7 |
| C-2 | 条款正文能否用于注册同意 | `registration_terms.py` 走 `account_registration_terms_status`（允许） | 条款正文明写「尚未生效，**不供注册勾选**」 | 同上 |
| C-3 | 是否强制 MFA | 管理登录页写「暂未强制 MFA」 | 代码有完整 MFA 绑定/校验流程与 `mfa_required_for_admin` 开关 | 现场截图 + `bff.py:105-107` |
| C-4 | 供应商导航上限 | `config.js` 自称 `partnerPrimaryNavMax: 7` | 实际 10 项 primary + 62 项 hidden | `supplier/config.js` |
| C-5 | 仓库 compose 是否为现场定义 | `docker-compose.business-runtime.yml` 自称 "the GitHub-side equivalent of the Compose file that is running on HK-STAGING-01" | 现场 label 指向 2026-09-06 的另一份文件 + deployctl override | `docker inspect` |
| C-6 | 是否有统一运营后台 | admin nav 62 项 | `/` 404，三个表面互不相链 | 现场 |
| C-7 | 产品名 | `GO 旅行` / `GO 合作伙伴平台` / `GO 全生态运营管理系统` / `GO SI DIRECT` | — | 三份 `index.html` 现场标题 |
| C-8 | 供应商身份 | `IdentityUserRow.supplier_id` 单值（一人一供应商） | `HotelPartnerPropertyRow` / `HotelRegistrationDirectRow` 各自持有 `supplier_id`，语义三分 | inventory §5.2 |
| C-9 | `property_id` 语义 | `CommercialCaseRow.property_id` 存 canonical `hotel_id` | `HotelPartnerPropertyRow.property_id` 是另一 ID 空间 | PM 专项 §13 |
| C-10 | 权限与端点 | 存在 `admin:read/orders/finance/trust/rules/connector/approve` 权限体系 | 两个供应商 decision 端点用 `admin_principal` 完全绕过 | PM 专项 §9 #16 |

---

## 14. Database readiness（全项目）

### A. `DOMAIN_STABLE` — 规则已定、已被真实路径使用，可继续建 / 必须保留

`identity_user` · `auth_session` · `refresh_token` · `registration_challenge` · `registration_rate` · `registration_decision` · `registration_maintenance` · `privacy_request` · `audit_event` · `approval_request` · `hotel_canonical_profile` · `hotel_content_source_snapshot` · `hotel_contact_point` · `hotel_auto_page_version` · `hotel_auto_page_event` · `hotel_registration_go_direct` · `hotel_partner_property` (+ `room_type` / `policy` / `ari_override` / `facility_assignment` / `operational_inbox` / `go_offer_authority`) · 媒体 asset 索引与授权声明 · `offer_merge_decision` · `offer_drift_state` · `offer_drift_event` · `room_external_identity` · `hotel_external_identity` · `property_mapping_candidate` · 5 个 `*OrderRuntimeRow` · `idempotency` · `outbox` / `outbox_dead_letter` · `payment_orchestration` · `refund`

### B. `DOMAIN_PARTIAL` — 可保留/试验，不能视为最终 production contract

`commercial_case`（容器形状对，入驻语义未定） · **supplier 身份表示法**（`IdentityUserRow.supplier_id` 单值 + `supplier_id` 三分语义 —— 这是**表示法**层面的 `PARTIAL`；**正式的 Supplier 领域实体本身不存在，见 C 类**） · `supplier ↔ hotel` 关系 · `supplier_connector_onboarding` / `connector_credential` · `hotel_partner_change_request`（决策面缺失） · `risk_event_runtime` / `risk_evidence_runtime` / `risk_remediation` · `judgment_*` · `recommendation_decision` · `review_session` / `review_tag` · `payment_order_root*` / `payment_order_fact_binding`（真实 PSP 未接通前无法冻结）

> ⚠️ **名词口径（须与 §27 RP-1 一致）**：`supplier_id` **表示法** = `PARTIAL`/`REPLACE`（存在但模型错误）；**Supplier 领域实体** = `MISSING`/`NEW`（不存在）。同一名词不得同时被读成"存在待改"与"根本不存在"。

### C. `PRODUCT_RULE_UNDEFINED` — **现在建表 = 用 schema 替产品拍板，应暂停**

`hotel_claim` · `ownership_dispute` · `hotel_alias` / `hotel_name_history` · `contract` / `contract_version` · `legal_entity` · `document` / `document_version` · `supplier_membership` / `staff` / `invitation` · **`supplier` 领域实体本身**（承载成员/关系/合同的正式实体） · `supplier_notification` · `document_retention_policy` · `onboarding_sla_policy` / `reviewer_assignment` · `review` / `review_finding` · `offboarding`

### 静态引用分析结果（563 model）

| 分类 | 数量 |
|---|---|
| 在应用源码中被引用 | **560** |
| 仅测试引用（`TEST_ONLY`） | 1（`hotel_fare_rule_runtime` / `FareRuleRow`） |
| 无任何引用（`ORPHAN`） | 2（`connector_property_mapping_audit`、`stay_credit_redemption_quote`） |
| service 引用 | 282 |
| route 引用 | 57 |
| worker 直接引用 | 0 |

> **说明**：孤儿表只有 3 张，说明"建了没人用"不是主要问题；**主要问题是"建了、service 在用、但没有任何真人可达路径"**（即 §16 的 `STATE_MACHINE_WITHOUT_JOURNEY`）。引用计数无法区分这两者，因此本节的 A/B/C 分类依据是**产品规则是否已定**，不是引用计数。

### 结构性缺陷

1. **JSON blob 代替领域模型**：`CommercialCaseRow.payload_json` 承载整条入驻业务；`HotelCanonicalProfileRow.canonical_json` 承载全部酒店事实；`HotelPartnerPropertyRow.{address,contacts,legal,operations,poi}_json`。后果：**无法 diff、无法约束、无法做 item-level finding。**
2. **同名不同义 ID**：`property_id` 在两个表里指两种东西（§13 C-9）。
3. **`supplier_id` 语义过载**：账号容器 / 酒店持有者 / 注册方三义合一。
4. **巨型单文件**：`db/models.py` = 8,195 行 563 个类，无 domain 拆分。

---

## 15. Engineering architecture

```
────────────────────────────────────────────────────────────────────
 3 个前端 mount（无统一入口，/ → 404）
   /go-app/    consumer  (349 行 app.js + 12 模块)
   /supplier-console/  supplier (10 primary + 62 hidden)
   /go-admin/  admin (62 nav)
        │  共享 /console-assets/ (shared/app.js 897 行 — 三端共用同一个 SPA 文件)
        ▼
 FastAPI 单体（1082 路由 / 120 route 文件 / 710 internal / 742 写）
   中间件: Sprint1R(Audit) → Sprint1U(CSRF-only) → Sprint1V(Observability)
        ▼
 service 层（126 文件）—— 业务逻辑所在
        ▼
 SQLAlchemy models（563 类 / 1 个 8,195 行文件）
        ▼
 PostgreSQL（外部，564 表，alembic 0145）
 + Redis（队列/缓存） + 本地媒体缓存目录（GO_MEDIA_CACHE_DIR）
        ▼
 14 个 worker 模块（7 个在 HK 运行）
────────────────────────────────────────────────────────────────────
 独立层：command-center/ control-plane/ deploy/ packaging/ deliverables/ evidence/
         + 34 个 GitHub Actions workflow（~28 个属交付/治理）
```

### 架构问题

| Finding | 说明 |
|---|---|
| `ARCH-01` **三端共用同一个 SPA 文件** | `shared/app.js` 897 行同时服务 consumer / supplier / admin 的视图分发（`route` 函数里 60+ 个 `if(item?.custom===...)`）。这是**最强的隐式耦合**。 |
| `ARCH-02` **巨型 models.py** | 563 类 / 8,195 行 / 583KB，无 domain 边界。 |
| `ARCH-03` **鉴权有两种不兼容的表达方式** | router 级 `dependencies=[...]` / 装饰器级 `dependencies=[...]` / 签名级 `Depends(...)` 三处并存，且**极易漏**（§21 的 66 条无显式依赖即漏掉的结果；分类后其中 35 条为真实缺陷）。 |
| `ARCH-04` **中间件的名字与行为不符** | `Sprint1USecurityMiddleware` 只做 CSRF；不认证。名字暗示它是安全门。 |
| `ARCH-05` **跨域状态机重复** | 至少三套"审批/状态"语义并存：`ApprovalRequestRow`（双签）、`CommercialCaseRow.state`（案例）、`HotelRegistrationDirectRow.state`（注册）、`HotelPartnerChangeRequestRow.state`（变更）、`ReviewSessionRow`。无统一状态机抽象。 |
| `ARCH-06` **业务规则泄漏到前端** | `shared/app.js:129` 在 JS 里维护"字段定义表"（含"唯一主键/受控状态机/VERIFIED"等后端语义）。 |
| `ARCH-07` **枚举漂移** | `ADMIN_STATE_LABELS` / `SUPPLIER_STATE_LABELS` / `SUPPLIER_LABELS` / `ADMIN_LABELS` 四张 JS 词表需要手工与 563 张表同步。 |
| `ARCH-08` **magic string** | 129 个以大写枚举字符串作为 `detail=` 的 HTTP 错误体；前端只有 ~15 个有映射（见 §17）。 |

---

## 16. Reachability / dead flows

**方法**：对每个状态机、每个端点、每张表，问"正常入口能不能走到"。

| 类型 | 发现 | 证据 |
|---|---|---|
| `CYCLIC_PRECONDITION` | **供应商入驻审批**：批准需要 registration；registration 需要 hotel_id；hotel_id 需要 console；console 需要批准 | PM 专项 §1 ① |
| `TEST_INSERT_REQUIRED` | 同一流程：开发方测试必须直接 `s.add(...)` 插入 `HotelCanonicalProfileRow` + `HotelRegistrationDirectRow(state='APPROVED')` | `tests/test_supplier_onboarding_hk_unified.py:92-114` |
| `NO_UI_CALLER` | `/internal/v1/supplier-onboarding/{id}/profile-decision` 与 `contract-decision`：前端引用 **0** | inventory §4 |
| `NO_CALLER` | `PUT /internal/v1/supplier-connectors/{id}/credentials`：前端引用 0，但**无鉴权可达**（既是 orphan 又是暴露面） | inventory §4.4 |
| `STATE_MACHINE_WITHOUT_JOURNEY` | `HotelPartnerChangeRequestRow`：`HIGH_RISK={LEGAL,ADDRESS,BRAND,QUALIFICATION}` 定义正确、记录会创建，**但无任何代码把 state 从 SUBMITTED 推进** | PM 专项 §6.3 |
| `IMPOSSIBLE_PRECONDITION` | `decide_profile(APPROVE)` 的 `registration_direct_id` 参数必须由调用者提供，而 `SupplierReviewBody` 不校验其存在性 | `bff.py:215-218` |
| `ADMIN_ONLY_WITHOUT_ADMIN_UI` | 治理族路由（287–305 条）中，admin nav 覆盖的只是子集；大量路由无 UI 调用方 | inventory §3/§4.6 |
| `UNREACHABLE_STATE` | 供应商 `supplierOnboardingView` 未处理 `CONTRACT_PENDING` ⇒ 落入 `else` 显示原始枚举（死路） | 前序专项 §3 |
| `ORPHAN_FEATURE` | `HotelPartnerChangeRequestRow`（写无人读）、`connector_property_mapping_audit`、`stay_credit_redemption_quote` | inventory §14 |
| `WRITE_ONLY_FLOW` | 同上变更申请；以及 `POST /internal/v1/judgment-hooks/process-pending`（可触发，无消费者） | — |
| `READ_ONLY_PRODUCT` | `/go-admin/` 的 `adminSupplierRegistry` = 只读 registry 表，无动作 | `shared/app.js:521` |
| `DEAD_END` | `/` → 404（无前门）；供应商入驻兜底页只有「退出登录」 | 现场 + 前序专项 |

---

## 17. API ↔ Frontend integration

### 17.1 覆盖对比

| 侧 | 数量 |
|---|---|
| 后端路由（解析） | 1082 |
| 前端显式调用的路径（`shared/app.js` + `admin/*.js` + `consumer/*.js` + `supplier/*.js`） | 约 260（`/v1/` + `/bff/` + `/internal/`） |

⇒ **约 75% 的后端路由没有任何前端调用方** —— 这是一个 **`INVESTIGATION_SIGNAL`**，**不得**直接解释为"75% 的 API 是废物"。

> **`NO_FRONTEND_CALLER != ORPHAN`**
> 无前端调用方可能包含：worker、webhook、机器对机器回调、自动化、外部集成、内部 service 动作。
> 只有**同时**满足 no frontend caller + no worker + no machine caller + no integration caller + no test/runtime product path，才可判定为 `ORPHAN`。
> 佐证：worker 模块对 model class 的直接引用为 0（全部经 service 层），说明"用引用关系推断调用关系"本身不可靠 —— 因此该统计只能作信号，不能作结论。

### 17.2 Finding

| Finding | 说明 | 证据 |
|---|---|---|
| `INT-01` **错误原因被生产但被丢弃** | `/bff/auth/supplier/registration-terms` 返回 `release_gate.registration_verification.reason`，前端 `grep release_gate` **0 命中** | 前序专项 §12 M-2 |
| `INT-02` **原始后端错误码直接上屏** | `userFacingError` 映射 8 码、`GORegistrationVerification.message` 映射 7 码，兜底 `return error?.message`。共 129 个 `detail=` 枚举中约 15 个有映射 | `shared/app.js:47`；`registration-verification.js:3-11` |
| `INT-03` **静默失败** | 条款接口 503 时注册页把错误写进已不在 DOM 的 `#loginErr` | 前序专项 §10 |
| `INT-04` **GET 无对应 POST / POST 无回读** | 例：`GET /internal/v1/supplier-connectors` 可读，但其 `POST ""`（create）无 UI；`POST /internal/v1/connectors/{id}/certify` 无对应读端点 | inventory §4 |
| `INT-05` **状态更新不通知** | 供应商入驻 5 个状态迁移函数只写 `updated_at`，不写 outbox、不发信 | PM 专项 §11 |
| `INT-06` **无参数校验的审批端点** | `SupplierReviewBody.registration_direct_id` 可选，但 APPROVE 时必须有效 | `bff.py:70-73` |

---

## 18. Database / model audit

见 §14 + inventory §1/§14。

补充量化：

| 项 | 值 |
|---|---|
| model 类 | 563 |
| live tables | 564 |
| migration 文件 | 146（对应 564 表 ⇒ 平均每 migration ~3.9 表） |
| 最大单文件 | `db/models.py` 8,195 行 |
| JSON blob 承载业务事实的表 | `commercial_case`、`hotel_canonical_profile`、`hotel_partner_property`、`hotel_content_source_snapshot`、`hotel_auto_page_version`、`hotel_registration_go_direct.official_supplement_json` 等 |
| 表名与类名一致的 | 563/563（100% 显式 `__tablename__`）✅ |
| 孤儿表 | 2 |
| 仅测试用表 | 1 |
| 无 `UploadFile` 路由 | 全库 0（唯一上传走 base64 JSON body） |

---

## 19. Test quality audit

### 19.1 规模

| 项 | 值 |
|---|---|
| Python 测试文件 | 399 |
| Python 测试函数 | 2401 |
| JS/CJS test | 8 |
| CI workflow | 34（约 6 个跑 pytest） |

### 19.2 问题模式（带真实样例）

| 模式 | 样例 | 为什么危险 |
|---|---|---|
| **直接 INSERT DB 绕开产品路径** | `tests/test_supplier_onboarding_hk_unified.py:92-108`：`s.add(HotelCanonicalProfileRow(...))` + `s.add(HotelRegistrationDirectRow(state='APPROVED'))`，测试名 `test_supplier_onboarding_requires_existing_hotel_truth_and_contract` | **测试名字自己承认"必须先有酒店真相"**；绿灯只证明"这套强耦合关系被正确断言"，不证明任何供应商能走通 |
| **83 个测试文件 / 498 处 `.add()`** | `grep -rn "s.add(\|session.add(\|SessionLocal.begin()" tests | 大量前置状态由测试构造，而不是由产品生成 |
| **只证明 fail-closed，不证明 success path** | 供应商入驻的 negative case（`APPROVED_HOTEL_REGISTRATION_REQUIRED`）被断言，positive case 靠手工插数据 | 负向测试全绿 ≠ 正向可达 |
| **验收用合成主体** | `hotel_page_production_acceptance.py:306`：`register_for_go_direct(target, f"rc13-supplier-{batch_id}", ...)` | GO Direct 注册/审批链路**从未遇到真实供应商** |
| **验收跑完即抹掉** | 同文件 212–218 行有 `delete(HotelRegistrationDirectRow)...` | 验收不留下可观察的业务结果 |
| **jsdom 式 UI 测试** | `tests/test_supplier_registration_ui.cjs` 用 `vm.createContext` + 手写 `element()` 桩，断言 `location.hash === '/one-click-build'` | 断言的 hash 当前**不可达**（`enterConsole` 先拦截）—— 测试与产品行为脱节 |
| **delivery 测试被当成 product 测试** | 34 workflow 中 ~28 个验证 canonical/receipt/admission/VERIFY | 这些断言"交付正确性"，与"产品正确性"无关（§20） |

### 19.3 结论

> **最容易让 Product Owner 误判的绿灯**：
> 1. `hk-unified-registration-acceptance.yml` 通过 ⇒ 看起来"注册可用"，其实该测试**自己插数据**。
> 2. `canonical-*` / `command-center-*` 系列通过 ⇒ 看起来"系统就绪"，它们只证明**交付链路自洽**。
> 3. `test_supplier_registration_ui.cjs` 通过 ⇒ 看起来"UI 链路通"，它断言的是一个**当前不可达的 hash**。
> 4. 2401 个测试函数全绿 ⇒ 看起来"覆盖充分"，其中 **83 个文件绕开产品路径**。

---

## 20. Runtime / source / delivery audit

**三类正确性必须分开：**

| 类别 | 结论 | 证据 |
|---|---|---|
| **SOURCE_CORRECTNESS** | ✅ main 可 fetch、SHA 明确、`LIVE_BYTES == PR376_SOURCE`（前序 9/9 sha256 全等） | `rev-parse origin/main` = `7e7aedd5…` |
| **DELIVERY_CORRECTNESS** | ✅ 8/8 业务服务同一镜像 `sha256:01632507d0d3…`；`api` healthy；alembic `0145 (head)`；`/health` ok | docker inspect / alembic current |
| **PRODUCT_CORRECTNESS** | ❌ 与服务/镜像无关：注册被阻断、入驻死循环、详情页是夹具、供给与支付未接通 | 前序专项 + §5/§8 |

### Finding

| Finding | 说明 |
|---|---|
| `DEL-01` **RUNTIME_POINTER_DRIFT** | repo pointer = PR320；现场 = PR376；openapi 972→1065 |
| `DEL-02` **COMPOSE_DEFINITION_DRIFT** | 现场用 2026-09-06 的 compose + deployctl override；仓库"canonical" compose 文件未被使用 |
| `DEL-03` **CURRENT_STATE_DOC_DRIFT** | `GO_CURRENT_STATE.md` / `CONTEXT_CHECKPOINT.json` 绑定 `8ffcde66…`（2026-09-14），落后 ~19 天、数百提交 |
| `DEL-04` **CANDIDATE_DOC_STALE** | `CURRENT_CANDIDATE.json` 是 DEPTH48 时代产物（`pr: 52`、`ci: FAILED_BEFORE_ANY_STEPS`、`RUNTIME_PENDING`） |
| `DEL-05` **34 CI / ~6 测测试** | 交付/治理流水线数量是测试流水线的 5 倍 |
| `DEL-06` **`/docs` + `/openapi.json` 公开** | Swagger UI 与 852KB schema 无需鉴权 |

---

## 21. Security — required vs premature

### 21.1 `SECURITY_REQUIRED`（真实故障可预防）

| # | 发现 | REAL_FAILURE_PREVENTED | 严重性 | 证据 |
|---|---|---|---|---|
**口径前提**：66 条"无显式鉴权依赖"是**未分类的原始枚举**，逐条复核后分类为 `PUBLIC_BY_DESIGN` 19 / `AUTH_ENFORCED_IN_BODY` 2 / `MACHINE_AUTH_IMPLEMENTED` 5 / **`AUTH_REQUIRED` 35** / `UNKNOWN` 5。下表只列**已确认应鉴权却匿名可达**的部分。完整逐条表见 `UNAUTHENTICATED_ROUTE_CLASSIFICATION_20261003.md`。

| # | 发现 | REAL_FAILURE_PREVENTED | 严重性 | 证据 |
|---|---|---|---|---|
| `SEC-01` | **35 条 `AUTH_REQUIRED` 路由匿名可达，其中 25 条在 `/internal/*`** | 未授权者读取内部业务数据、触发后台作业、**写入连接器凭据**、**审批酒店映射**、变更订单/SLA/房型映射 | **P0** | 逐条分类表 + 现场 GET 证据 |
| `SEC-02` | **`onboarding.py` 导入鉴权工具但从未使用**（根因 A） | 同上；且这是**可复制的模式**（`outbox.py`/`routing.py`/`merge.py`/`judgment.py`/`connectors.py`/`ops.py`/`truth.py` 同类遗漏） | **P0** | `api/routes/onboarding.py:1-27` |
| `SEC-03` | **`Sprint1USecurityMiddleware` 只做 CSRF、不认证**（根因 B） | 无 cookie / 无 Authorization 的请求直达 handler | **P0** | `main.py:234-268` |
| `SEC-04` | **`GET /internal/v1/merge/drift` 匿名返回真实业务数据** | 泄露酒店/连接器/房型映射真实事实 | **P0** | 现场 200，含真实 `hotel_id: HRBUB`、`connector_id: conn_aoluguya_hosted_test` |
| `SEC-05` | **`/openapi.json`（852,802 B）+ `/docs`（Swagger）公开** | **`ATTACK_SURFACE_AMPLIFIER`** —— **本身不构成漏洞**；风险来自它与 `SEC-01` 的匿名写/读端点**组合**时放大攻击面。若产品有意提供 public API docs，不应自动判错 | P1 | curl 200 |
| `SEC-06` | **runtime 容器 env 中存在第三方 API credential** | **`CREDENTIAL_EXPOSURE_SCOPE_INCREASED`** —— 用环境变量承载 runtime secret 是常见且可接受的部署方式，**不是设计错误**。已知事实：该值在本次审计中进入了本地命令输出，越过了最小 runtime exposure boundary | **P1** | 容器 env；**值为避免二次扩散不复述**。建议动作：**ROTATE**（不新增 KMS/HSM/Vault） |
| `SEC-07` | **`POST /internal/v1/demo/orders/{order_id}/complete-stay` 匿名可达** | 可变更订单结算状态；其 docstring 自述「Sprint 1X deterministic E2E helper. Not a public production fulfillment endpoint.」 | P1 | 源码 |
| `SEC-10` | **`POST /v1/offers/{offer_id}/prebook` 匿名可达** | 无身份即可创建真实预占（占用库存） | P1 | `hotel.py:59-62`（handler 无任何鉴权调用） |
| `SEC-11` | **`POST /v1/reviews/{review_id}/{star,tags,content}` 匿名可达** | 可篡改任意评价的评分/标签/正文 | P1 | `truth.py:61-73` |
| `SEC-12` | **`GET /v1/reviews/pending?account_id=…` IDOR** | `account_id` 由调用者提供且**默认 `acct_demo`**；无鉴权 ⇒ 传任意 account_id 可读他人在待评价列表 | P1 | `truth.py:55-56`；现场 200 `{"data":[]}` |
| `SEC-09` | **管理登录页明示测试模式、未强制 MFA** | 管理面弱口令风险 | P2 | 现场截图 |
| ~~`SEC-08`~~ | ~~`GET /v1/hotel-media/{asset_id}` 无归属校验~~ | **REVOKED（撤回）**：复核发现该端点**已有正确门禁** —— `media_svc.content_path(..., require_publishable=True)` + `catalog_scope.require_hotel` + 显式拒绝 `source_type=='HOTEL_DIRECT_UPLOAD'`（供应商直传图片必须走审核页）。**原判断错误，予以撤回。** | — | `hotel_autopage_factory.py:89-99` |

### 21.2 `PREMATURE_SECURITY_CONTROL`（当前规模下收益低）

以下**不是错误**，只是**在"没有真实用户"的阶段投入产出比低**，且已占用大量工程：

- 恢复域的 **信任平面独立与容灾 / 联邦信任执行 / 信任传播与恢复 / 信任混沌与就绪 / 持续混沌与豁免 / 身份重签发 / 凭证授权**（单域 290 路由）
- **预测模型主备治理 / 预测漂移刷新 / 预测训练可复现 / 预测制品供应链 / 预测服务证明**（97 路由）—— 预测需要历史样本，当前样本量≈0
- **豁免暴露与技术债 / 异常债务清理 / 企业风险组合/偏好/预测**（121 路由）
- **对"尚不存在的注册文件"做留存期/跨境/接收方清单级别的门禁**

**判断依据**：这些控制的 `REAL_FAILURE_PREVENTED` 都是**假设未来场景**，而当前已存在**真实且正在发生的故障**（注册不可用、入驻不可达、35 条应鉴权却匿名可达的路由、runtime credential 建议轮换）。

---

## 22. Performance / maintainability

| # | 发现 | 证据 | 判定 |
|---|---|---|---|
| `PERF-01` | **base64 上传大文件** | `hotel_partner_media_upload.upload` 收 `content_base64`，单文件上限走 base64 长度校验 ⇒ 传输体积膨胀 ~33%，且整包在内存 | 现实问题（图片可达数十 MB） |
| `PERF-02` | **`admin_queues` 无分页、7 个全表条件查询** | `operational.py:113-124`，每队列 `LIMIT` 但无 offset/keyset | 规模增长后变慢 |
| `PERF-03` | **`/openapi.json` 852,802 B 每次动态生成** | 现场实测体积 | 可缓存但不小 |
| `PERF-04` | **`shared/app.js` 897 行单文件三端共用** | 任一端改动都触发全端加载 | 维护成本 |
| `PERF-05` | **`db/models.py` 8,195 行** | 单文件 | 维护成本 + import 成本 |
| `PERF-06` | **`_factory_flags` 等函数在单次请求内多次全表扫描** | `hotel_autopage_factory.py` 内 `select(...)` 无 limit | 中风险 |
| `PERF-07` | **`GET /internal/v1/merge/drift` 未鉴权且无分页** | 现场返回列表 | 与 SEC-04 叠加 |
| `PERF-08` | P95 / 压测证据 | **`UNKNOWN`** —— 未见现场指标端点数据（`/metrics` 存在但未采集） |

---

## 23. Control Ahead of Product

**判定：`CONTROL_AHEAD_OF_PRODUCT = YES`（严重）**

| 证据维度 | 治理侧 | 产品侧 |
|---|---|---|
| API 路由占比 | 治理族 = **287（文件口径，26.5%）／305（路径 union，28.2%）**；**691 为四类非互斥求和，不作占比用** | 供应商入驻 = **2** |
| Admin 导航 | 治理类 **30 项连续** | 供应商入驻审核 **0 项** |
| CI workflow | 交付/治理 **~28** | 跑测试 **~6** |
| 代码体量 | `models.py` 8,195 行（治理相关占多数） | `supplier_onboarding_state.py` 188 行 |
| 现场服务 | 3 个 worker 是 recovery/judgment/reconciliation | 0 个 worker 服务入驻 |
| 权限体系 | 7 个 `admin:*` 权限 | 入驻审批端点**绕过权限体系** |
| 治理门禁 | 对"还不存在的注册文件"要求跨境/留存/接收方清单 | 文件上传**不存在** |

**这不是"安全做得太严"，而是：产品侧没有定义，所以工程把能力投到了不需要产品定义的地方。** 治理能力（审计/双签/审批）本身有价值（见 §3 #7），但它们解决的是"已经存在的东西别出错"，而当前阶段的问题是"那个东西还不存在"。

---

## 24. Deferred Core Requirements

**判定：`DEFERRED_CORE_REQUIREMENT = YES`**

以下均已确认缺失，但都被当"以后再做"，而它们不是 nice-to-have：

| # | 被延后的核心能力 | 为什么它是 P0 | 已存在但未用于此的能力（说明不是做不到） |
|---|---|---|---|
| 1 | **文件上传（营业执照/身份证明/合同）** | 没有它，"提交主体资料"语义为空 | `hotel_partner_media_upload.py` 完整上传管道 |
| 2 | **供应商入驻审核台 + 队列** | 没有它，申请提交后无人知道它存在 | `hotel-direct-review.js` 完整审核台 |
| 3 | **酒店判重 / 认领** | 上线首日即遇"这家已被别人注册" | `HotelExternalIdentityRow`/`PropertyMappingCandidateRow` 已存在（用于供给映射） |
| 4 | **合同对象** | 唯一有法律约束力的产物，现在只是字符串 | `ApprovalRequestRow` 双签框架 |
| 5 | **找回密码** | 全库 0 命中 | 认证体系完整 |
| 6 | **入驻结果通知** | 用户只能反复登录猜结果 | `OutboxRow` + 7 个 worker 在跑 |
| 7 | **变更 / 续签 / 退出** | 已上线酒店的日常必需 | `HotelPartnerChangeRequestRow` 已建 |
| 8 | **多酒店 / 多员工 / 集团** | 直接决定 `identity_user` 表结构，越晚改代价越大 | — |
| 9 | **主体法定标识（USCC）** | 无法在法律上唯一确定主体，也无法判重 | — |
| 10 | **真实供给与支付接入** | C 端界面背后没有真实库存与收款 | `AOLUGUYA_*` / Alipay 代码已存在 |

**共同模式**：`TABLE EXISTS → 当成功能完成`；`API EXISTS → 当成功能完成`（§26）。

---

## 25. KEEP

| # | 资产 | 理由 |
|---|---|---|
| K-1 | 酒店库（canonical / source snapshot / contact point / auto page version） | 规则稳定、现场在用、有来源与授权 |
| K-2 | 酒店页面审核工作台（`hotel-direct-review.js` + `hotel_direct_submission_review`） | 完整、含版本守卫与竞态保护，**可直接作为其它审核台的蓝本** |
| K-3 | 媒体上传管道的**工程形状**（校验/去重/原子写/并发） | 复形状，不复公开媒体语义 |
| K-4 | 注册验证码管道 | 质量高于多数商业实现 |
| K-5 | 逐项条款同意记录 `RegistrationDecisionRow` | 全链路最产品级的一块 |
| K-6 | 认证 / 会话 / 令牌（含 `token_version` 撤销、MFA、SSO、CSRF） | 模型完整 |
| K-7 | `CommercialCaseRow` 通用案例容器 + `ApprovalRequestRow` + `AuditEventRow` | 形状正确、与业务解耦 |
| K-8 | 房型映射 / Offer 合并 / 漂移（`OfferMergeDecisionRow` 等） | 真实资产 |
| K-9 | 5 个多品类订单运行时 + `IdempotencyRow` + Outbox | 结构正确 |
| K-10 | **C 端界面** | 现场渲染质量高，是真资产（需补真实供给） |

---

## 26. REFACTOR

| # | 对象 | 为什么不是 KEEP 也不是 REPLACE |
|---|---|---|
| R-1 | **鉴权表达方式** | 方向对，但三处并存（router 级 / 装饰器级 / 签名级）导致 66 条无显式依赖（分类后 35 条为真实缺陷）⇒ 收口为统一策略（router 级默认 + 显式豁免清单） |
| R-2 | `Sprint1USecurityMiddleware` | 名字与行为不符；应改名并拆出真正的认证层 |
| R-3 | `db/models.py`（563 类单文件） | 内容有价值，但必须按 domain 拆分 |
| R-4 | `shared/app.js`（897 行三端共用） | 应拆为三端独立入口 + 共享组件 |
| R-5 | 前端枚举词表（4 张手写表） | 应改为由后端 schema 派生 |
| R-6 | 错误码映射（129 个 `detail=`、~15 个有映射） | 应改为**后端返回可展示文案 key**，前端统一渲染 |
| R-7 | `commercial_case` 的 `payload_json` | 容器保留，但入驻业务必须从 blob 提升为字段 |
| R-8 | admin nav（62 项平铺） | 需按"日常 / 治理 / 交付"分组，否则运营找不到工作 |
| R-9 | `admin_queues` | 方向对（平台级队列），需补分页 + 业务队列 |

---

## 27. REPLACE

| # | 对象 | 概念对但实现/模型错，继续补会越来越贵 |
|---|---|---|
| RP-1 | **供应商身份模型**（`IdentityUserRow.supplier_id` 单值 + `supplier_id` 三义） | 需换成 `supplier` 实体 + `membership` + `supplier↔hotel` 关系表 |

> ⚠️ **关于"supplier entity"的口径说明（避免同一名词同时出现在 PARTIAL 与 NEW）**：这里要区分**两件不同的事**，它们状态不同、处置也不同 ——
> - **`supplier_id` 表示法 / 供应商身份语义**（现有 `IdentityUserRow.supplier_id` 单值 + `supplier_id` 在 `HotelPartnerPropertyRow` / `HotelRegistrationDirectRow` 上语义三分）→ **`PARTIAL` / `REPLACE`**：概念存在、也在被使用，但模型错误、继续补会越来越贵。
> - **正式 Supplier 领域实体**（一个可承载成员、关系、合同、状态的 `supplier` 表本身）→ **`MISSING` / `NEW`**：**它根本不存在**，不是"存在但重复"。
> - 因此 RP-1 的准确意思是"**把现有的 `supplier_id` 表示法替换/升级为一个正式 Supplier 实体的过程**"，而不是"删除一个已经存在的实体"。
| RP-2 | **供应商入驻状态机**（`CommercialCaseRow.state` + blob） | 需换成显式 `application` 对象 + item-level review |
| RP-3 | **供应商合同**（两个字符串） | 需换成 `contract` / `contract_version` 对象 |
| RP-4 | **`property_id` 语义**（两个表同名不同义） | 需拆名为 `canonical_hotel_id` vs `partner_property_id` |
| RP-5 | **酒店变更申请**（只写不读） | 需补决策面，或删除该表避免误导 |

---

## 28. DELETE

> **每一个 DELETE 都必须给出 REAL_REASON / DEPENDENCY / RISK / RECOVERY。** 本节不主张立刻删代码，只主张**停止维护与停止扩张**。

| # | 对象 | REAL_REASON | DEPENDENCY | RISK | RECOVERY |
|---|---|---|---|---|---|
| D-1 | **恢复/信任/混沌/预测/豁免类治理导航（admin 第 11–40 项，约 30 项）** | 服务对象（真实流量与历史样本）不存在；占约 26.5% 的路由与 30 项导航 | 部分被 `recovery-worker` / `judgment-worker` 引用 | 删代码会牵动 worker；**故只主张从导航与路线图中移除，代码冻结** | Git 历史完整可恢复 |
| D-2 | **重复的产品表面**：`/supplier-console/` 与 `/go-admin/` 里内容重叠的治理页 | 同一功能两个入口，维护成本翻倍 | 低 | 低 | 保留一个入口 |
| D-3 | **`hotel_fare_rule_runtime`（仅测试引用）** | 无应用引用 | 仅测试 | 低 | 测试可改 |
| D-4 | **`connector_property_mapping_audit` / `stay_credit_redemption_quote`（孤儿表）** | 无任何引用 | 无 | 低 | 可重建 |
| D-5 | **`GET /internal/v1/demo/orders/{id}/complete-stay`** | 名字即"demo"，且未鉴权 | 无产品调用方 | 低 | 删除或加鉴权 |
| D-6 | **`/docs` + `/openapi.json` 的公开访问** | 攻击面放大器 | 无 | 低 | 改为鉴权或仅内部 |

---

## 29. NEW

| # | 真实业务需要但当前不存在 |
|---|---|
| N-1 | `supplier` 实体 + `legal_entity`（含 USCC） |
| N-2 | `supplier_membership` / `staff` / `invitation`（多用户、离职交接） |
| N-3 | `hotel_claim` / `ownership_dispute`（认领与争议） |
| N-4 | `hotel_alias` / `hotel_name_history`（改名/换牌） |
| N-5 | `document` / `document_version`（**受限文件域**，独立于公开媒体） |
| N-6 | `contract` / `contract_version` |
| N-7 | `notification`（供应商域）+ 通知订阅规则 |
| N-8 | 找回密码 |
| N-9 | **供应商入驻审核台 + 待审队列** |
| N-10 | 统一产品入口与前门（`/`） |
| N-11 | C 端真实供给接入（替换夹具） |
| N-12 | 真实支付接入 |
| N-13 | 客服/工单对象 |
| N-14 | **统一鉴权策略层**（消除「无显式依赖」导致的漏网） |

---

## 30. Recommended GO recovery plan

**原则：Occam Razor。顺序不可颠倒。**

```
REAL USER BLOCKER  →  REAL OPERATOR BLOCKER  →  PRODUCT RULE  →
DATA MODEL  →  IMPLEMENTATION  →  ONLY THEN GOVERNANCE
```

1. **止血安全（NOW）**：处理 **35 条已确认应鉴权却匿名可达**的路由（优先 25 条 `/internal/*`，特别是凭据写入与映射审批）+ **轮换**被暴露的第三方 credential + 决定 `/docs` 是否公开（作为**放大因子**处理，而非漏洞本身）。详见 `GO_FULL_AUDIT_ACTION_MAP_20261003.md`。
2. **解掉 B 端 cyclic precondition（NOW）**：按更正后的 **D-15**（`SUPPLIER LEGAL-ENTITY VERIFICATION` 与 `HOTEL RELATIONSHIP / CLAIM VERIFICATION` 的阶段边界，3 个 PM options）由 Product Owner 作出决定，并据此消除 `APPROVE SUPPLIER ⇄ APPROVED HOTEL REGISTRATION` 的互为前置。这是唯一挡住整条 B 端链路的门。
3. **给运营一个工作台（NEXT）**：供应商入驻队列 + 审核台（照抄 `hotel-direct-review.js`）。
4. **把"入驻"从 blob 里拿出来（NEXT）**：`application` / `document` / `review_finding` 显式化。
5. **补产品规则（NEXT）**：PM 专项 §18 的 15 项 + 本报告 §12 的 10 项。
6. **补真实供给与支付（NEXT）**：否则 C 端界面再好也只是展示品。
7. **才轮到治理（LATER）**：把已有治理资产接入真实业务对象。

---

## 31. What should stop immediately

1. **停止继续扩张治理/恢复/信任/预测域**（287–305 路由、30 导航项）—— 它们的服务对象不存在。
2. **停止在未决产品规则上建表**（PM 专项 §14 C 类 12 个对象）。
3. **停止把"表/API/状态/测试/Evidence 存在"当作功能完成**（§33）。
4. **停止在"供应商入驻"之外的生产面上保留无鉴权内部路由**。
5. **停止在 `/docs` 公开完整 API schema**。
6. **停止维护 depot 里已失效的 runtime pointer 与 current-state 文档** —— 要么刷新，要么标记为历史。

---

## 32. What should continue immediately

1. **酒店库 / 酒店页面 / 媒体授权 / 审核台** —— 继续建，这是唯一已验证的产品资产。
2. **注册 / 条款 / 验证码 / 认证会话** —— 继续用。
3. **C 端界面** —— 继续（但要接真实供给）。
4. **支付编排骨架** —— 继续（但要接真实 PSP）。
5. **多品类订单运行时** —— 继续。
6. **runtime 交付链路的可验证性**（字节级 identity）—— 继续，但要把 pointer 与文档刷新机制自动化，否则一直是 drift。

---

## 33. "框架完成 = 功能完成" 模式（根因分析）

本轮特别要求的根因识别。**七种模式全部在仓库中找到真实样例。**

| # | 模式 | 真实样例 | 后果 |
|---|---|---|---|
| 1 | **TABLE EXISTS → 功能完成** | `hotel_partner_change_request` 表存在且会写入 ⇒ 看起来"变更管理完成"；实际 `state` 永远停在 `SUBMITTED` | 换牌/改名/换主体永久无人处理 |
| 2 | **API EXISTS → 功能完成** | `/internal/v1/supplier-onboarding/{id}/profile-decision` 存在 ⇒ 看起来"审核完成"；实际无队列、无界面、需预知 2 个 ID、且结构上批不了 | 审核员没有工作的地方 |
| 3 | **STATE EXISTS → 流程完成** | `supplier_onboarding_state.py` 有 10 个状态与 `_next_step()` 映射 ⇒ 看起来"状态机完成"；前端未穷举 ⇒ `CONTRACT_PENDING` 落入 `else` 显示原始枚举 | 用户看到死路 |
| 4 | **TEST PASSES → 产品完成** | `test_supplier_onboarding_hk_unified.py` 全绿；但它**直接 SQL 插数据**构造前置条件，测试名自己写着 `requires_existing_hotel_truth` | 绿灯 ≠ 可达 |
| 5 | **EVIDENCE EXISTS → 业务验收完成** | 241 个 `*Evidence*` / `*Acceptance*` 命名文件；`hotel_page_production_acceptance.py` 用**合成 supplier** `rc13-supplier-{batch}` 跑注册审批 | 验收从未遇到真实供应商 |
| 6 | **CI GREEN → 用户可用** | 34 个 workflow 中 ~28 个验证 canonical/receipt/admission/VERIFY；只有 ~6 个跑测试 | 交付绿灯被读成产品绿灯 |
| 7 | **PR MERGED / RUNTIME DEPLOYED → 产品正确** | pointer 写 PR320、现场跑 PR376、`CURRENT_CANDIDATE.json` 写 DEPTH48 `pr:52` `ci: FAILED_BEFORE_ANY_STEPS` | 三处指针互不一致 |

**根因**：项目缺少一个**"完成"的定义**。当前实际的完成定义是"存在性"（表/API/状态/测试/证据/CI/部署 存在），而不是"一个真人能不能完成他的事"。

---

## 34. 三重正确性的分离

| 类别 | 当前状态 |
|---|---|
| **SOURCE_CORRECTNESS** | ✅ 可验证（SHA 明确、字节可对） |
| **DELIVERY_CORRECTNESS** | ✅ 可验证（8/8 同镜像、alembic head、healthy、VERIFY_OK 历史记录） |
| **PRODUCT_CORRECTNESS** | ❌ 不可用（注册阻断、入驻死循环、详情夹具、供给/支付未接、B 端无审核台） |

**这三个必须分开汇报。** 现状是：前两个的高度成熟（字节级 identity、VERIFY、Evidence、指针）**制造了第三个也已完成的错觉**。

---

## 35. Launch readiness & Final verdict

### Launch readiness

| 面向 | 明天能不能上线 | 为什么 |
|---|---|---|
| **消费者** | ❌ | 无前门（`/` 404）；酒店详情是夹具；供给未接通；支付未接通 |
| **供应商** | ❌ | 注册全阻断；入驻死循环；无文件上传；无找回密码 |
| **运营** | ⚠️ 部分 | 交易/风控/内容审核可用；**入驻运营无工作台** |
| **安全** | ❌ | **35 条应鉴权却匿名可达的路由（其中 25 条 `/internal/*`，含凭据写入与映射审批）**；`/docs` 与 `/openapi.json` 公开（放大因子）；runtime env 中一个第三方 credential 建议轮换 |
| **数据** | ⚠️ | 564 表结构完整；12 个必要对象缺失；12 个对象规则未定 |

### Final verdict

> ## GO 今天 = `REAL_ASSETS + BROKEN_CORE_JOURNEY + CONTROL_ONLY_MASS`
>
> - **REAL**：C 端界面、酒店库与页面生产、图片授权与审核台、注册/条款/认证。这些是真资产。
> - **BROKEN**：B 端入驻（死循环）、运营入驻审核（无工作台）、C 端交易（无供给无支付）。
> - **CONTROL_ONLY**：约 26.5% 的 API（治理族）、30 项运营导航、~28 个 CI pipeline —— 自洽、可运行、**不产生产品结果**。
> - **交付层（source/delivery）是成熟的**，但它与产品正确性无关，且三处指针已经 drift。

**最严重的问题不是"代码烂"，而是"工程能力被投在了不产生产品结果的地方，同时用户唯一必须走通的那条链路是断的"。**

---

## FINAL QUESTIONS

### 1. 当前 GO Supplier onboarding 是"完整产品""半成品""技术原型"还是别的什么？

**技术原型**，且被**真正产品级的邻接系统**（酒店库/媒体/审核台）包围。不是半成品 —— 部件形状本身不对。（详见 PM 专项）

### 2. 当前最大问题是？

**"以上多项"，根因顺序：**
1. **产品规则未定义**（25 项待决：PM 专项 15 + 本报告 10）
2. **运营后台缺失**（无入驻队列、无审核台、无认领、无合同、无通知）
3. **领域模型缺失/错误**（12 个必要对象缺失；`supplier_id` 三义；`property_id` 同义不同物；blob 代替模型）
4. **安全缺口**（35 条应鉴权却匿名可达，含凭据写入与映射审批；`/docs` 公开为放大因子；runtime credential 建议轮换）
5. **核心链路设计死锁**（入驻不可达）
6. **真实供给与支付未接通**（C 端界面是展示品）
7. **UI 差**（最小的一项，且多半是上面几条的结果）

### 3. 现在继续大规模建数据库，是否合适？

**分开看：A 类继续建（酒店库、认证、条款决策、订单运行时、媒体、审计）是对的；C 类应暂停（claim / alias / contract / document / legal_entity / membership / notification / retention / sla / review_finding）。** 详见 §14。

### 4. 哪些已稳定可以保留？

§14 A 类全部 + §25 的 10 项 KEEP。

### 5. 哪些现在不应建？

§14 C 类 12 个对象 —— **它们的形状会替 25 个待决问题中的至少一个拍板。**

### 6. 只做一个集中版本，范围是什么？

见 §30 的 7 步（安全止血 → 解死循环 → 审核台 → 显式化 → 补规则 → 真实供给支付 → 才轮到治理）。

### 7. 哪些后端能力该保留避免推倒重来？

§25 KEEP 的 10 项。最该保留：**酒店库整套、媒体管道形状、审核台模式、条款决策记录、注册验证码管道、认证会话**。

### 8. 哪些属于过早优化 / 过早治理？

§21.2 + §23：恢复/信任/混沌/豁免/预测/遥测/身份重签发/联邦信任/信用平面容灾（30 项导航 + 287–305 路由）+ 对不存在文件的留存/跨境门禁。

### 9. 从 Product Owner 视角，最容易被 PR/CI/Evidence 误导的地方？

**§33 的七种模式**，最危险的三条：
- 测试全绿但**测试自己插数据库**（`test_supplier_onboarding_hk_unified.py`）；
- 34 个 CI 里 ~28 个是**交付/治理流水线**，却被读成"系统就绪"；
- **三处 runtime/state 指针互不一致**（pointer=PR320、现场=PR376、candidate=DEPTH48 pr52），任何以文档为准的判断都会错。

### 10. 老板只需要看 5 分钟的产品现实摘要

见 `GO_FULL_AUDIT_BOSS_BRIEF_20261003.md`。

---

## 附录：附件清单

| 文件 | 用途 |
|---|---|
| `GO_FULL_AUDIT_INVENTORY_20261003.md` | coverage map（inventory） |
| `GO_FULL_AUDIT_20261003.md` | 本文件（主报告） |
| `GO_FULL_AUDIT_BOSS_BRIEF_20261003.md` | 老板 5 分钟版 |
| `GO_FULL_AUDIT_BOSS_GPT_HANDOFF_20261003.md` | Boss GPT 交接 + 新 DONE 定义 |
| `GO_FULL_AUDIT_ACTION_MAP_20261003.md` | NOW / NEXT / LATER / STOP |
| `docs/audits/2026-10-03-go-full-audit/evidence/api_routes.json` | 1082 路由 + 鉴权依赖 |
| `docs/audits/2026-10-03-go-full-audit/evidence/db_tables.json` | 563 model → table + 引用分布 |
| `docs/audits/2026-10-03-go-full-audit/evidence/surface-results.json` + `shots/` | 现场渲染结果与截图 |
