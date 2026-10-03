# GO FULL AUDIT — INVENTORY / COVERAGE MAP

**Date**: 2026-10-03
**Scope**: whole repository `yuguangzhi3836-glitch/GO`, area = `/go-app/` (Consumer) + `/supplier-console/` (Supplier) + `/go-admin/` (Admin/Operations) + Control Plane + runtime
**Purpose**: 证明"全量审过"的 coverage map。每一条都来自程序化枚举或现场只读检查。
**Mode**: READ ONLY。零 mutation。

---

## 0. Truth binding（本轮重新核对，非引用旧结论）

| Item | Value | How verified |
|---|---|---|
| GitHub current main | `7e7aedd556eac986210f1a5474c7b31e04d37a29`（2026-10-03 12:37 +0800，`Merge PR #374 supplier-onboarding-state`） | `git fetch origin main` + `rev-parse` |
| HK-STAGING actual runtime image | `sha256:01632507d0d3b60054c1d9e56c5338b51085a69094b9beb4773e330c21191754` | `docker inspect` over 8/8 business services（全部同一值） |
| Image tag | `go-hk-test-pr:9f889acfcd36a82c7565b723261ee046c2615314` | `docker images`（tag = PR #376 head） |
| Running business services | **8**: `api`, `outbox-worker`, `recovery-worker`, `reconciliation-worker`, `judgment-worker`, `mobile-engagement-worker`, `mobile-push-worker`, `mobile-push-receipt-worker` | `docker ps` |
| Non-target services | `redis:7.4-alpine`（Up 4 weeks）、`caddy:2.8-alpine`（Up 4 weeks） | `docker ps` |
| DB | **不在本机 docker 内**（`docker ps -a` 无 postgres 容器）；由 `api` 容器内 `settings.database_url` 指向外部 | container 内只读 SQL |
| DB alembic revision | `0145_source_latest_index`（head） | 容器内 `alembic current` + `select version_num from alembic_version` |
| DB public tables | **564** | container 内 `information_schema.tables`（= 563 model + `alembic_version`） |
| OpenAPI (live) | **1065 paths / 1101 operations** | `curl 127.0.0.1:8000/openapi.json` |
| Public exposure | `/openapi.json` → **200 (852,802 B)**；`/docs` → **200**（Swagger UI 公开） | curl GET |
| Root path | `/` → **404**（无统一入口/落地页） | curl GET + browser |
| Runtime pointer（repo） | `docs/canonical-baseline/CURRENT_HK_RUNTIME.json` 指向 **PR #320**（image config `sha256:26c95472d494…`，2026-10-02，openapi 972 paths，tables 564） | `git show origin/main:...` |
| 判定 | **`RUNTIME_POINTER_DRIFT = YES`** | 见 §7 |

### RUNTIME_POINTER_DRIFT 明细

| 字段 | repo pointer 声明 | 现场实测 | 一致? |
|---|---|---|---|
| runtime image | `sha256:26c95472d494100dc5365b031335670b57570b86ac50fb1b4ebd161d7933530b` (PR320) | `sha256:01632507d0d3…` (PR376) | ❌ |
| image tag | `go-hk-test-pr:eeafca1b…` | `go-hk-test-pr:9f889acf…` | ❌ |
| deployed_date | 2026-10-02 | 2026-10-03（容器 Up 4 hours） | ❌ |
| openapi_paths | 972 | **1065** | ❌ |
| tables | 564 | 564 | ✅ |
| alembic_head | `0145_source_latest_index` | `0145_source_latest_index` | ✅ |

**第二处 drift**：容器 label `com.docker.compose.project.config_files` =
`/home/go-stg/releases/r31-5-final-completion-20260906/.../deploy/docker-compose.r31-hk-staging.yml` + `/run/go-hk-deployctl/deploy-hi1e1j9x.yaml` + `/run/go-hk-deployctl/media-mount-501k8keo.yaml`。
即：**现场运行的拓扑由一份 2026-09-06 的 compose 文件 + deployctl 生成的 override 决定，而不是仓库里声明为 "canonical Compose definition" 的 `deploy/hk-staging/docker-compose.business-runtime.yml`。** 该仓库文件自称 "the GitHub-side equivalent of the Compose file that is running on HK-STAGING-01" —— 这个说法当前不成立。

