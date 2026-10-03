# GO FULL AUDIT — ERRATA / 口径更正记录

**Date**: 2026-10-03
**Mode**: AUDIT DOCUMENT REVISION ONLY（未改任何产品代码 / 未 commit / 未 deploy / 未 DB mutation）
**Baseline（本轮重新 readback 确认，未变）**：
- main = `7e7aedd556eac986210f1a5474c7b31e04d37a29`
- HK runtime = PR376 head `9f889acfcd36a82c7565b723261ee046c2615314`（`sha256:01632507d0d3…`，8/8 业务服务同镜像）
- alembic = `0145_source_latest_index (head)`

**目的**：把容易被"一个统计口径错误"整份否定的地方收紧到可证明的程度。**核心结论不撤回。**

---

## E-1｜`/internal/* ≠ admin-only`

- **OLD**：`/internal/* = 710 / 1082 = 66% 的 API 是 admin-only`
- **NEW**：
  - `/internal/*` namespace = **710 / 1082 = 65.6%**（这是 **URL namespace**，不是鉴权口径）
  - 依赖集合中包含 `admin_principal` 的路由 = **558 / 1082 = 51.6%**（这是 **auth principal** 口径）
- **WHY**：URL namespace 与 auth principal 是两件事。`/internal/*` 里存在 `hosted_admin`、`supplier_principal`、`catalog_writer`、以及无依赖的路由。把两者混为一谈是口径错误。
- **全文处置**：所有出现"66% admin-only"的位置已改为上述两句分开表述。

---

## E-2｜"66 条无鉴权路由" → 分类后的 35 条

- **OLD**：`66 条路由无鉴权`，并在 Action Map 写"**修掉 66 条无鉴权路由**"
- **NEW**：66 是**未分类的原始枚举**。逐条复核后分类为：

| 分类 | 数量 |
|---|---|
| `PUBLIC_BY_DESIGN` | 19 |
| `AUTH_ENFORCED_IN_BODY`（已鉴权，只是没走 `Depends`） | 2 |
| `MACHINE_AUTH_IMPLEMENTED`（webhook 已强制签名 header） | 5 |
| **`AUTH_REQUIRED`（真实缺陷）** | **35** |
| `UNKNOWN_NEEDS_PRODUCT_DECISION` | 5 |

- 其中 `AUTH_REQUIRED` 的 35 条里，**25 条位于 `/internal/*`**。
- **WHY**：① health / 公开条款 / 登录注册 / 公开酒店媒体按设计应匿名；② 部分路由通过 `_consumer_account()` 在函数体内强制 401（现场实测 `/v1/consumer/trips` → 401）；③ 5 个 webhook 均强制 `X-GO-Signature-SHA256` / `X-Payment-Signature` header，**机器对机器不应套用 user auth**。
- **证据**：`UNAUTHENTICATED_ROUTE_CLASSIFICATION_20261003.md`（逐条 METHOD/PATH/SOURCE/CALLER/CLASSIFICATION/RATIONALE/REAL_FAILURE_IF_LEFT_OPEN/RECOMMENDED_ACTION）。

---

## E-3｜`/docs` + `/openapi.json` 公开

- **OLD**：写成安全漏洞（P1 "打开的攻击面"）
- **NEW**：`PUBLIC_OPENAPI = ATTACK_SURFACE_AMPLIFIER`
  准确表述：**公开完整 API schema 本身不构成漏洞**；风险来自它 **与确实存在的匿名 internal/read/write 端点组合**，放大攻击面。
- **WHY**：若产品未来有意提供 public API docs，不应因"docs public"自动判错。
- **处置**：主报告 §21 与 Boss Brief 均按此口径改写。

---

## E-4｜runtime env 中的 credential

- **OLD**：暗示"API key 放环境变量 = 错误设计"
- **NEW**：`CREDENTIAL_EXPOSURE_SCOPE_INCREASED`
  已知事实：**该 credential 的值在本次审计过程中进入了本地命令输出**（一次范围过宽的 env 查询）。
  环境变量承载 runtime secret 是常见且可接受的部署方式。
- **建议**：`ROTATE`（仅此一项最小动作）+ 后续审计禁止打印 secret value。
- **不新增**：KMS / HSM / Vault / 新治理系统。
- **处置**：所有报告均**不复述 key 内容**，只记录风险与动作。

---

## E-5｜`models.py` / `shared/app.js` 重构优先级

