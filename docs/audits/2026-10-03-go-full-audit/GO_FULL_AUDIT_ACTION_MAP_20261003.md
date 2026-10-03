# GO Full Audit — Action Map

**Date**: 2026-10-03
**Principle**: Occam Razor。优先序不可颠倒：**REAL USER BLOCKER → REAL OPERATOR BLOCKER → PRODUCT RULE → DATA MODEL → IMPLEMENTATION → ONLY THEN GOVERNANCE。**
**纪律**: 不做 100 个并行任务。每项标 DOMAIN / OWNER TYPE / DEPENDENCY / WHY / CLASSIFICATION。
**Mode**: 只给方向，不改代码。

---

## NOW（本周内，止血 + 解死循环）

| # | 事项 | DOMAIN | OWNER | DEPENDENCY | WHY | CLASS |
|---|---|---|---|---|---|---|
| N-1 | **处理 35 条已确认应鉴权却匿名可达的路由**（优先 25 条 `/internal/*`；头号两条：`PUT /internal/v1/supplier-connectors/{id}/credentials` 写凭据、`POST /internal/v1/supplier-connectors/property-mappings/{id}/review` 审批映射）。**注意：19 条 `PUBLIC_BY_DESIGN` / 5 条 `MACHINE_AUTH_IMPLEMENTED` / 2 条 `AUTH_ENFORCED_IN_BODY` 不在处理范围** | Security / API | 工程 | 无 | 未授权者可读内部业务数据、触发后台作业、写凭据、审批映射、匿名创建酒店预占、匿名改任意评价（`SEC-10/11/12`） | REFACTOR |
| N-2 | **把鉴权收口为统一策略**：router 级默认鉴权 + 显式豁免清单 | Engineering | 工程 | N-1 | 三处并存（router/装饰器/签名）是漏网的根因，不收口会复发 | REFACTOR |
| N-3 | **轮换现场环境中明文的第三方 API Key** | Security | Eason（人工） | 无 | 凭据明文存在于 runtime 容器 env；审计过程中该值曾在本地命令输出中出现，需按"用完即吊销换新"处理 | KEEP（补操作） |
| N-4 | **关闭或鉴权 `/docs` 与 `/openapi.json` 的公开访问** | Security | 工程 | 无 | 852KB 全量 API schema 公开，与 N-1 叠加放大攻击面 | DELETE（公开访问） |
| N-5 | **D-15 决断（已从假二选一更正为阶段边界）**：`SUPPLIER LEGAL-ENTITY VERIFICATION` **vs** `HOTEL RELATIONSHIP / CLAIM VERIFICATION` —— 各自是什么业务事实、在流程哪一步发生、主体通过后能做什么、酒店匹配/认领在哪一步、最终什么条件解锁经营后台。含 3 个 PM options（A 主体先行 / B 关系先行 / C 并行双闸） | Product | 余总 / 产品 | 无 | **这是 B 端整条链路唯一的门**。当前 `APPROVE SUPPLIER ⇄ APPROVED HOTEL REGISTRATION` 互为前置 ⇒ cyclic precondition。完整表述见 `GO_FULL_AUDIT_ERRATA_20261003.md` E-6 | NEW |
| N-6 | **按 N-5 的决断解开死锁**（加"认领已有酒店"步骤，或把主体审批与酒店关系解耦） | Supplier | 工程 + 产品 | N-5 | 不解开，B 端所有后续工作都无法验收 | REPLACE |
| N-7 | **停止扩张治理/恢复/信任/预测域**（287–305 路由、30 导航项） | Governance | 余总 / 产品 | 无 | 服务对象（真实流量与历史样本）不存在 | DELETE（扩张） |
| N-8 | **刷新或标记失效的三处指针/文档** | Delivery | 工程 | 无 | pointer=PR320 / 现场=PR376 / candidate=DEPTH48 pr52；`GO_CURRENT_STATE.md` 落后 19 天 | REFACTOR |

---

## NEXT（解死循环之后，让链路能真的走完）