### 第三处 drift：current-state 文档

| 文档 | 绑定的 main | 最后修改 | 与当前 main 的距离 |
|---|---|---|---|
| `docs/project/GO_CURRENT_STATE.md` | `8ffcde66d36c1bbf849218529ef015f6e81725af`（2026-09-14） | 2026-09-26 | **落后 ~19 天** |
| `docs/project/CONTEXT_CHECKPOINT.json` | `8ffcde66…`，`refreshed_at 2026-09-14T19:57` | 2026-09-14 | **落后 ~19 天** |
| `docs/canonical-baseline/CURRENT_CANDIDATE.json` | `source_commit bd25d7acc…`，`pr: 52`，`current_status: SOURCE_COMPOSITE_PARENT_ARCHIVED_FULL_ACCEPTANCE_AND_RUNTIME_PENDING`，`ci: FAILED_BEFORE_ANY_STEPS` | DEPTH48 时代 | 与今天无关的历史产物 |

main 在最近 30 天有 **402 个提交**。

---

## 1. Repository scale

| 指标 | 数量 |
|---|---|
| `application/src/go_hotel/**/*.py` | **488 文件**，约 30–33k 行 |
| API route 文件 | **120** |
| `@router.<method>` 装饰器（解析得） | **1082** |
| OpenAPI 实测 | 1065 paths / 1101 ops |
| SQLAlchemy model class `(Base)` | **563** |
| `__tablename__` 声明 | 563 |
| live public tables | 564（563 + `alembic_version`） |
| service 文件 | **126** |
| worker 模块 | **14** |
| alembic migration | **146** |
| Python 测试文件 | **399** |
| Python 测试函数 | **2401** |
| JS/CJS/MJS 测试 | 8 |
| GitHub Actions workflow | **34**（其中仅 ~6 实际跑 pytest） |
| 前端 JS 总量 | ~3,932 行（`shared/app.js` 897、`admin/hotel-page-factory.js` 451、`consumer/app.js` 349 …） |
| 最大单文件 | `application/src/go_hotel/db/models.py` = **8,195 行 / 583,862 B**（563 个类挤在一个文件） |

---

## 2. Frontend entrypoints & mounts

| Mount | Source dir | 大小 | 现场 |
|---|---|---|---|
| `/go-app/` | `application/frontend/consumer/` | index 2,330 B | 200 ✅ |
| `/supplier-console/` | `application/frontend/supplier/` | index 995 B | 200 ✅ |
| `/go-admin/` | `application/frontend/admin/` | index 2,542 B | 200 ✅ |
| `/console-assets/` | `application/frontend/shared/` | 共享 JS/CSS/SVG | 200 ✅ |
| `/` | — | — | **404** ❌ |

`main.py:342-345` 四个 `app.mount`。**没有统一入口、没有落地页、没有产品前门。**

## 3. Frontend navigation inventory

| Surface | primary nav | hidden nav | total | 备注 |
|---|---|---|---|---|
| Consumer `/go-app/` | 5（首页/行程/收藏/消息/我的） | — | 5 | 另有品类 tab 5 项（酒店/机票/火车票/租车/景点玩乐） |
| Supplier `/supplier-console/` | **10** | **62** | **72** | `config.js` 自称 `partnerPrimaryNavMax: 7`，实际 10 |
| Admin `/go-admin/` | **62** | — | **62** | 其中**第 11–40 项连续 30 项**为恢复/信任/混沌/豁免/预测/遥测类 |

### Admin nav 全 62 项（`application/frontend/admin/config.js`）

运营类：全局运行状态 / 异常队列 / 订单控制 / 退款 / 赔付责任 / 风险事件 / GO 判断证据 / 供应商连接器 / 结算明细 / 双人审批工作流 · **酒店运营 / 机票运营 / 铁路运营 / 用车运营 / 租车运营 / 景点门票 / 供应商管理 / GO 推荐 / GO 点评 / GO Truth / GO 星级 / GO Trips / R8 预发布就绪度 / 酒店数字基础设施 / 一期闭环 / 支付运营 / 财务对账 / GO 身份凭证 / GO Offer 治理 / T+20 财务审计 / 供应商责任与赔付 / 审计日志**

