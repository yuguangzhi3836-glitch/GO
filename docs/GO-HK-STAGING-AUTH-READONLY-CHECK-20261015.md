# HK-STAGING 认证与鉴权 · 只读检查报告

- **时间**：2026-10-15 20:55–21:05 (GMT+8)
- **执行者**：WorkBuddy（麻花）· 只读
- **范围**：HK-STAGING 业务机（`hk-staging` 47.239.57.40 / `iZj6ccs8t04f1p4d8pe69zZ`）上的 Python 后台（compose `go-822-staging`）
- **授权基线**：READ_ONLY=YES · 未部署 · 未改配置 · 未读任何凭据/环境变量值 · 未尝试任何伪造凭据登录
- **public check 方式**：`https://staging-api.goaidirect.com`（Caddy → api:8000）匿名探测 + live `main` 源码 + 现场镜像元数据

---

## 0. 现场身份（Live evidence）

| 项 | 观测值 |
|---|---|
| API 容器 | `go-822-staging-api-1` up 7 days (healthy) |
| 镜像 | `sha256:d093c89ec550f2540c3da8456fb8f9111c6e0ed86b6d688fa4679ab834089e8e` |
| 镜像构建时间 | `2026-10-07T17:21:17+08:00`（⇒ 部署≈10-08） |
| 应用版本 | `9.1.0`（openapi `info.version`） |
| 前端 | Caddy `2.8-alpine` 反代 → `api:8000`；`Server: uvicorn` |
| 现场 APP_ENV | `staging`（`GET /bff/auth/policy` 实读） |
| 现场 mfa_required_for_admin | **`false`**（同上实读） |
| 现场 oidc_enabled | **`false`**（同上实读；`/bff/auth/sso/start` → 503 `OIDC_NOT_CONFIGURED`） |
| 其他容器 | redis + 8 个 worker（outbox / reconciliation / judgment / recovery / mobile-push ×2 / mobile-engagement），同镜像 |

> ⚠ **main ≠ 现场字节**。live main = `fa997b90b75956938be0387f73d17aab2d36f7a6`（2026-10-09）。
> 现场镜像建于 10-07；`hk-staging/source/runtime/`（09-11 归档）里的 `security/deps.py|rbac.py|service.py` 与 main **不同**，属更早世代。
> 现场镜像**含** `security/cookie_scope.py`（指纹：`GET /v1/consumer/me` 带 `X-GO-Session: bogus` → `400 INVALID_SESSION_SCOPE`）⇒ 现场介于 09-11 归档与 main 之间，安全模块行为与 main 基本一致。

---

## 1. 登录认证方式

自建身份服务 `go_hotel.security.service.IdentityService`，三套并行通道：

| 通道 | 载体 | 使用方 | 现场状态 |
|---|---|---|---|
| **Bearer JWT** | `Authorization: Bearer <jwt>` | 移动端 / 服务客户端 / 脚本 | ✅ 启用 |
| **HttpOnly Cookie 会话** | `go_access` / `go_consumer_access`（+ `go_csrf`） | 浏览器控制台 / `/go-app` | ✅ 启用（HSTS 头在场 ⇒ `cookie_secure=true`） |
| **OIDC 企业 SSO** | code+PKCE → id_token | — | ❌ 未配置（503） |

- 口令存储：**PBKDF2-SHA256，260,000 轮**，`pbkdf2_sha256$iters$salt$dk`（`security/crypto.py`）。
- 双通道路由：`security/cookie_scope.py` 用 `X-GO-Session: consumer|console` 选择命名空间；路径固定（`/v1/consumer*`=consumer，`/bff,/internal,/v1/supplier`=console）；两边 cookie 同时在场且未声明 → `409 SESSION_SCOPE_REQUIRED`。
- **无 Basic Auth、无 API Key、无 mTLS**（应用层）。
- 机器面另有两类：Agent 网关签名 JWT（见 §4）、Webhook HMAC 签名（见 §4）。

---

## 2. 是否使用 JWT / Token

| 令牌 | 类型 | 说明 |
|---|---|---|
| access_token | **JWT（HS256）** | `alg=HS256`，`typ=JWT`，手写 base64url + HMAC-SHA256，密钥 = `settings.jwt_signing_key` |
| refresh_token | **不透明随机串** | `secrets.token_urlsafe(48)`，DB 只存 **SHA-256 摘要**（`token_hash`），**单次使用即轮换** |
| csrf_token | 不透明随机串 | 双提交（cookie + `X-CSRF-Token` 头），DB 存摘要 |
| Agent 网关令牌 | JWT（HS256） | `typ=GO_AGENT_ACCESS / iss=GO_COMMAND_CENTER / aud=GO_AGENT_GATEWAY` + `purposes` 白名单 |

