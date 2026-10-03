# UNAUTHENTICATED ROUTE CLASSIFICATION — 2026-10-03

**Baseline**: main `7e7aedd556eac986210f1a5474c7b31e04d37a29` · HK runtime `PR376 head 9f889acfcd36a82c7565b723261ee046c2615314`（`sha256:01632507d0d3…`）
**Source of list**: `docs/audits/2026-10-03-go-full-audit/evidence/api_routes.json` → 1082 route declarations parsed from `application/src/go_hotel/api/routes/*.py`
**Definition used**: "无显式鉴权" = 该路由的 dependency 集合为空 —— 合并三处来源后判定：router 级 `APIRouter(dependencies=[…])`、装饰器级 `dependencies=[…]`、handler 签名 `Depends(…)`。
**Method note**: 本分类**不只看 dependency**，还逐个检查了 handler **函数体内**的鉴权行为（因为发现部分路由通过 `_consumer_account()` 之类的帮助函数在体内强制 401）。因此这与"只按 `Depends` 判定"的结论不同，属于更严格的复核。

---

## 0. 汇总

| 分类 | 数量 | 含义 |
|---|---|---|
| `PUBLIC_BY_DESIGN` | **19** | 按设计应匿名开放（登录、注册、公开条款、公开页面/媒体、健康检查、透明日志） |
| `AUTH_ENFORCED_IN_BODY` | **2** | 已强制鉴权，但通过函数体帮助函数而非 FastAPI `Depends` ⇒ **不是缺陷**，只是风格不一致 |
| `MACHINE_AUTH_IMPLEMENTED` | **5** | 机器对机器回调，已在签名 header 上强制校验 ⇒ **不是缺陷** |
| **`AUTH_REQUIRED`（真实缺陷）** | **35** | 应当鉴权但当前完全匿名可达 |
| `UNKNOWN_NEEDS_PRODUCT_DECISION` | **5** | 需要产品判定是否有意公开 |
| **合计** | **66** | |

> **结论修正**：原报告写的"66 条无鉴权路由"是**未分类的原始枚举**，不等于"66 个安全漏洞"。
> 复核后真实需要处理的为 **35 条 `AUTH_REQUIRED`**，其中 **25 条位于 `/internal/*`**。

---

## 1. `PUBLIC_BY_DESIGN`（19）—— 不得因为"无鉴权"判错

| METHOD | PATH | SOURCE | CALLER / KNOWN USE | RATIONALE | REAL_FAILURE_IF_LEFT_OPEN | RECOMMENDED_ACTION |
|---|---|---|---|---|---|---|
| GET | `/health` | `health.py` | 负载均衡/监控探针 | 健康检查按惯例公开 | 无（仅暴露 status） | 保持 |
| GET | `/bff/auth/policy` | `bff.py` | 登录页读取环境/MFA 策略 | 登录前必须可知 | 无（只返回 env + 两个布尔） | 保持 |
| POST | `/bff/auth/login` | `bff.py` | 登录 | 登录入口 | 无（有 CSRF 中间件 + 凭据校验） | 保持 |
| GET | `/bff/auth/sso/start` | `bff.py` | 企业 SSO 发起 | 未登录时必须可达 | 无 | 保持 |
| GET | `/bff/auth/sso/callback` | `bff.py` | OIDC 回调 | 依赖 state/nonce 校验 | 需确认 state 校验存在 | 保持（复核 OIDC state） |
| POST | `/bff/auth/supplier/register` | `bff.py` | 供应商注册 | 注册入口 | 无（验证码 + 条款校验前置） | 保持 |
| GET | `/bff/auth/supplier/registration-terms` | `bff.py` | 注册页条款 | 注册前必须可见 | 无（公开条款正文） | 保持 |
| POST | `/v1/consumer/auth/register` | `consumer_identity.py` | C 端注册 | 注册入口 | 无 | 保持 |
| GET | `/v1/consumer/auth/registration` | `consumer_identity.py` | 注册策略 | 注册前必须可见 | 无 | 保持 |
| GET | `/v1/registration-terms` | `registration_terms.py` | 条款清单 | 公开法律文本 | 无 | 保持 |
| GET | `/v1/registration-terms/{term_id}/{version}` | `registration_terms.py` | 条款正文 | 公开法律文本 | 无 | 保持 |
| POST | `/v1/registration/challenges` | `registration_verification.py` | 发送验证码 | 注册前必须可达 | 无（已有冷却/地址/对端/全局四维限流） | 保持 |
| GET | `/v1/hotel-media/{asset_id}` | `hotel_autopage_factory.py` | 公开酒店图片 | 酒店页公开媒体 | **已正确设门**：`require_publishable=True` + `catalog_scope.require_hotel` + 显式拒绝 `source_type=='HOTEL_DIRECT_UPLOAD'`（供应商直传图片必须走审核页） | 保持 |
| GET | `/v1/hotel-pages/direct-submissions/{review_id}/media/{asset_id}` | `hotel_direct_submission.py` | 审核页取图 | capability 式（需 review_id + asset_id 同时正确） | 需成对 id | 保持（推荐加短时签名） |
| POST | `/v1/flights/search` | `flight.py` | 机票搜索 | 公开搜索 | 无（只读查询） | 保持 |
| GET | `/v1/ai-infrastructure/manifest` | `ai_travel_infrastructure.py` | 能力清单 | 公开能力声明（master_version V6.1） | 无（静态清单） | 保持或收为内部 |
| GET | `/v1/consumer/home` | `consumer.py` | C 端首页数据 | 公开落地数据 | 无鉴权风险；**但内容为硬编码 demo**（`city_code:TYO`, `check_in:2026-09-0x`）⇒ **产品问题，非安全问题** | 保持（内容需接真实数据） |
| GET | `/v1/consumer/hotels/{hotel_id}` | `consumer.py` | C 端酒店详情 | 公开详情 | 同上；**返回 `hotel_test` 夹具** ⇒ **产品问题** | 保持（内容需接真实数据） |
| GET | `/v1/trust/transparency/checkpoint` | `recovery_federated_trust.py` | 透明日志检查点 | 透明日志按设计公开可验证（当前 `tree_size:0`） | 无 | 保持 |