治理/恢复/预测类（**连续 30 项**）：恢复控制 / 恢复实验 / 恢复学习 / 恢复数据治理 / 学习事件控制 / 恢复发布治理 / 运行时发布安全 / 运行遥测治理 / 运行遥测可信 / 运行身份生命周期 / 运行身份重签发 / 凭证授权 / 联邦信任执行 / 外部信任与多地域 / 信任传播与恢复 / 信任平面独立与容灾 / 信任混沌与就绪 / 持续混沌与豁免 / 豁免暴露与技术债 / 异常债务清理 / 企业风险组合 / 企业风险偏好 / 企业风险预测 / 预测校准与准确性 / 预测模型主备治理 / 预测统计晋级 / 预测漂移与刷新 / 预测训练与可复现 / 预测制品供应链 / 预测服务证明

**供应商入驻审核 = 0 项。**

---

## 4. API inventory

### 4.1 按顶层段

| 段 | 路由数 | 占比 |
|---|---|---|
| `/internal/*`（URL namespace，**非鉴权口径**） | **710** | **65.6%** |
| `/v1/*` | 348 | 32% |
| `/bff/*` | 19 | 2% |
| `/health`, `/metrics` | 2 | — |
| **合计** | **1082** | |

### 4.2 按 HTTP 方法

| 方法 | 数量 |
|---|---|
| GET | 340 |
| POST / PUT / PATCH / DELETE（写） | **742** |
| 合计 | 1082 |

> 写路由 (742) 是读路由 (340) 的 **2.2 倍**。对一个几乎还没有真实用户的系统，绝大多数的写路径没有真实调用方。

### 4.3 按鉴权依赖（修正解析器后：router 级 + 装饰器级 + 签名级三处合并）

| 依赖 | 路由数 |
|---|---|
| `admin_principal` | 466 |
| `consumer_principal` | 136 |
| `hosted_admin` | 70 |
| **（无任何鉴权）** | **66** |
| `supplier_principal` | 46 |
| `legacy_order_access` | 25 |
| `admin_principal + catalog_writer` | 24 |
| 其它组合 | 249 |

**51.6% 的 API 要求 admin principal** —— 依赖集合中包含 `admin_principal` 的路由 = **558 / 1082**。

> ⚠️ **口径区分（重要）**：
> - `/internal/*` = **710 / 1082 = 65.6%** 是 **URL namespace** 口径，**不等于 admin-only**；该 namespace 内还存在 `hosted_admin`(70)、`supplier_principal`、`catalog_writer` 以及无依赖路由。
> - `admin_principal` = **558 / 1082 = 51.6%** 是 **auth principal** 口径。
> 两者不得互相替代表述。

### 4.4 无显式鉴权依赖的路由 66 条 —— 逐条分类后 **35 条为真实缺陷**

> **66 是"未分类的原始枚举"，不是"66 个安全漏洞"。** 逐条复核（含检查 handler **函数体内**的鉴权行为）后：

| 分类 | 数量 | 说明 |
|---|---|---|
| `PUBLIC_BY_DESIGN` | **19** | 登录/注册/公开条款/健康检查/公开酒店媒体/透明日志等，按设计匿名 |
| `AUTH_ENFORCED_IN_BODY` | **2** | 已鉴权，但通过 `_consumer_account()` 在体内强制 401，未走 `Depends` ⇒ **非缺陷** |
| `MACHINE_AUTH_IMPLEMENTED` | **5** | webhook 均强制 `X-GO-Signature-SHA256` / `X-Payment-Signature` header ⇒ **非缺陷** |
| **`AUTH_REQUIRED`** | **35** | 应鉴权却匿名可达；**其中 25 条位于 `/internal/*`** |
| `UNKNOWN_NEEDS_PRODUCT_DECISION` | **5** | 需产品判定是否有意公开 |

逐条表（METHOD / PATH / SOURCE / CALLER / CLASSIFICATION / RATIONALE / REAL_FAILURE_IF_LEFT_OPEN / RECOMMENDED_ACTION）见 `UNAUTHENTICATED_ROUTE_CLASSIFICATION_20261003.md`。