- **OLD**：`X-12 db/models.py domain split`、`X-13 shared/app.js 三端拆分` 位于 **NEXT**
- **NEW**：移入 **LATER / HOLD**
- **WHY**：按本项目 `REAL_FAILURE_BEFORE_PERMANENT_CONTROL` + Occam Razor —— **文件大/文件丑不是当前用户 blocker**。
  `REAL_FAILURE_PREVENTED`：
  - `models.py` 8,195 行：**当前无 Evidence** 证明它直接阻断业务功能（仅影响维护成本与 import 时间）。
  - `shared/app.js` 897 行三端共用：**当前无 Evidence** 证明它直接造成用户事故。
  ⇒ 两者均**不满足 NOW/NEXT 的门槛**。只有当下一阶段真实产品开发被其明显阻塞时，才顺手做必要拆分。
  **不得开启"架构整洁化"大型工程。**

---

## E-6｜D-15 从"假二选一"改为"阶段边界"

- **OLD**：
  > D-15 入驻是否允许"先建库、后认证" vs "先认证、后建库"（二选一）
- **NEW**：真正需要 Product Owner 决定的是 **两个业务事实的阶段边界**：

  > **D-15（修正）** `SUPPLIER LEGAL-ENTITY VERIFICATION` **vs** `HOTEL RELATIONSHIP / CLAIM VERIFICATION`
  > 需要决定：
  > 1. 创建账号需要什么；
  > 2. **主体认证**需要什么；
  > 3. 主体认证通过后能做什么；
  > 4. 酒店匹配 / 认领在哪一步发生；
  > 5. **酒店关系审核**需要什么证据；
  > 6. 是否允许主体先通过、酒店关系后绑定；
  > 7. 是否允许先选 canonical hotel、再认证代表关系；
  > 8. 最终什么条件解锁经营后台。

- **PM decision options（供选择，不替余总决定）**：
  - **Option A — 主体先行**：账号 → 主体认证（USCC + 营业执照 + 授权）→ 通过后解锁"酒店匹配/认领"→ 酒店关系审核 → 合同 → 开通。
  - **Option B — 关系先行**：账号 → 选/认领 canonical hotel（含判重）→ 酒店关系审核 → 主体认证 → 合同 → 开通。
  - **Option C — 并行 + 双闸**：主体与酒店关系并行提交，**两个都通过**才解锁合同阶段（保留双闸但**去掉互为前置**）。

- **核心要求（不变）**：必须消灭当前
  `APPROVE SUPPLIER` requires `APPROVED HOTEL REGISTRATION`
  而 `HOTEL REGISTRATION PATH` requires `APPROVED SUPPLIER`
  构成的 **cyclic precondition**。

---

## E-7｜统计口径统一（691 / 689 / 64%）

- **OLD**：多处写 "recovery+trust+risk+forecast = 691 / 1082 = 64%"
- **NEW**：**691 是四个非互斥正则的"求和"，不是 API 占比。** 复核：

| 项 | 值 |
|---|---|
| recovery | 290 |
| trust | 183 |
| risk | 121 |
| forecast | 97 |
| **非互斥求和** | **691** |
| **去重 union** | **305 = 28.2%** |
| 按**声明文件**归属（文件名含 recovery/trust/risk/forecast/chaos/waiver/debt/enterprise） | **287 = 26.5%** |

- **重叠证据**：`forecast` 路径 **97/97 全部包含 `recovery`**（例：`/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast/policies`）；recovery∩trust = 177、recovery∩risk = 112、trust∩risk = 112。
- **权威口径（全文统一）**：
  > **治理族路由 = 287（按声明文件，26.5%）；按路径子串 union = 305（28.2%）。二者均非互斥统计。**
- **全文处置**：所有 `691` / `689` / `64%` 一律替换为上述表述。**"64%" 撤回。** 相关定性改为："**约四分之一的 API 属于治理族**"。

### 其它数字定义统一

| 数字 | 定义（全文统一） |
|---|---|
| **1082** | 从 `application/src/go_hotel/api/routes/*.py` 解析出的 `@router.<method>` **声明数** |
| **1065 paths / 1101 ops** | 现场 `/openapi.json` 的 **path 模板数 / operation 数**（与 1082 不同基：声明数含未挂载/别名，OpenAPI 含 app 实际暴露） |
| **563 models / 564 tables** | `db/models.py` 的 `(Base)` 类数 / 现场 `information_schema` public 表数（563 + `alembic_version`） |
| **34 workflows / ~6 跑 pytest** | `.github/workflows/*.yml` 数 / 其中引用 `pytest` 的 workflow 数 |
| **83 DB-inserting test files** | `tests/` 下含 `session.add(` 或 `.add(` 的 `.py` 文件数 |
| **498 DB setup occurrences** | `tests/` 下 `s.add(`/`session.add(`/`SessionLocal.begin()` 的出现次数 |
| **287 / 305** | 治理族路由的两个口径（见上） |
| **558 (51.6%)** | dependency 集合含 `admin_principal` 的路由数 |
| **710 (65.6%)** | 路径以 `/internal` 开头的路由数 |

---

## E-8｜Supplier surfaces 表述