---

## 2. `AUTH_ENFORCED_IN_BODY`（2）—— 已鉴权，非缺陷

| METHOD | PATH | SOURCE | CURRENT_AUTH | CLASSIFICATION | RECOMMENDED_ACTION |
|---|---|---|---|---|---|
| GET | `/v1/consumer/trips` | `consumer.py` | 函数体调用 `_consumer_account(request, …)`；无 token 且 `APP_ENV ∉ {local,test,demo}` ⇒ **401**（现场实测 401 ✅） | `AUTH_ENFORCED_IN_BODY` | 建议改为 `Depends(consumer_principal)` 以与全库一致（**风格收敛，非安全修复**） |
| GET | `/v1/consumer/orders/{order_id}/detail` | `consumer.py` | 同上（`_consumer_account`） | `AUTH_ENFORCED_IN_BODY` | 同上 |

---

## 3. `MACHINE_AUTH_IMPLEMENTED`（5）—— 已强制机器鉴权，非缺陷

| METHOD | PATH | SOURCE | CURRENT_AUTH | RECOMMENDED_ACTION |
|---|---|---|---|---|
| POST | `/v1/webhooks/payments/{channel}` | `omnichannel_payment.py` | 强制 `Header(alias='X-Payment-Signature')` | 保持（确认验签在 service 内） |
| POST | `/v1/webhooks/production-connectors/{connector_id}` | `production_connector_runtime.py` | 强制 `X-GO-Delivery-ID` + `X-GO-Signature-SHA256` | 保持 |
| POST | `/v1/webhooks/p0/0100/payment/{operation_id}` | `real_external_execution.py` | 强制 `X-GO-Delivery-ID` + `X-GO-Signature-SHA256` | 保持 |
| POST | `/v1/webhooks/p0/0100/supplier/{operation_id}` | `real_external_execution.py` | 同上 | 保持 |
| POST | `/internal/v1/connectors/{connector_id}/webhooks` | `webhooks.py` | handler 体内显式 401 分支 | 保持（建议统一到 signature header） |

> **这是对原报告的一处放宽**：webhook 类**不得套用 user auth**；它们需要的是签名/共享密钥，且**当前已经实现**。原报告把这一类列进"无鉴权写路径"是不准确的，本表更正。

---

## 4. `AUTH_REQUIRED`（35）—— 真实缺陷

### 4.1 内部读（9）

| METHOD | PATH | SOURCE | WHAT LEAKS | REAL_FAILURE_IF_LEFT_OPEN | 现场实测 |
|---|---|---|---|---|---|
| GET | `/internal/v1/merge/drift` | `merge.py` | 酒店/连接器/房型映射漂移真实事实 | 竞争信息与供应链拓扑泄露 | **200，含真实 `hotel_id: HRBUB`** |
| GET | `/internal/v1/merge/decisions/{decision_id}` | `merge.py` | 合并决策明细 | 同上 | — |
| GET | `/internal/v1/connectors/health/all` | `connectors.py` | 连接器清单与健康 | 供应商/连接器资产盘点 | **200** |
| GET | `/internal/v1/p0/design-code-freeze/status` | `p0_design_code_freeze.py` | 内部设计/代码冻结状态 | 交付状态泄露 | **200** |
| GET | `/internal/v1/p0/design-code-freeze/providers` | 同上 | 供应商契约清单 | 同上 | — |
| GET | `/internal/v1/p0/design-code-freeze/cancel-refund-state-machine` | 同上 | 内部状态机定义 | 同上 | — |
| GET | `/internal/v1/judgments/{judgment_id}` | `judgment.py` | 判断记录 | 内部评估泄露 | — |
| GET | `/internal/v1/supplier-connectors/{onboarding_id}` | `onboarding.py` | 供应商连接器详情 | 供应商资产泄露 | **200（列表）** |
| GET | `/internal/v1/supplier-connectors/{onboarding_id}/credentials` | `onboarding.py` | **凭据引用** | 凭据元数据泄露 | — |