**原先被误列的一类已撤回**：`GET /v1/hotel-media/{asset_id}` 经复核**已有正确门禁**（`require_publishable=True` + `catalog_scope.require_hotel` + 显式拒绝 `HOTEL_DIRECT_UPLOAD`），不是缺陷。

**已现场只读验证（GET only）**：

| 路由 | 现场结果 |
|---|---|
| `GET /internal/v1/supplier-connectors` | **200** `{"data":[]}` |
| `GET /internal/v1/merge/drift` | **200**，返回真实业务数据（含 `hotel_id: HRBUB`、`canonical_room_id`、`connector_id: conn_aoluguya_hosted_test`） |
| `GET /internal/v1/connectors/health/all` | **200**，返回连接器清单 |
| `GET /internal/v1/p0/design-code-freeze/status` | **200**，返回内部设计/代码冻结状态 |
| `GET /v1/reviews/pending` | **200** |
| 对照：`GET /internal/v1/admin/dashboard` | **401** ✅（声明了 `admin_principal` 的就是受保护的） |
| 对照：`GET /v1/consumer/trips` | **401** ✅ |

**未验证（属写操作，按边界未调用）** 但源码确认无鉴权：

- `PUT /internal/v1/supplier-connectors/{onboarding_id}/credentials` — 写供应商连接器凭据
- `GET /internal/v1/supplier-connectors/{onboarding_id}/credentials` — 读凭据
- `POST /internal/v1/supplier-connectors/property-mappings/{mapping_id}/review` — 审批映射
- `POST /internal/v1/connectors/{connector_id}/certify` — 认证连接器
- `POST /internal/v1/connectors/reconciliation/run-once`、`POST /internal/v1/ops/outbox/run-once`、`POST /internal/v1/ops/saga-recovery/run-once`、`POST /internal/v1/outbox/drain` — 触发后台作业
- `POST /internal/v1/demo/orders/{order_id}/complete-stay` — 变更订单
- `PUT /internal/v1/merge/room-mappings` — 变更房型映射
- `PUT /internal/v1/routing/sla/{connector_id}` — 变更 SLA
- `POST /internal/v1/judgments/{hotel_id}/reevaluate`、`POST /internal/v1/judgment-hooks/process-pending` — 触发判断流水线
- `POST /internal/v1/orders/{order_id}/reviews/eligibility`、`POST /internal/v1/reviews/{review_id}/{first-invite|mark-not-reviewed}` — 评价流程
- `POST /internal/v1/connectors/{connector_id}/webhooks`

**根因（已验证）**：`api/routes/onboarding.py` 顶部 `from go_hotel.security.deps import require_permission` 与 `Principal, approval_service, audit_service` **被 import 但从未使用**；`router=APIRouter(prefix="/internal/v1/supplier-connectors", tags=[...])` 未声明 `dependencies=`；每个 handler 也未声明 `Depends`。`outbox.py`、`routing.py`、`merge.py`、`judgment.py`、`connectors.py`、`ops.py`、`truth.py`（部分）同类。
`main.py` 的 `Sprint1USecurityMiddleware` **只做 CSRF**，不强制认证 —— 无 cookie、无 Authorization header 的请求直接放行到 handler。

### 4.5 路由最多的文件

| 路由数 | 文件 |
|---|---|
| 105 | `hosted_direct_booking.py` |
| 38 | `hotel_autopage_factory.py` |
| 32 | `personal_travel_vault.py` |
| 25 | `dashboard.py` / `hotel_partner_core.py` / `mobile.py` |
| 19 | `bff.py` / `compensation.py` / `consumer_identity.py` / `fare.py` / `travel_intelligence.py` |
| 18 | `mother_plan_p0.py` |
| 17 | `flight.py` |

### 4.6 按业务域的路由密度（正则匹配 path）

| 域 | 路由数 |
|---|---|
| **recovery** | **290** |
| **trust** | **183** |
| order | 136 |
| supplier | 129 |
| **risk** | **121** |
| **forecast** | **97** |
| hotel | 91 |
| connector | 73 |
| payment | 58 |
| ride / mobility | 51 |
| review | 43 |
| media | 36 |
| rental | 33 |
| flight | 25 |
| mobile | 25 |
| refund | 20 |
| rail | 15 |
| attraction | 13 |
| judgment | 13 |
| vault | 2 |