- **OLD**："用户会被丢进 72 个入口 / 72 个按钮"
- **NEW**：
  > **Supplier frontend defines 72 route/surface entries: 10 primary + 62 hidden.**
  产品问题表述为：**information architecture complexity high** + **hidden surface count high**；**实际同时可见导航需单独判断**。
- **WHY**：`hiddenNav` **不是**同时可见的导航项，不能直接等同于用户看到 72 个按钮。

---

## E-9｜"75% 后端路由无前端调用方"

- **OLD**：直接写成 75% API 无用
- **NEW**：保留为 **`INVESTIGATION_SIGNAL`**，并明确补一句：
  > **`NO_FRONTEND_CALLER != ORPHAN`**
  只有同时满足 **no frontend caller + no worker + no machine caller + no integration caller + no test/runtime product path** 才能判 `ORPHAN`。
- **WHY**：无前端调用方可能包含 worker、webhook、M2M、自动化、外部集成、内部 service 动作。
- **佐证**：worker 模块对 model class 的直接引用为 0（全部经 service 层），说明"通过 model 引用推断调用关系"不可靠 —— 因此该统计只能作信号。

---

## E-10｜563 model 的结论（反向加强）

- **OLD**：陈述"563 model / 564 table"
- **NEW**：显式加强为 ——

  > **GO 的主要问题不是"建了 500 张完全没人用的空表"**：
  > 563 个 model 中 **560 个在应用源码中被引用**、1 个仅测试引用、**2 个孤儿**。
  > 真正的问题是：**大量表确实进入了 service/runtime，但它们服务的是不可达、非闭环、或产品规则尚未完成的业务。**
  > 因此 **`ORPHAN_TABLE` 计数低 ≠ 数据库健康**；`REACHABILITY`（真人可达路径）才是判定标准。

- **WHY**：这是审计公平性上最重要的一条反向证据 —— 它把批评从"浪费存储"纠正为"投入方向错误"，更难被反驳，也更准确。
- **处置**：写入主报告 Executive + Engineering 节 + Boss GPT Handoff。

---

## E-11｜Security finding 级别重校准

| ID | OLD | NEW | 理由 |
|---|---|---|---|
| `SEC-01` | P0「66 条无鉴权」 | **P0（收窄）**：**35 条 `AUTH_REQUIRED`，其中 25 条 `/internal/*`** | 分类后仍有真实高价值影响（凭据写入、映射审批、作业触发）+ 现场实测可达 |
| `SEC-04` | P0 | **P0** | 现场 200 且含真实 `hotel_id: HRBUB` |
| `SEC-05` `/docs` | P1 | **P1（口径改为放大因子）** | 本身不是漏洞 |
| `SEC-06` env credential | P1 | **P1（口径改为 exposure scope）** | 环境变量承载 secret 可接受；建议 ROTATE |
| `SEC-07` demo complete-stay | P1 | **P1** | 自认 E2E helper，匿名可写 |
| `SEC-08` `/v1/hotel-media/{asset_id}` | P1 | **REVOKED（撤回）** | 复核发现**已有正确门禁**（`require_publishable=True` + `require_hotel` + 拒绝 `HOTEL_DIRECT_UPLOAD`）。**原判断错误。** |
| `SEC-10`（新增） | — | **P1** | `POST /v1/offers/{offer_id}/prebook` 匿名创建真实预占 |
| `SEC-11`（新增） | — | **P1** | `POST /v1/reviews/{review_id}/{star,tags,content}` 匿名写评价 |
| `SEC-12`（新增） | — | **P1** | `GET /v1/reviews/pending?account_id=…` IDOR（默认 `acct_demo`） |

**P0 判定门槛（本轮采用）**：现实可达路径 **+** 真实高价值影响 **+** 证据明确。仅"没有 `Depends`"或"docs 公开"**不得**判 P0。

---

## E-12｜最终 finding 数量

| 级别 | 数量 |
|---|---|
| **P0** | **4** |
| **P1** | **10** |
| **P2** | **6** |
| **P3** | **3** |
| **合计** | **23** |

（原为 P0=5 / P1=10 / P2=7 / P3=3 = 25。变化：`SEC-01` 与 `SEC-04` 合并口径保持 P0 但收窄；`SEC-08` 撤回；`.models/app.js 拆分` 由 NEXT 移入 LATER 并降 P3。）

---

## E-13｜总体 verdict 是否改变

**不改变。**

> **GO = REAL_ASSETS + BROKEN_CORE_JOURNEY + CONTROL_ONLY_MASS** 保持。

本轮修正的效果是：把三处**夸大或口径不严**的地方（64% / admin-only / 66 条安全漏洞）收紧为**可逐条证明**的表述（~26.5% / namespace vs principal 分开 / 35 条已分类），并**撤回 1 条错误 finding**、**加强 1 条反向证据**。这些修改都**削弱了对报告的反驳空间**，而非削弱结论本身。