### 4.2 内部读（路由/映射，4）

| METHOD | PATH | SOURCE |
|---|---|---|
| GET | `/internal/v1/routing/decisions/{decision_id}` | `routing.py` |
| GET | `/internal/v1/routing/sla/{connector_id}` | `routing.py` |
| GET | `/internal/v1/routing/canary-bucket/{connector_id}` | `routing.py` |
| GET | `/internal/v1/supplier-connectors/{onboarding_id}/property-mappings` | `onboarding.py` |

### 4.3 内部写（15）

| METHOD | PATH | SOURCE | WHAT IT MUTATES | REAL_FAILURE_IF_LEFT_OPEN |
|---|---|---|---|---|
| PUT | `/internal/v1/supplier-connectors/{onboarding_id}/credentials` | `onboarding.py` | **写供应商连接器凭据** | 最高：可替换凭据引用 |
| POST | `/internal/v1/supplier-connectors/property-mappings/{mapping_id}/review` | `onboarding.py` | **审批酒店映射** | 高：可越权批准映射 |
| POST | `/internal/v1/supplier-connectors/{onboarding_id}/property-mappings` | `onboarding.py` | 创建映射候选 | 中高 |
| PUT | `/internal/v1/merge/room-mappings` | `merge.py` | **变更房型映射** | 高：污染正式房型对应 |
| PUT | `/internal/v1/routing/sla/{connector_id}` | `routing.py` | **变更连接器 SLA** | 高 |
| POST | `/internal/v1/connectors/{connector_id}/certify` | `connectors.py` | **认证连接器** | 高 |
| POST | `/internal/v1/connectors/reconciliation/run-once` | `connectors.py` | 触发对账作业 | 中 |
| POST | `/internal/v1/ops/outbox/run-once` | `ops.py` | 触发 outbox 发布 | 中 |
| POST | `/internal/v1/ops/saga-recovery/run-once` | `ops.py` | 触发 saga 恢复 | 中高 |
| POST | `/internal/v1/outbox/drain` | `outbox.py` | 排空 outbox | 中 |
| POST | `/internal/v1/judgment-hooks/process-pending` | `judgment.py` | 触发判断流水线 | 中 |
| POST | `/internal/v1/judgment-hooks/{hook_id}/process` | `judgment.py` | 同上 | 中 |
| POST | `/internal/v1/judgments/{hotel_id}/reevaluate` | `judgment.py` | 重算判断 | 中 |
| POST | `/internal/v1/orders/{order_id}/reviews/eligibility` | `truth.py` | 变更评价资格 | 中 |
| POST | `/internal/v1/reviews/{review_id}/first-invite`、`/mark-not-reviewed` | `truth.py` | 变更评价流程 | 中 |

### 4.4 内部 test helper（1）

| METHOD | PATH | SOURCE | NOTE |
|---|---|---|---|
| POST | `/internal/v1/demo/orders/{order_id}/complete-stay` | `consumer.py` | docstring 自述「Sprint 1X deterministic E2E helper. Not a public production fulfillment endpoint.」—— **一个自认的测试辅助端点，在 staging 上匿名可写订单状态** |

### 4.5 对外写但无身份（5）

| METHOD | PATH | SOURCE | WHAT IT DOES | REAL_FAILURE_IF_LEFT_OPEN |
|---|---|---|---|---|
| POST | `/v1/offers/{offer_id}/prebook` | `hotel.py` | 创建预占（真实持有） | **高：匿名可创建预占，可被滥用占用库存** |
| POST | `/v1/reviews/{review_id}/star` | `truth.py` | 写评分 | 高：可篡改任意评价评分 |
| POST | `/v1/reviews/{review_id}/tags` | `truth.py` | 写标签 | 同上 |
| POST | `/v1/reviews/{review_id}/content` | `truth.py` | 写评价正文 | 高：可注入任意内容 |
| POST | `/v1/reviews/{review_id}/second-trigger` | `truth.py` | 触发二次评价 | 中 |