> ⚠️ **统计口径更正**：`recovery(290) + trust(183) + risk(121) + forecast(97)` 的**求和 691 是非互斥统计，不得当作占比使用**。
> - **去重 union = 305 = 28.2%**
> - **按声明文件归属（文件名含 recovery/trust/risk/forecast/chaos/waiver/debt/enterprise）= 287 = 26.5%**
> - 重叠证据：`forecast` **97/97 全部包含 `recovery`**（例 `/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast/policies`）；recovery∩trust=177、recovery∩risk=112、trust∩risk=112。
>
> **权威表述（全文统一）**：治理族路由 = **287（文件口径，26.5%）／305（路径 union，28.2%）**，二者均为非互斥统计。旅行业务域合计占其余部分且互相重叠。
> 详见 `GO_FULL_AUDIT_ERRATA_20261003.md` E-7。

---

## 5. Domain map（按 domain 聚类，含归属判定）

### 5.1 Consumer / C 端
- 前端：`application/frontend/consumer/`（index.html + app.js 349 行 + 12 个功能 js + 8 个 css）
- 路由：`consumer.py`、`consumer_identity.py`、`consumer_growth_direct_value.py`、`consumer_unified_lifecycle.py`、`hotel.py`（search/prebook）、`flight.py`、`rail.py`、`mobility.py`、`attractions.py`、`rental_operations.py`
- 模型：`ConsumerNotificationRow`、`ConsumerTripMemberRow`、`ConsumerTripInvitationRow`、`TravelerClaimRow`、`ProfileImportJobRow`、`GoFriendsFamilyInvitationRow`
- 现场：`/go-app/` 200，标题 `GO 旅行`，h1 `说出你的旅行想法`，品类 tab 5 项、底部 nav 5 项、旅行灵感卡片 3 张；匿名访问仅 1 个预期 401（`/v1/consumer/me`）
- **判定：REAL_PRODUCT（UI 层）/ PARTIAL_PRODUCT（交易闭环）**

### 5.2 Supplier / B 端
- 前端：`application/frontend/supplier/` —— **Supplier frontend defines 72 route/surface entries: 10 primary + 62 hidden**（`hiddenNav` **不是**同时可见导航项）+ `shared/app.js` 的 supplier 视图
- 路由：`bff.py`（19）、`hotel_partner_core.py`（25）、`dashboard.py`、`hotel_direct_submission.py`、`compensation.py`、`go_identity_entitlements.py`、`supplier_multivertical.py`、`supplier_operations.py`（37）、`catalog_fare.py`…
- 模型：`HotelPartnerPropertyRow`、`HotelPartnerRoomTypeRow`、`HotelPartnerChangeRequestRow`、`HotelPartnerOperationalInboxRow`、`HotelPartnerAriOverrideRow`、`HotelPartnerGoOfferAuthorityRow`、`SupplierConnectorOnboardingRow`、`ConnectorCredentialRow`、`PropertyMappingCandidateRow`…
- **判定：TECHNICAL_PROTOTYPE**（详见 `GO_SUPPLIER_PM_PRODUCT_AUDIT_20261003.md`）

### 5.3 Admin / Operations
- 前端：`application/frontend/admin/`（25 个 js，nav 62 项）
- 路由：`/internal/*` 710 条；`dashboard.py`、`hotel_autopage_factory.py`、`hotel_infrastructure*`、`interactive.py`、`operational.py`…
- 现场：`/go-admin/` 200，登录页 `GO 全生态运营管理系统`；`/internal/v1/admin/dashboard` 401（受保护）
- **判定：PARTIAL_PRODUCT（运营台存在且部分可用）/ CONTROL_ONLY（30 项治理导航）**