access_token claims：`sub, username, actor_type, supplier_id, roles, sid, ver, iat, exp, jti`。

> ⚠ 用户会话令牌与 Agent 令牌**共用同一把 `jwt_signing_key`**，分隔仅靠 claims（`typ/iss/aud`）。
> ⚠ `core/config.py` 内 `jwt_signing_key` 出厂默认值为 `dev-only-change-me-jwt`。**现场实际取值未读取**（属凭据面，本次不读、不试）。是否已改为强随机值需 owner 自行确认。

---

## 3. 有效期与验证机制

**有效期**（`core/config.py` 代码默认值）：

| 项 | 默认 | 说明 |
|---|---|---|
| `access_token_minutes` | **15 分钟** | JWT `exp` |
| `refresh_token_days` | **14 天** | refresh token 与 `auth_sessions.expires_at` 同用 |
| 会话（session） | 14 天 | `AuthSessionRow.expires_at` |
| MFA 注册令牌 | 600 秒 | `purpose=MFA_ENROLLMENT`，不可当会话用 |
| OIDC state 行 | 10 分钟 | 单次消费 |

> 现场 env（`ACCESS_TOKEN_MINUTES` 等）**实际覆盖值未读取**（属凭据/环境面）。上表是源码口径。

**验证链**（`IdentityService.authenticate` + `decode_jwt`，逐层失败即 401）：

1. JWT 结构 3 段 → 2. **HMAC-SHA256 签名比对**（`hmac.compare_digest`，失败 `INVALID_SIGNATURE`）→ 3. **`exp` 未过期**（`TOKEN_EXPIRED`）
4. DB：`IdentityUserRow.status == ACTIVE`
5. DB：`u.token_version == claims['ver']`（**全局失效开关**：改密/重绑 MFA 时 +1）
6. DB：`AuthSessionRow` 存在、`status == ACTIVE`、`expires_at > now`（失败 `SESSION_REVOKED`）
7. 命中后更新 `last_seen_at`；`X-GO-Actor` 头若存在必须与令牌 `actor_type` 一致，否则 `403 ACTOR_CONTEXT_CHANGED`

**刷新**：refresh 摘要查表 → 会话/用户 ACTIVE 且未过期 → 跨端类型校验 `allowed_actor_types` → **撤销旧 refresh 并签发新 refresh + 新 CSRF**（滑动续期）。

**CSRF**：`Sprint1USecurityMiddleware` 对所有非 GET/HEAD/OPTIONS 且**不带 `Authorization` 头**的请求做双提交校验（cookie==头 + 会话内摘要比对）；豁免名单 `/bff/auth/login|supplier/register|sso/*`、`/v1/consumer/auth/register|login`、`/v1/mobile/auth/login|refresh`。

**其他响应头**（实读）：CSP（`default-src 'self'`）、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、HSTS、`/bff/auth*`、`/v1/auth*`、`/v1/consumer/auth*`、`/v1/consumer/me` → `Cache-Control: no-store`。

**缺口**：
- 无 **jti 黑名单** ⇒ 单枚 access token 在 15 分钟内无法单独吊销（只能整会话/整用户）。
- 登录接口**无限流/锁定**（全仓 grep 无 `rate_limit / lockout / failed_login` 实现，仅外部 provider 对 429 的处理）。

---

## 4. 匿名可达的 API（现场实测）

线上 `GET /openapi.json` 可匿名读取（**886 KB，1065 path / 1101 operation**）。按 `security` 声明统计：

| 前缀 | 总数 | 需登录 | 匿名 |
|---|---|---|---|
| `/internal/` | 718 | 687 | **31** |
| 其他公开业务 | 164 | 126 | 38 |
| `/v1/consumer` | 81 | 72 | 9 |
| `/v1/supplier` | 75 | **75** | 0 |
| `/v1/mobile` | 20 | 18 | 2 |
| `/bff/` | 19 | 10 | 9 |
| `/v1/agent` | 9 | 0 | 9（**实为机器签名鉴权**，见下） |
| `/v1/webhooks` | 7 | 0 | 7（**实为 HMAC 签名鉴权**） |
| `/v1/trust` | 6 | 0 | 6 |
| `/mcp` `/a2a` | 2 | 0 | 2 |
| **合计** | **1101** | **988** | **113** |

### 4.1 匿名 GET 实测 200 且返回真实数据（**缺陷**）