| # | 事项 | DOMAIN | OWNER | DEPENDENCY | WHY | CLASS |
|---|---|---|---|---|---|---|
| X-1 | **供应商入驻审核工作台 + 待审队列** | Supplier / Ops | 工程 | N-6 | 没有它，申请提交后无人知道它存在。**直接照抄 `hotel-direct-review.js` 的模式。** | NEW |
| X-2 | **上传能力：营业执照 / 身份证明 / 门头照 / 盖章合同** | Supplier / Document | 工程 + 产品 | D-7（隐私模型） | 目前**最明确缺失的核心底层能力之一**（并非唯一 —— reviewer workbench / password recovery / notification / contract object 同样属于 NEW）；没有它"提交主体资料"语义为空 | NEW |
| X-3 | **把入驻业务从 `payload_json` blob 提升为对象**：`application` / `review_finding` / `document` | Supplier | 工程 | X-2 的规则 | blob 无法 diff、无法约束、无法做"哪一项需要改" | REPLACE |
| X-4 | **`supplier` 实体 + `legal_entity`（含统一社会信用代码）** | Supplier / Legal | 产品 + 工程 | D-1 / D-6 | 现在 `supplier` 只是一个 ID 字符串，法律上不能确定一个主体 | REPLACE |
| X-5 | **`membership` / `staff` / `invitation`** | Identity | 产品 + 工程 | D-2 / D-12 | `identity_user.supplier_id` 单值 ⇒ 结构上排除多酒店/多员工/集团/代运营。**越晚改迁移代价越大** | REPLACE |
| X-6 | **找回密码** | Auth | 工程 | 无 | 全库 0 命中；供应商一旦忘记密码即永久失去账号 | NEW |
| X-7 | **入驻结果通知**（提交/退回/通过） | Notification | 工程 | D-11 | 用户现在只能靠反复登录猜审批结果；`OutboxRow` 与 7 个 worker 已在跑，接上即可 | NEW |
| X-8 | **合同对象**（`contract` / `contract_version`） | Contract | 产品 + 工程 | D-8 | 合同是唯一有法律约束力的产物，现在只是两个字符串 | REPLACE |
| X-9 | **错误文案映射改为后端驱动** | Frontend / API | 工程 | 无 | 129 个错误码只有 ~15 个有前端映射，其余原样上屏 | REFACTOR |
| X-10 | **接上真实供给与真实支付** | Consumer / Payment | 产品 + 工程 | 商务决策 | 否则 C 端界面只是展示品（`AOLUGUYA_*_CONFIGURED=false`、真实 PSP 未接） | KEEP（补接入） |
| X-11 | **统一产品入口（`/`）+ 三端互链** | Product surface | 产品 + 工程 | 无 | 目前 `/` = 404；用户必须知道 `/go-app/` 才能进 | NEW |

---

## LATER（真实业务跑起来之后）

| # | 事项 | DOMAIN | OWNER | DEPENDENCY | WHY | CLASS |
|---|---|---|---|---|---|---|
| L-1 | **`hotel_claim` / `ownership_dispute`** | Hotel identity | 产品 + 工程 | D-4 | 上线首日即遇"这家已被别人注册"；但规则未定前建表会绑定错误决定 | NEW |
| L-2 | **`hotel_alias` / `hotel_name_history`** | Hotel identity | 产品 + 工程 | D-3 / D-5 | 酒店改名换牌是常态；但匹配规则未定 | NEW |
| L-3 | **变更闭环**（把已存在的 `HIGH_RISK={LEGAL,ADDRESS,BRAND,QUALIFICATION}` 变更申请接上决策面） | Supplier | 工程 | D-5 | 表已存在、词表已正确，只缺决策面 | REPLACE |
| L-4 | **合同生命周期**（到期/续签/补签） | Contract | 产品 + 工程 | X-8 / D-9 | 需要先有合同对象 | NEW |
| L-5 | **退出合作（offboarding）** | Supplier | 产品 + 工程 | D-13 | 有上线就有下线 | NEW |
| L-6 | **客服/工单对象** | Support | 产品 + 工程 | D-9 | 目前只有个人信息权利申请，没有业务支持 | NEW |
| L-7 | **`admin_queues` 分页 + 业务队列补齐** | Ops | 工程 | X-1 | 7 个队列无分页；缺入驻/认领/合同队列 | REFACTOR |
| L-8 | **把已建好的治理资产接入真实业务对象** | Governance | 工程 | X-1..X-8 | 审计/双签/审批框架本身是资产，等有对象再挂 | KEEP |
| L-9 | **前端枚举词表改为由后端 schema 派生** | Frontend | 工程 | 无 | 4 张手写 JS 词表需与 563 张表手工同步 | REFACTOR |
| L-10 | **交付指针与 current-state 文档的自动刷新** | Delivery | 工程 | 无 | 否则 drift 会反复发生 | REFACTOR |
| L-11 | **`db/models.py` 按 domain 拆分（由 NEXT 降级至此）** | Engineering | 工程 | 无 | `REAL_FAILURE_PREVENTED` 当前**无法证明**：8,195 行单文件只影响维护成本与 import 时间，**无 Evidence 表明它直接阻断业务功能** ⇒ 不满足 NOW/NEXT 门槛 | REFACTOR (HOLD) |
| L-12 | **`shared/app.js` 拆为三端独立入口（由 NEXT 降级至此）** | Frontend | 工程 | 无 | 同上：**897 行**三端共用只影响维护成本，**无 Evidence 表明它直接造成用户事故** ⇒ 不满足 NOW/NEXT 门槛 | REFACTOR (HOLD) |