### 5.4 Hotel / Hotel library / Hotel page / Media
- 服务：`hotel_autopage_factory.py`、`hotel_discovery_orchestrator.py`、`hotel_infrastructure_p0.py`、`hotel_page_production_acceptance.py`、`regional_hotel_build.py`、`media_harvester.py`、`hotel_partner_media_upload.py`
- 路由：`hotel_autopage_factory.py`（38）、`hotel_direct_submission.py`、`hotel.py`
- 模型：`HotelCanonicalProfileRow`、`HotelContentSourceSnapshotRow`、`HotelContactPointRow`、`HotelAutoPageVersionRow`、`HotelAutoPageEventRow`、`HotelRegistrationDirectRow`、`HostedMediaAssetRow`
- 前端：`admin/hotel-page-factory.js`（451 行）、`admin/hotel-direct-review.js`（100 行，完整审核台）
- **判定：REAL_PRODUCT**

### 5.5 Verticals
| Vertical | 路由文件 | 路由数 | 判定 |
|---|---|---|---|
| Hotel | `hotel.py`, `hotel_partner_core.py`, `hotel_autopage_factory.py`, `hosted_direct_booking.py` | 91 | REAL_PRODUCT（library）/ PARTIAL（交易） |
| Flight | `flight.py` | 25 | PARTIAL |
| Rail | `rail.py` | 15 | PARTIAL |
| Ride / Mobility | `mobility.py`, `ride_policy_operations.py` | 51 | PARTIAL |
| Rental | `rental_operations.py`, `rental_deposit_*.py` | 33 | PARTIAL |
| Attraction | `attractions.py` | 13 | PARTIAL |

现场开关：`AOLUGUYA_DIRECT_TEST_MODE=true`、`AOLUGUYA_REAL_INVENTORY_CONFIGURED=false`、`AOLUGUYA_REAL_RATE_CONFIGURED=false`、`AOLUGUYA_REAL_PAYMENT_CONFIGURED=false` ⇒ **外部真实供给与支付在当前现场均未启用**。

### 5.6 Booking / Order
- `booking.py`（router 级 `dependencies=[Depends(legacy_order_access)]`）、`interactive.py`（取消/改期）、`order_supplier_fulfillment.py`、`hosted_direct_booking.py`（105 路由）
- 模型：`OrderRow`、`OfferRow`、`PrebookRow`、`OrderChangeRow`、`IdempotencyRow`、`HotelOrderRuntimeRow`、`FlightOrderRuntimeRow`、`RailOrderRuntimeRow`、`MobilityRideOrderRuntimeRow`、`MobilityRentalOrderRuntimeRow`
- **判定：PARTIAL_PRODUCT**

### 5.7 Payment / Refund / Credit / Finance
- `omnichannel_payment.py`、`payment_sandbox_runtime.py`、`payment_sandbox_cutover.py`、`real_external_execution.py`、`alipay_safeguarded_settlement.py`
- 模型：`PaymentRow`、`PaymentOrchestrationRow`、`PaymentOrderRoot*`、`PaymentOrderFactBinding`、`RefundRow`、`CatalogCreditContractRow`、`StayCreditRow`、`SupplierFinancialAccountRow`、`SupplierLiabilityRow`、`CompensationPaymentRow`、`ProtectionFundLedgerRow`、`AlipayMerchantBindingRow`
- 现场：`AOLUGUYA_REAL_PAYMENT_CONFIGURED=false`；`PAYMENT_SANDBOX_CERTIFICATION` 资源类型存在
- **判定：FOUNDATION_ONLY + CONTROL_ONLY（沙箱/认证体系齐全，真实支付未接通）**

### 5.8 Search / Discovery / Routing / Merge
- `hotel.py` search、`attractions.py` search、`flight.py` search、`rail.py` search、`merge.py`（房型映射/drift）、`routing.py`（SLA/canary/decision）
- 模型：`OfferMergeDecisionRow`、`OfferDriftStateRow`、`OfferDriftEventRow`、`RoutingDecisionRow`、`PropertyMappingCandidateRow`、`RoomExternalIdentityRow`、`HotelExternalIdentityRow`
- **判定：PARTIAL_PRODUCT（merging/routing 是真实资产，但 consumer 侧搜索的供给未接通）**

### 5.9 Trip / GO ID / Account / Personal Vault
- `go_identity_entitlements.py`、`personal_travel_vault.py`（32 路由）、`travel_intelligence.py`（19）
- 模型：`ConsumerTripMemberRow`、`ConsumerTripInvitationRow`、`ProfileImportJobRow`、`TravelEntityAliasRow`、`TravelFactAuthorityRow`、`TravelOperationalFactRow`、`PersonalTravelVault*`
- 前端：`consumer/vault-manager.js`（145）、`consumer/travel-status.js`
- **判定：PARTIAL_PRODUCT**