| PATH | 响应体 |
|---|---|
| `GET /internal/v1/p0/design-code-freeze/status` | 24,253 B |
| `GET /internal/v1/p0/design-code-freeze/providers` | 16,111 B |
| `GET /internal/v1/p0/design-code-freeze/cancel-refund-state-machine` | 4,395 B |
| `GET /internal/v1/merge/drift` | 1,350 B（含真实 `hotel_id`） |
| `GET /internal/v1/mobile/engagement/jobs` | 683 B |
| `GET /internal/v1/connectors` | 362 B |
| `GET /internal/v1/routing/sla/{id}` | 251 B |
| `GET /internal/v1/connectors/health/all` | 118 B |
| `GET /internal/v1/routing/decisions/{id}` | 59 B |
| `GET /internal/v1/merge/decisions/{id}` | 57 B |

同类**匿名可写**（POST/PUT，本次**未执行**以免产生变更）：`/internal/v1/connectors/reconciliation/run-once`、`/internal/v1/outbox/drain`、`/internal/v1/ops/outbox/run-once`、`/internal/v1/ops/saga-recovery/run-once`、`/internal/v1/judgment-hooks/process-pending`、`/internal/v1/judgments/{hotel_id}/reevaluate`、`/internal/v1/demo/orders/{id}/complete-stay`、`PUT /internal/v1/merge/room-mappings`、`PUT /internal/v1/routing/sla/{id}`、`/internal/v1/mobile/engagement/ingest|process-due`、`/internal/v1/reviews/{id}/first-invite|mark-not-reviewed`、`/internal/v1/orders/{id}/reviews/eligibility`、`/internal/v1/connectors/{id}/certify`。

### 4.2 匿名但**按设计**（不算缺陷）

`GET /health`、`GET /bff/auth/policy`、`GET /bff/auth/sso/start|callback`、`POST /bff/auth/login`、`POST /bff/auth/supplier/register`、`GET /bff/auth/supplier/registration-terms`、`POST /v1/auth/login|refresh`、`POST /v1/consumer/auth/login|refresh|register`、`GET /v1/consumer/auth/registration`、`POST /v1/mobile/auth/login|refresh`、`GET /v1/registration-terms*`、`POST /v1/registration/challenges`、`POST /v1/{flights,rail,attractions,mobility,search}/*`（公开搜索）、`GET /v1/consumer/home`、`GET /v1/consumer/hotels/{id}`、`GET /v1/hotel-pages/{slug}`、`GET /v1/hotel-media/{asset_id}`、`GET /v1/trust/transparency/*`。

### 4.3 匿名但**已有机器鉴权**（不算缺陷）

- `/v1/agent/*`（9 个）：缺头即 `422`，必带 `Authorization / X-GO-Agent-ID / X-GO-Request-ID / X-GO-Trace-ID / X-GO-Purpose`，再由 `signed_agent_authorizer` 校验 JWT 的 `typ/iss/aud + agent_id 一致 + purpose 在 purposes 内 + protocol 白名单`。现场已确认（伪造 Bearer → 422，仍要求其余头）。
- `/v1/webhooks/*`（7 个）：强制 `X-Payment-Signature` / `X-GO-Delivery-ID` + `X-GO-Signature-SHA256`。
- `/a2a/v1`、`/mcp`：同一 Agent 授权器（`protocol_authorizer`）。

### 4.4 信息暴露

`GET /openapi.json`（886 KB 全量 schema）、`GET /docs`、`GET /.well-known/agent-card.json`（技能清单）**均匿名 200**。前两者是 FastAPI 默认，需产品决策是否收口。

---

## 5. 必须登录的 API

**988 / 1101 operation 显式声明 Bearer 依赖**。全量覆盖：`/v1/supplier/*`（75/75）、`/internal/*`（687/718）、`/v1/consumer/*`（72/81）、`/v1/mobile/*`（18/20）、`/bff/*`（10/19）、其余内部业务面（126/164）。

登录类保护的操作举例：`/v1/auth/me|logout`、`/internal/v1/identity/users`、`/internal/v1/audit-events`、`/v1/consumer/me|trips|wallet|travelers|orders`、`/v1/consumer/reviews/*`、`/v1/supplier/*` 全量、`/internal/v1/approvals*`。

现场反证（应为 401 的确实 401）：`/v1/auth/me`、`/v1/consumer/trips`、`/v1/consumer/orders/{id}/detail`、`/internal/v1/audit-events`、`/internal/v1/supplier-connectors/{id}`。

---

## 6. 角色权限与数据归属校验

**两者都有，但是「按路由 opt-in」，不是全局默认拒绝。**