---

## STOP（立即停止）

| # | 停止什么 | WHY | CLASS |
|---|---|---|---|
| S-1 | 继续新建「恢复 / 信任 / 混沌 / 豁免 / 预测 / 遥测 / 身份重签发 / 联邦信任 / 信用平面容灾 / 异常债务清理」能力 | 占约 **26.5%（287 条，文件口径）／28.2%（305 条，路径 union）** 的 API、30 项导航，服务对象不存在 | DELETE（扩张） |
| S-2 | 在未决产品规则上建表（`hotel_claim` / `hotel_alias` / `contract` / `document` / `legal_entity` / `membership` / `notification` / retention / SLA / `review_finding`） | 表结构会替未决的产品决定拍板，后续必须迁移 | DELETE（扩张） |
| S-3 | 把"表/API/状态/测试/Evidence/CI/部署 存在"当作功能完成 | 这是本轮识别出的七种假完成模式的根因 | STOP（行为） |
| S-4 | 在生产面上保留该锁未锁的内部路由 | **35 条 `AUTH_REQUIRED` 存量（25 条 `/internal/*`）** + 复发风险（三处鉴权表达方式并存导致遗漏） | DELETE |
| S-5 | 公开 `/docs` 与 `/openapi.json` | 攻击面放大 | DELETE |
| S-6 | 用"先插数据库再断言"的测试充当产品验收 | 83 个测试文件 / 498 处插库；绿灯容易被读成产品完成 | REFACTOR（测试策略） |
| S-7 | 让 runtime pointer / compose 定义 / current-state 文档与实际长期不一致而不处理 | 任何以文档为准的判断都会错 | REFACTOR |

---

## 依赖关系速览

```
N-1 ──► N-2                 （先补漏，再收口策略）
N-5 ──► N-6 ──► X-1 ──► X-3 ──► X-2 ──► X-8 ──► L-3 / L-4
         │                 └──► X-4 ──► L-1 / L-2
         └──► X-5（结构决定，越早越好）
X-2 ──►（需先定 D-7 隐私模型）
X-6 / X-7 独立，可并行
X-10 依赖商务决策（真实供给与支付的商务关系）
L-8 依赖 X-1..X-8 全部就位
```

**同时进行的任务上限建议：3 条**（N-1/N-2 安全线、N-5/N-6→X-1 入驻线、X-6/X-7 基础体验线）。

---

## 不做的事（明确排除）

| 排除项 | 理由 |
|---|---|
| 重新发明 C13/C14 / 新增治理体系 | 任务边界；且 §23 已判定治理过剩 |
| 重写 C 端界面 | C 端界面是 REAL_ASSET（只需接真实供给） |
| 重写酒店库 / 审核台 / 媒体管道 / 验证码管道 | §3 REAL_ASSET，方向与实现对 |
| 为"百万用户"做架构 | 当前无真实流量；`PERF-08` 标为 UNKNOWN |
| 立刻删除治理代码 | 有 worker 依赖；只主张从导航与路线图移除 + 冻结 |