### 5.10 Notification / Support / Reviews / Truth / Rating
- `truth.py`、`catalog_remedy`、`go_reviews`（admin）
- 模型：`ConsumerNotificationRow`、`HostedReservationNotificationRow`、`ReviewSessionRow`、`ReviewTagRow`、`RiskEventRuntimeRow`
- **判定：PARTIAL_PRODUCT；supplier 域无通知模型（MISSING）**

### 5.11 Registration / Privacy
- `registration_terms.py`、`registration_verification.py`、`registration_email.py`、`registration_privacy.py`、`privacy.html` + `privacy.js`
- 模型：`RegistrationChallengeRow`、`RegistrationRateRow`、`RegistrationDecisionRow`、`RegistrationMaintenanceRow`、`PrivacyRequestRow`
- **判定：REAL_PRODUCT（这一块质量最高）**

### 5.12 Mobile
- `mobile.py`（25 路由）、`worker/mobile-*.py`、`consumer/app.js` 的移动布局
- 现场：mobile-engagement / mobile-push / mobile-push-receipt 三个 worker 在跑
- **判定：PARTIAL_PRODUCT**

### 5.13 Governance / Recovery / Trust / Forecast / Risk（**最大的一块**）
- 路由 **287（文件口径）／305（路径 union）**；admin 导航连续 30 项；服务：`recovery_*`（数十个文件）、`forecast_*`、`trust_*`、`enterprise_risk_*`
- 模型：`RiskEventRuntimeRow`、`RiskEvidenceRuntimeRow`、`RiskRemediationRow`、`JudgmentHookRow`、`JudgmentEvidencePackageRow`、`JudgmentRuntimeRow`、`RecommendationDecisionRow`、`ApprovalRequestRow`、`AuditEventRow`…
- **判定：CONTROL_ONLY**（功能自洽、可运行，但不产生任何面向真实用户/运营人员的产品结果）

### 5.14 Command Center / Control Plane / HK runtime / GO Forge
- 目录：`command-center/`、`control-plane/`、`deploy/`、`hk-staging/`、`packaging/`、`deliverables/`、`evidence/`
- 34 个 GitHub Actions workflow 中约 28 个属于此域
- **判定：DELIVERY / CONTROL_ONLY**（交付正确性可验证，与产品正确性无关）

### 5.15 Inference / AI
- `go_ai/service.py`（698 行）、`ai_travel_infrastructure.py`
- 现场：`GO_AI_PROVIDERS_JSON=`（**空**）⇒ AI 能力在当前现场无 provider 可用
- **判定：FOUNDATION_ONLY**

---

## 6. Workers / async jobs

| Worker | 模块 | 现场 |
|---|---|---|
| outbox | `workers/outbox_worker.py` | Up 4h |
| recovery | `workers/recovery_worker.py` | Up 4h |
| reconciliation | `workers/reconciliation_worker.py` | Up 4h |
| judgment | `workers/judgment_worker.py` | Up 4h |
| mobile-engagement | `workers/mobile_engagement_worker.py` | Up 4h |
| mobile-push | `workers/mobile_push_worker.py` | Up 4h |
| mobile-push-receipt | `workers/mobile_push_receipt_worker.py` | Up 4h |

14 个 worker 模块存在，7 个在 HK 运行。另有 `OutboxRow` / `OutboxDeadLetterRow` 作为持久化队列。

**注意**：worker 模块对 model class 的直接引用计数 = **0**（全部经 service 层），因此"某表是否被 worker 使用"无法从 model 引用推断。

---

## 7. External integrations