- **RBAC**：`security/rbac.py` 角色→权限表（15 角色）。`require_permission("admin:read")` 作为 FastAPI 依赖注入；`admin_principal` 限 `GO_ADMIN`；`consumer_principal` 限 `CONSUMER`；`supplier_principal` 除 `SUPPLIER_USER` 外**还校验 onboarding 状态** ∈ {`CONTRACT_ACTIVE`,`BUSINESS_ENABLED`}（否则 `SUPPLIER_ONBOARDING_INCOMPLETE`）。
  - 注意：**角色改名/扩权只在 rbac.py**；现场（旧世代）的 `SUPPLIER_OWNER` 比 main **少** `supplier:fare-rules` 权限。
- **数据归属**：`assert_supplier_order(p, order_id)` 按 `row.supplier_id != p.supplier_id` → 404；`assert_consumer_order` 按 `row.account_id != p.user_id` → 404（**越权返回 404 而非 403，防枚举**）；`_assert_review` 按 `account_id`；StayCredit 亦按 `account_id`。
- **双人控制**：`ApprovalService` 对 8 类高风险操作（`COMPENSATION / BANK_DEBIT / CONNECTOR_ACTIVATION / RULE_VERSION_RELEASE / …`）要求**发起人与审批人不同**（`DUAL_CONTROL_REQUIRES_DISTINCT_ACTOR`）+ 30 分钟时限 + 一次性消费。
- **审计**：`Sprint1RAuditMiddleware` 对已认证的 POST/PUT/PATCH/DELETE 落 `audit_event`；401/403 记 `AUTHZ_FAILURE` 安全信号。

**缺口**：
- 无全局默认拒绝 —— 鉴权靠每个路由自己写 `Depends`；漏写即匿名可达（§4.1 即实证）。中间件只做 CSRF/响应头，**不做鉴权**。
- 权限粒度到 verb 级（`admin:read`），**不到资源级**；`/internal/*` 大量读接口只靠 `GO_ADMIN` 与否区分。
- 匿名成功的 `/internal/*` 请求**不会**进审计与安全信号（无 principal）。

---

## 7. Cole 的 APK 能否复用现有认证接口

**能，且无需后端任何改动、无需注册客户端。** 现有第一方 App（`application/mobile/go-app`，Expo/RN，Android `travel.go.consumer`）走的就是这套：

```
POST /v1/mobile/auth/login    {"email": "...", "password": "..."}   无鉴权，豁免 CSRF
  → {"data": {"access_token": "<HS256 JWT>", "token_type": "bearer",
              "expires_in": 900, "refresh_token": "<opaque>"}}
POST /v1/mobile/auth/refresh  {"refresh_token": "..."}              无鉴权，豁免 CSRF
  → 同一结构（旧 refresh 立即失效，新的轮换下发）
GET  /v1/consumer/me                       Authorization: Bearer <jwt>
…其余 /v1/consumer/*、/v1/mobile/*（fare / cancel / change / stay-credit / device / notifications）同理
```

要点：
1. **Base URL**：`https://staging-api.goaidirect.com`（`/openapi.json` 匿名可读 ⇒ 可直接生成客户端）。
2. **身份类型必须是 CONSUMER** —— `/v1/mobile/auth/login` 走 `consumer_service.login(email, password)`，且 refresh 强制 `allowed_actor_types={'CONSUMER'}`。供应商/管理台账号不能用这条路。
3. **原生 App 不受 CORS 限制**；后端**未配置 CORS 中间件**，所以 H5/WebView 形态的客户端会被浏览器拦（需另议）。
4. **没有任何客户端身份绑定**：无 `client_id` / 包名 / Play Integrity / App Attest / 证书固定校验。⇒ 复用零成本，**也零门槛**：任何人拿同样的接口就能做一个"官方 App"。
5. **Bearer 即全部凭证**：无设备绑定（`/v1/mobile/devices` 只登记推送，鉴权发生在之后），令牌被复制即等效登录；access 15 分钟内不能单独吊销。
6. **登录接口无限流** ⇒ 面向公网 + 无限流 + 无限客户端绑定，是当前最需要先补的一环。

**建议（按最小必要排序，均需单独授权才动手）**：
① 给登录/刷新加限流与失败计数；② 明确是否需要一个 App 侧 client 标识（哪怕只是可撤销的 public client id）；③ 若要做 H5/WebView，才需要 CORS 白名单；④ APK 侧令牌存 Keystore/Keychain，`expires_in` 到期前静默 refresh（现有 App 用 `expo-secure-store` + 401 重试，可直接照抄）。