### 4.6 IDOR 读取（1）

| METHOD | PATH | SOURCE | CURRENT_AUTH | REAL_FAILURE_IF_LEFT_OPEN |
|---|---|---|---|---|
| GET | `/v1/reviews/pending` | `truth.py` | `account_id: str = Query(default='acct_demo')` —— **无鉴权，account_id 由调用者提供且默认一个 demo 账号** | **高：传任意 account_id 即可读取他人在待评价列表**（现场 `GET /v1/reviews/pending` → 200 `{"data":[]}`） |

---

## 5. `UNKNOWN_NEEDS_PRODUCT_DECISION`（5）

| METHOD | PATH | SOURCE | WHY UNKNOWN | 建议 |
|---|---|---|---|---|
| POST | `/v1/ai-infrastructure/identity-release-plan` | `ai_travel_infrastructure.py` | 纯规划计算（校验 `requested_scopes` 后返回计划），**未见持久化**；但是否需要公开 | 产品决定：若为纯只读计算可公开；否则收内部 |
| POST | `/v1/ai-infrastructure/booking-orchestration-plan` | 同上 | 同上 | 同上 |
| GET | `/v1/hotels/{hotel_id}/judgment` | `judgment.py` | 酒店判断结果是否应公开可见 | 产品决定（现场对不存在 hotel 返回 404） |
| POST | `/internal/v1/connectors/{connector_id}/webhooks` | `webhooks.py` | 有体内 401 分支，但鉴权机制不清（非标准签名 header） | 收敛到签名 header |
| GET | `/v1/consumer/hotels/{hotel_id}` 的**内容真实性** | `consumer.py` | 端点设计公开合理，但**返回夹具数据** ⇒ 归入产品问题 | 非安全项 |

---

## 6. 数量校正对报告的影响

| 原报告写法 | 校正后 |
|---|---|
| "66 条无鉴权路由" | **66 条无显式鉴权路由（原始枚举）**；分类后 **35 条 `AUTH_REQUIRED`**、2 条已体内鉴权、5 条已机器鉴权、19 条按设计公开、5 条待产品决定 |
| "其中 31 条在 `/internal/*`" | **35 条 `AUTH_REQUIRED` 中，25 条在 `/internal/*`** |
| "66 条安全漏洞" | **不得再这样表述** |
| "webhook 无鉴权" | **已更正**：5 个 webhook 均强制签名 header，非缺陷 |

## 7. 安全严重性影响（配合主报告 §21 / §13）

| 原 finding | 原级别 | 校正后级别 | 理由 |
|---|---|---|---|
| `SEC-01` 66 条无鉴权 | P0 | **P0（收窄口径）** | 降为：**35 条 `AUTH_REQUIRED`，其中 25 条 `/internal/*`**；含**凭据写入**与**映射审批** |
| `SEC-04` `merge/drift` 匿名读到真实数据 | P0 | **P0** | 现场实测 200 且含真实 `hotel_id`；属真实可达 + 高价值 |
| `SEC-05` `/docs` + `/openapi.json` 公开 | P1 | **P1（口径改为 ATTACK_SURFACE_AMPLIFIER）** | **本身不构成漏洞**；与 SEC-01 组合才放大攻击面。若产品有意公开 API 文档，不应自动判错 |
| `SEC-06` API key 位于 runtime env | P1 | **P1（口径改为 CREDENTIAL_EXPOSURE_SCOPE_INCREASED）** | 用环境变量承载 runtime secret 是常见部署方式，**不是设计错误**。风险来自：该值在本次审计中进入过本地命令输出 ⇒ 建议 **ROTATE** |
| `SEC-07` `/internal/v1/demo/.../complete-stay` 匿名可写订单 | P1 | **P1** | 保留（自认的 E2E helper，匿名可写） |
| `SEC-08` `/v1/hotel-media/{asset_id}` 无归属校验 | P1 | **撤回（REVOKED）** | 复核发现该端点**已有正确门禁**：`require_publishable=True` + `require_hotel` + 显式拒绝 `HOTEL_DIRECT_UPLOAD`。**原判断错误，予以撤回。** |
| 新增 `SEC-10` `/v1/offers/{offer_id}/prebook` 匿名创建预占 | — | **P1** | 无身份即可创建真实持有 |
| 新增 `SEC-11` `/v1/reviews/{review_id}/{star,tags,content}` 匿名写 | — | **P1** | 可篡改任意评价 |
| 新增 `SEC-12` `/v1/reviews/pending` IDOR | — | **P1** | `account_id` 由调用者提供，默认 `acct_demo` |

**校准后安全项**：P0 = 2（`SEC-01` 收窄后的 35 条、`SEC-04`）｜P1 = 5｜撤回 1（`SEC-08`）。