| 集成 | 证据 | 现场状态 |
|---|---|---|
| SMTP（注册验证码） | `registration_email.py`（硬编码 sender `postmaster@goaidirect.com`，凭据走文件） | **未就绪** ⇒ 供应商注册全阻断 |
| OpenStreetMap Overpass | `GO_HOTEL_REGION_DISCOVERY_BOOTSTRAP_OSM=true` + `GO_HOTEL_REGION_DISCOVERY_OSM_ENDPOINT=https://overpass-api.de/api/interpreter` | 启用 |
| Firecrawl | `GO_FIRECRAWL_API_KEY` 存在于 runtime env | 见主报告安全节 |
| Alipay / 微信支付 | `alipay_safeguarded_settlement.py`、`AlipayMerchantBindingRow` | `REAL_PAYMENT_CONFIGURED=false`（未接通） |
| 奥鲁古雅（香港）供给 | `aoluguya_*.py` | `DIRECT_TEST_MODE=true`（测试模式） |
| GitHub | control-plane bridge、Forge | 启用（非产品面） |
| AI providers | `GO_AI_PROVIDERS_JSON=`（空） | **无 provider** |
| Redis | `redis:7.4-alpine` | 运行 |
| Caddy | `caddy:2.8-alpine`（TLS 终止） | 运行 |

---

## 8. Coverage statement

| 要求 | 状态 |
|---|---|
| frontend routes 已 inventory | ✅ §2 §3（3 个 mount，consumer 5 / supplier 72 / admin 62） |
| API routes 已 inventory | ✅ §4（1082 条解析，1065 paths live OpenAPI，含鉴权依赖） |
| major services 已 inventory | ✅ §5（126 service 文件按域归类） |
| DB models/tables 已 inventory | ✅ §1（563 model / 564 live table） |
| workers 已 inventory | ✅ §6（14 模块 / 7 运行） |
| product domains 已 inventory | ✅ §5（15 个域，含 verdict） |
| main / runtime 关系已验证 | ✅ §0（pointer drift 三处） |
| Consumer 核心 journey 已审 | ✅ 主报告 §5 |
| Supplier 核心 journey 已审 | ✅ 主报告 §6（复用两轮专项） |
| Admin/Operations 核心 journey 已审 | ✅ 主报告 §7 |
| 每个 travel vertical 至少一条主 journey | ✅ 主报告 §8 |
| Payment/refund 成功 + 失败路径 | ✅ 主报告 §8 |
| Account/auth/recovery 已审 | ✅ 主报告 §8 |
| Notification/support 已审 | ✅ 主报告 §8 |
| Mobile 已审 | ✅ 主报告 §5/§7 |
| Hotel library 已审 | ✅ 主报告 §11 |
| runtime/delivery 已审 | ✅ §0 + 主报告 §20 |
| control-plane/governance 与产品价值关系 | ✅ 主报告 §23 |

**NOT_AUDITED（含理由）**：

| 区域 | 原因 |
|---|---|
| HK 上的真实业务数据内容（订单/客户/供应商明细） | READ ONLY 边界内不做数据抓取；仅统计表数量与结构。 |
| `deliverables/` 历史快照目录内容 | 属历史归档，不是当前产品面（已确认目录存在但未逐文件审）。 |
| 治理域 287–305 条路由的逐条业务语义 | 只按域归类与抽样；这些路由不对应任何真人产品路径，逐条审无产品价值。 |
| Production 环境 | 无授权，未访问。 |
| Control Plane / Command Center 的部署裁定逻辑 | 属交付正确性，本轮仅核对 runtime 指针一致性。 |

---

## 9. 本文件引用的自动化产物

| 路径 | 内容 |
|---|---|
| `docs/audits/2026-10-03-go-full-audit/evidence/api_routes.json` | 1082 条路由 + 方法 + 鉴权依赖 + 源文件 |
| `docs/audits/2026-10-03-go-full-audit/evidence/db_tables.json` | 563 个 model class → table + 引用分布 |
| `docs/audits/2026-10-03-go-full-audit/evidence/surface-results.json` | 4 个现场 surface 的渲染结果 |
| `docs/audits/2026-10-03-go-full-audit/evidence/shots/*.png` | 现场截图（root-404 / consumer-desktop / consumer-mobile / admin-desktop） |
| `docs/audits/2026-10-03-go-full-audit/evidence/inv_api2.py` `inv_db.py` `surf.mjs` `classify.py` `signals.py` `secret_scan.py` | 分析脚本（**已随证据包提交**，可独立复核报告中的数字） |
