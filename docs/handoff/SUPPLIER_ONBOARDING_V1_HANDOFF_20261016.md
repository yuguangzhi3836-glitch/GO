# Supplier Onboarding V1 — B 端交接文档

> **TASK ID：GO-B-HANDOFF-20261016** ｜ 交接人：Eason / `chenzhenxi1-sudo` ｜ 最后更新：2026-10-16
>
> 本文是 **HANDOFF** 文档，不是产品验收报告、不是部署凭据、不是正式 Evidence。
> 配套 Evidence → `docs/handoff/SUPPLIER_ONBOARDING_V1_HK_DEPLOY_ACCEPTANCE_20261016.md`
>
> ⚠ **所有会变化的数字（SHA / 镜像 id / 迁移 head / 服务状态）请现场重读，不要引用本文的历史值。**
> 本文的香港事实采集于 2026-10-16T09:16Z–09:19Z，采集方式为现场只读复核（容器 `docker inspect`、`alembic current/heads`、环图与 install fact 的 `sha256sum`、产品端点回读）。
>
> 📌 **本文已更新为「部署后」版本**。2026-10-16 早些时候的「部署前」版本曾判定香港部署 BLOCKED、香港仍运行基线 `22df468b` —— **该判断已被本轮实际部署推翻**，本版为准。

---

## 0. 结论速览

| 项 | 状态 |
|---|---|
| 代码在 GitHub 且已推送 | ✅ 分支 `chenzhenxi/supplier-onboarding-v1-20261016`，PR **#592**（Draft / open / `mergeable_state=clean`） |
| 香港已运行本候选 | ✅ 8 个业务容器均运行 `sha256:c7977e9b…`（api healthy / restarts 0） |
| 数据库迁移 | ✅ HK 测试库 `go_hotel_stg`：`0145_source_latest_index` → `0151_legal_entity_document_blob`（current == heads） |
| 证件持久化 | ✅ 走迁移 `0151` 的数据库表；**不依赖宿主机挂载**；容器重建后字节不变 |
| 香港业务验收 | ✅ 企业资料 → 执照上传 → 酒店认领 → 提交 → 退回 → 重提 → 通过 → 合同 → 经营后台（双身份） |
| **仍未闭合** | ⚠ **注册邮箱验证码通道**在香港**未配置**（门是关的，503 fail-closed）——环境侧、需 owner 授权注入真实 SMTP 凭据 |
| main 整合 | ⛔ **仍 BLOCKED**（两线无共同祖先、`0135` 迁移链冲突），见 §7.2 |

---

## 1. B 端业务能力

### 1.1 已实现 · 已本地验证 · **已香港现场验收**

| 能力 | 关键实现 | 本地验证 | 香港验收 |
|---|---|---|---|
| 三合一登录（用户名 / 邮箱 / 手机同一账号） | `security/login_identity.py`、`security/service.py`、迁移 `0150` | `test_login_identifiers_and_recovery.py` 25/25 | ✅ 申请人 + 审核员双身份真实登录 |
| 注册通道按环境可送达能力推导 | `services/registration_verification.py::required_channels()` | `test_registration_verification.py` 20/20 | ⚠ 门未配置（§7.3） |
| 邮箱验证码（真 SMTP 通道） | `services/registration_email.py`（基线已有，本轮未改） | 通道矩阵 `MATRIX=PASS` | ⛔ 未配置，503 |
| 账号找回 | `api/routes/account_recovery.py` | `test_login_identifiers_and_recovery.py` | — （未在香港实演） |
| 企业主体资料（法人 / USCC 校验位） | `services/legal_entity.py`、`services/uscc.py`、迁移 `0146` | `test_legal_entity.py` 28/28 | ✅ `PUT/GET /bff/supplier/legal-entity` 200，存储值与输入一致 |
| 营业执照 / 资质证件上传（私有、内容寻址） | `services/legal_entity_document.py`、`services/document_store.py`、迁移 `0147`/`0151` | `test_legal_entity_document.py` 30/30 | ✅ raw octet-stream 上传 201、下载字节 sha256 一致、审核员跨角色读取一致 |
| 酒店搜索与认领 | `services/hotel_search.py`、`services/onboarding_hotel.py`、迁移 `0149` | `test_onboarding_hotel.py` 29/29 | ✅ 搜索 200；**认领已持久化且现场回读**；超状态守卫 409 |
| 入驻审核（提交 / 退回 / 重提 / 通过） | `services/onboarding_review.py`、`api/routes/onboarding_review.py` | `test_onboarding_review.py` 21/21 | ✅ 队列可见 → `NEEDS_CHANGES`（含 finding + 备注）→ 申请人可读 → 重提 → `APPROVE` |
| 合同阶段 | `services/onboarding_contract.py`、`api/routes/onboarding_contract.py` | `test_onboarding_contract.py` 20/20 | ✅ 模板可读、sha 与下载一致、签署件上传、确认 → `CONTRACT_ACTIVE` / `business_ready=true` |
| 前台 / 后台界面 | `frontend/onboarding/*`、`frontend/admin/onboarding-review.js` | 真实浏览器 48/48 + 21/21 | ✅ 静态面全部 200（`/partner/` `/go-admin/` `/supplier-console/` `/go-app/`） |

### 1.2 候选能力（代码在，依赖未就绪）

- **短信验证码**：`services/registration_sms.py` 是**刻意的空壳** —— `ready()` 恒 `False`、`send_code()` 抛 `REGISTRATION_SMS_NOT_READY`。
  注册门只在**演示替身码**模式下才要求它；未接真实短信通道前它不构成注册阻塞项（这正是 `required_channels()` 的设计目的）。
- **OIDC 登录**：`security/service.py` 已实现但**未启用**（香港 `/bff/auth/policy` 自报 `oidc_enabled=false`）。

---

## 2. 产品流程（申请人 → 审核员）

```
注册账号（用户名/邮箱/手机任一为登录标识）
   → 邮箱验证码（真 SMTP；演示模式为替身码）      ⛔ 香港未配置，门是关的（§7.3）
   → 登录
   → 填写企业主体资料（legal entity）
   → 上传营业执照 / 资质证明（私有存证，见 §6.2）
   → 搜索或创建酒店
   → 认领酒店（关系 + 证明）
   → 提交入驻申请
   → GO Admin 收到待办
   → 审核退回（可带结构化 findings + 备注）
   → 申请人查看退回原因
   → 修改并重新提交
   → 审核通过（同时建立酒店归属）
   → 合同阶段
   → BUSINESS_ENABLED
   → 进入经营后台
```

**验收纪律**：必须用真实入口、两个身份（酒店申请人 / GO 审核员）走完整条链；**不得用直接改数据库替代产品流程**。
本地验证码 / 本地测试合同与香港的真实 SMTP / 真实合同必须**区分标注**。

---

## 3. 技术结构（关键入口）

| 层 | 入口 |
|---|---|
| 前端 | `application/frontend/onboarding/{index.html,onboarding.js,onboarding.css}`、`frontend/admin/onboarding-review.js`、`frontend/shared/api.js` |
| 静态挂载 | `main.py`：`/partner` `/go-admin` `/supplier-console` `/go-app` `/console-assets` → `StaticFiles(directory=…)` **直接挂源码目录** ⇒ 改前端**不需要重建 bundle** |
| API | `api/routes/bff.py`、`account_recovery.py`、`onboarding_review.py`、`onboarding_contract.py`、`onboarding.py` |
| Service | `services/{supplier_onboarding,supplier_onboarding_state,onboarding_hotel,onboarding_review,onboarding_contract,legal_entity,legal_entity_document,document_store,hotel_search,uscc,registration_verification,registration_sms}.py` |
| 安全 | `security/{login_identity,service,deps,rbac}.py` |
| 数据库 | 迁移 `0146`–`0151`（见 §6.1） |
| 文件存储 | `services/document_store.py`（内容寻址；后端按环境自动选择，见 §6.2） |

---

## 4. 版本身份（本轮的权威值）

| 项 | 值 | 来源 |
|---|---|---|
| `REPO` | `yuguangzhi3836-glitch/GO` | GitHub live |
| `HANDOFF_PR` | **#592**（Draft / open / base = `release/hk-product-existing-fixes-20261007`） | GitHub live |
| `HANDOFF_BRANCH` | `chenzhenxi/supplier-onboarding-v1-20261016` | 本地 / 远端 |
| `BRANCH_HEAD_AT_HANDOFF` | `dd7eb4dd6fb6bcfb8f0527ae326c848d1540808e`（= PR #592 `head.sha`；**仅文档**，`application/**` 未动） | GitHub live |
| `HK_DEPLOYED_SOURCE_COMMIT` | **`3a8c43a56af742d48ca6b03b3eb6a3915d66caf2`** | 香港环图 `source_commit` + 候选事实 |
| `SOURCE_FINGERPRINT` | `76e19275992c31f8e44cfd80bd350bad3f94cd7db51b5f7b8dcd47f6245a825a` | 候选事实 |
| `APPLICATION_TREE` | **`af37d1837a54ed7f568138638c923027a318aab5`** | 候选事实；**等于 `git rev-parse HEAD:application`** |
| `HK_DEPLOYED_IMAGE_ID` | **`sha256:c7977e9b0382627e2ef5b6161b6e4630e6a1584af6782c7fcae8e67f3c2ff82f`** | `docker inspect` |
| `HK_IMAGE_REFERENCE` | `go-hk-test-pr:3a8c43a56af742d48ca6b03b3eb6a3915d66caf2` | 候选事实 |
| `HK_ARTIFACT_PACKAGE` | `sha256:5bf1599bb0951f093878ec3e61b82bb63b455ac7ecda2a209526fa72f1409beb`（116 507 136 字节） | 候选事实 |
| `HK_PREVIOUS_KNOWN_GOOD` | `sha256:d093c89ec550f2540c3da8456fb8f9111c6e0ed86b6d688fa4679ab834089e8e` | 候选事实 `rollback_relation` |
| `HK_DATABASE_REVISION` | **`0151_legal_entity_document_blob`**（current == heads） | `alembic current` / `alembic heads` 现场 |
| `HK_CANDIDATE_CONTRACT` | `fcbca9471dbb9fc98156b192827c0bbbbf4e833e958a7fc8a012961581ce5973` | /etc 只读 |
| `HK_INSTALLATION_ID` | `20261016T090041Z-b-end-g0151` | install fact |
| `HK_ENVIRONMENT_GRAPH` | `ae2bc9dc2ba9696c16cd77269447f419fd7ff58386f1a904795d17c15026ba8e` | `sha256sum` 现场 |

### 4.1 分支拓扑

```
main                                  ← 独立历史（36 提交），与 HK 线【无共同祖先】
   ✗

HK 旧运行基线 22df468b                ← 本轮之前香港实际运行（逐字节实证）
   ├─ 89df1b6d  fix(onboarding): bind mutation audit actors and correct candidate scope   （#558）
   ├─ 2c21b718  test(c13): supply synthetic registration signing key                      （#558）
   ├─ 3fda010a  test(c13): keep synthetic signing key stable per identity test            （#558）
   │             = release/hk-product-existing-fixes-20261007 = #558 head = #592 base
   ├─ 9a721c70  feat(onboarding): land the Supplier Onboarding V1 build                   （我方）
   ├─ 690f3209  fix(registration): ask only for the codes the environment can deliver     （我方）
   ├─ 32d0fa33  test(c13): unify the synthetic signing key with the shared conftest constant （我方）
   ├─ c6a282cd  docs(handoff): Supplier Onboarding V1 handoff — baseline, verification, blockers （我方）
   ├─ 791bd959  docs(handoff): record the acceptance results                              （我方）
   ├─ 034b3185  Make private applicant document bytes durable in the deployment           （我方）
   └─ 3a8c43a5  fix(upload): carry applicant evidence as an octet-stream body             （我方）
                 ▲ 本轮香港部署的 source commit
```

**基线口径**：本分支以 **HK 上一版实际运行代码 `22df468b`** 为已验证业务基础，再叠 #558 三个提交与我方七个提交。
**不是**以 `main` 为基线 —— `main` 与 HK 线是两条**无共同祖先**的历史（§7.2）。

### 4.2 差异规模

| 对照（**部署源提交 `3a8c43a5`** 为起点） | 文件 | 增 / 删 |
|---|---|---|
| vs HK 旧基线 `22df468b` | **67**（36 新增 / 31 修改） | +12 378 / −249 |
| vs #558 tip `3fda010a`（我方净贡献） | **63**（36 新增 / 27 修改） | +12 309 / −228 |

> ⚠ 上表由本地 `git diff --shortstat` 于 `3a8c43a5` 采集。分支 HEAD 在部署后多了一个**仅文档**提交
> （`dd7eb4dd`，即本文与配套 Evidence），故对 `22df468b` 现为 68 文件、对 `3fda010a` 现为 64 文件；
> GitHub PR #592 亦自报 `changed_files = 64`。**产品代码树 `application/**` 未变**（`af37d183…`）。
> **判「有无回退」不要用这些总数**，要逐套对照 `rc/failed`（§5.1）。

---

## 5. 验证结果

### 5.1 工程测试（本地实验室）

- **全量 24 套回归：`TOTAL_PASSABLE=245  RC_ALL=1`**，与上一轮权威值**逐项相同** ⇒ **零回退**。
- 4 套红 / 8 个失败项，**与基线逐条一致**（见 §5.2）。
- 受冲突影响的套件单独复跑全绿：`test_sprint1y_consumer_identity` 4/4、`test_sprint1h_onboarding` 5/5
  （证明 #558 的 `Principal.user_id` 审计绑定仍在生效）。

### 5.2 已知红色（均为基线 / 环境，非本轮引入）

| 套件 | 项数 | 归类 | 说明 |
|---|---|---|---|
| `test_nationwide_registration_full_app` | 3 | BASELINE_FAILURE | 断言 `property_id`，该键在基线与本方 `bff.py` 中**从未被返回过** |
| `test_registration_terms_admission` | 2 | BASELINE_FAILURE | 断言 `acceptance_enabled is False`，实际无条件 True |
| `test_consumer_registration_open` | 2 | BASELINE_FAILURE | 抛 `REGISTRATION_DEFERRED_TERM_OVERLAP` |
| `test_depth30_native_api_contract` | 1 | ENVIRONMENT_FAILURE | 实验环境缺 `node` |

⚠ **判据纪律**：`TOTAL_PASSABLE` **只是绿套用例之和，不含红套**；判「有无回退」必须**逐套**对照上一轮 `rc/failed`。

### 5.3 迁移（本地真实 PostgreSQL 18.4）

全新库验证通过：`0 → 0149 → 播种旧数据 → 0150`，`email`/`phone` 列与唯一索引正确，
回填只对合法邮箱生效（`go_admin` 保持 `NULL`），`downgrade -1` 正确删列、再 `upgrade head` 回到 `0150`。

### 5.4 通道矩阵 / 现场探针 / 浏览器 / 全流程双身份（本地实验室）

- 通道矩阵 `MATRIX=PASS`（真邮箱→`('email',)`；替身码→双通道；皆无→门关）。
- 现场探针（真实服务 + 香港形态）`PROBE=PASS`。
- **申请人浏览器验收**（真实 Chrome，1440 与 390 双视口，全程真实点击 / 输入 / 提交，不注入 cookie）：`CHECKS=48 FAILED=0 VIOLATIONS=0`。
- **全流程双身份验收**（申请人 → 审核员，真实 HTTP + 真实 PostgreSQL 18.4，**每次从零建库**）：`CHECKS=52 PASS=52 FAIL=0`。
  - 产品主链 16/16；新酒店建档 3/3；**负例矩阵 27/27**（11 个互不相同的真实拒绝码）；数据库不变量 6/6。
- **审核台浏览器验收**（真实 Chrome 打开 `/go-admin/`，控制台自带登录）：`CHECKS=21 FAILED=0 VIOLATIONS=0`。

### 5.5 香港现场验收（本轮新增）

> 完整证据 → `docs/handoff/SUPPLIER_ONBOARDING_V1_HK_DEPLOY_ACCEPTANCE_20261016.md`
> 原始响应体留存于香港 `/root/onb/evidence/{acceptance-…,acceptance2-…,claim-readback-…,final-…}`

- **公开面**：`/health`、`/partner/`、`/supplier-console/`、`/go-admin/`、`/go-app/`、`/console-assets/api.js`、
  `/bff/auth/policy`、`/docs`、`/openapi.json` 全部 **200**，无 5xx。
- **申请人侧**（经 `https://staging-api.goaidirect.com`，真实 cookie + CSRF 双提交）：登录 200 → `/bff/auth/me` 回本账号 →
  企业资料 `PUT` 200 → 法人 USCC 存储值 == 输入值 → **执照 raw octet-stream 上传 201** → 列表 200 →
  下载字节 sha256 与上传一致 → 元数据 200 → 酒店搜索 200。
- **审核员侧**：登录 200 → 队列**可见该案** → 案件详情 200 → **审核员读取同一执照，字节与申请人所见一致**（跨角色一致性）。
- **退回 → 重提 → 通过**：`NEEDS_CHANGES` 200（带 `LICENSE_ILLEGIBLE` finding + 备注）→ 申请人回读 `state=NEEDS_CHANGES`
  且能看到原因 → 修正后重提 → 回 `UNDER_REVIEW` → `APPROVE` 200 → 申请人 `state=VERIFIED`，
  **同时建立酒店归属**（`hotel_registration_go_direct` 恰好 1 行）。
- **合同阶段**（香港为**测试合同**，见 §7.4）：`can_confirm=true`、模板 sha 与下载文件一致 → `SIGNED_CONTRACT` 上传 201 →
  确认 200 → `state=CONTRACT_ACTIVE`、`business_ready=true`。
- **认领路径现场回读**（补证）：`GET /bff/supplier/hotel/claim` 200，返回持久化的
  `mode=EXISTING` / `relationship_type=OWNER` / `hotel_id=hotel_ac72aa53c89d4c3984b72436cb85f617` /
  `saved_at=2026-10-16T09:10:48Z`；此后 `PUT /bff/supplier/hotel/claim` 正确返回 **409 `HOTEL_CLAIM_NOT_EDITABLE`**。
- **文档持久化（决定性）**：同镜像**重建 api 容器**（`09:12:34Z`）后，两份文档仍可读且 **sha256 完全不变**；
  容器内 `find / -name "led_*"` 为 **0** ⇒ 字节不在容器可写层，走的是数据库表（§6.2）。

---

## 6. 数据库与文件持久化

### 6.1 迁移链（香港已执行）

```
0145_source_latest_index                     ← 迁移前香港 head
  → 0146_legal_entity
  → 0147_legal_entity_document
  → 0148_onboarding_constraints
  → 0149_hotel_search_indexes
  → 0150_identity_login_identifiers
  → 0151_legal_entity_document_blob          ← 迁移后 current == heads（唯一 head）
```

香港实测（`go_hotel_stg`，外部 RDS，PostgreSQL 18.4）：

| 指标 | 迁移前 | 迁移后 |
|---|---|---|
| head | `0145_source_latest_index` | `0151_legal_entity_document_blob` |
| 表 / 列 | 564 / 6 227 | 567 / 6 262 |
| `identity_user` | 1 006 | 1 007（含本轮 1 个验收账号） |
| `hotel_canonical_profile` | 114 | 114（**未变**） |

- 本轮新增：3 张表 + 4 个 `gin_trgm_ops` 索引 + 1 列族（`email`/`phone`）+ 1 个唯一索引族 + 1 个 check 约束 + 1 002 行 email 回填。
- 迁移程序指纹 `526ace41…`；**迁移前后运行时指纹完全相同**（`4a531904…`）⇒ 迁移本身未改运行时。
- 恢复点：`/home/go-forge/onb-b-end-rp-20261016T080853Z|084514Z|085239Z`（各含完整 pg_dump `08-pre-change-db.dump` ≈ 16 MB + `SHA256SUMS`）。
- ⛔ **与 `main` 的迁移链在 `0135` 正面冲突**：`main` 是 `0135_supplier_onboarding`，
  我方是 `0135_go_ai_execution` + `0135_journey_search_trigram`（同号不同 revision）。见 §7.2。
- ⛔ 正式迁移**必须由授权通道执行**；不得对香港数据库直接跑未经检验的 Alembic。

### 6.2 文件持久化

`services/document_store.py`：内容寻址（`led_<sha256前48><ext>`）、原子写、读回重算 sha256、
路径遍历防护、10 MB 上限、魔数嗅探（不信任文件名 / 扩展名 / `Content-Type`）。

**后端选择（本轮关键设计）**：`_uses_database()` = 「未设 `GO_SUPPLIER_DOCUMENT_DIR`」
⇒ 香港**没有**该环境变量，于是自动改走 **迁移 `0151` 建的表 `legal_entity_document_blob`**（`content` 为 `LargeBinary`）。

选这条路的理由写在 0151 的 docstring 里：**八个业务容器每次部署都会丢弃容器文件系统**，
本机卷不随部署搬运；而数据库表**随备份 / 恢复整体搬运**，且不需要申请新的宿主机挂载。

香港实测：

| 检查 | 结果 |
|---|---|
| 容器内 `find / -name "led_*"` | **0 个文件** ⇒ 字节不在容器可写层 |
| `legal_entity_document_blob` 行数 | 1（内容寻址去重） |
| api 容器重建后读回 | sha256 **完全不变** |
| `docker inspect` 的 supplier 文档挂载 | **无**（不依赖宿主机目录） |

> ⚠ 诚实说明：验收上传的**营业执照**与**签署合同**是**同一个 193 字节合成 PDF** ⇒ 内容寻址去重成
> **1 个 blob**、2 行 `legal_entity_document`。合同服务只校验「存在 + 模板 sha 匹配」，**不解析合同正文**，
> 因此这是可接受的测试夹具；但它**不是**对合同正文的真实性验证。

⇒ `DOCUMENT_STORAGE_PERSISTENT = YES`，实现方式为**数据库表**，非宿主机挂载。

---

## 7. 已知问题与残余阻塞

### 7.1 ✅ 香港部署 — 已完成（本轮）

曾经的三条阻塞（候选未准入 / 声明基线缺失 / 存储未就绪）本轮已逐条解决，走的是**现有 GO Forge 正式通道**：

1. 备份 + 隔离演练 + 实库迁移（授权范围内）；
2. 环图 `migration_head` 推进 `0145` → `0151`，并用主机密钥**重签** install fact；
3. 发布收敛候选事实，`migration_required=false`；
4. `FORGE` 驱动：`identity` → `precheck`（全绿）→ `recreate`（`PASS`）→ 独立 `verify`。

⛔ **未伪造 Command-Center 的 `_record_v2` deploy 记录**（驱动故意省略该步骤）；⛔ 未绕过 Forge、未切旧通道。

### 7.2 ⛔ GitHub `main` 整合：仍 BLOCKED（安全条件不满足）

- **两线无共同祖先**（`git merge-base` 为空；`main` 36 提交，本线 424 提交）。
- 树差异 **814 文件**（+63 410 / −52 043；326 仅我方、**118 仅 main**、370 双方都改）。
- **118 个 main-only 路径**含 CI workflow、`control-plane/c13-c14-lite/*`、`control-plane/runtime-host-channel-v1/*` 等
  ⇒ 直接合并有**丢失 main 独有工作**的风险。
- **迁移链在 `0135` 冲突**（§6.1）。

⇒ 任务明令「不允许通过简单覆盖某个目录来消除差异」「不允许让 main 的旧迁移链覆盖香港现有迁移链」。
正确的对账方式是一次**刻意设计的 source-composite**，属 owner 决策。**故本轮不创建 main-target PR。**

### 7.3 ⚠ 注册邮箱验证码通道在香港未配置（本轮唯一未闭合的产品可见缺口）

**这是环境配置问题，不是代码缺陷。** 现场只读证据：

| 检查 | 结果 |
|---|---|
| `/bff/auth/supplier/registration-terms` → `release_gate.registration_verification` | `{required: true, implemented: false, status: NOT_READY, reason: REGISTRATION_VERIFICATION_NOT_CONFIGURED}` |
| 同响应 `verification_channels` | `[]` |
| 同响应 `status` / `enabled` | `DRAFT` / `false`（但 `acceptance_enabled=true`、`account_stage=true`） |
| `POST /v1/registration/challenges`（完整字段、真实条款版本） | **503 `REGISTRATION_VERIFICATION_NOT_READY`** |

**根因**：香港冻结的 `runtime.env` **没有**任何 `REGISTRATION_VERIFICATION_*` / `REGISTRATION_EMAIL_CONFIG_PATH` 键
⇒ `settings.registration_verification_enabled` 默认 `False`、`registration_email_config_path` 默认 `""`
⇒ `registration_verification.ready()` 恒 `False` ⇒ 产品按设计 **fail-closed**（这是正确行为，不是 bug）。

**本地实验室已验证「通道可用 + 配置正确」**（`evidence/REGISTRATION-EMAIL-CHANNEL-VERIFY-20261016.md`）：
`smtpdm.aliyun.com:465` SSL、发信地址 `postmaster@goaidirect.com`、四层证据（SMTP 会话 / 提交 / 产品函数 / 真人收件箱）全部对齐。

**HK 上线需要（属 owner 决策，超出本次授权）**：同时注入 `REGISTRATION_VERIFICATION_ENABLED=true` 与该 JSON 配置
（`password_file` 必须**绝对路径**；**不得同时**打开演示固定码开关）。
⚠ 这意味着**改冻结 env + 注入真实 SMTP 凭据** ⇒ 必须 owner 当次明确授权。
⚠ 两个已知坑：发信走「邮件推送」`smtpdm.aliyun.com`，**不是**「企业邮」`smtp.qiye.aliyun.com`（同一密码不通用）；
发信地址**不能自投递**（服务商永久拒收 `502 Mailfrom account is a local account`）。

**本轮香港验收如何绕过这一步（明确标注为替代前置，非产品门通过）**：
验收账号由**产品自身的写边界**创建（`supplier_onboarding_service.register_account(...)` + `registration_privacy.required_decisions(policy)`），
**没有**绕过任何产品校验、**没有**直接 INSERT 数据库。这一点必须在任何对外陈述中一并说明。

### 7.4 ⚠ 合同是测试夹具，不是正式商业合同

香港合同模板 `version=2026-10-06-test-v1`、`marking=LOCAL_TEST_CONTRACT_FIXTURE`、`source=TEST`、`is_test_fixture=true`、
`blocked_external_asset=PRODUCTION_CONTRACT_TEMPLATE_REQUIRED`、sha256 `fa6394731990f7512c16c62b6edb13a902df4ccac1c907e5705a035abd665f91`、1 431 字节。

⇒ **香港测试通过不能冒充 Production 商业验收**；正式商业合同模板接入后需**重跑合同段验收**。

### 7.5 其它（沿用）

- 应用层「查重 + 写入」**无原子性**、DB 唯一索引**按列** ⇒ 并发窗口仍在（换绑设计见 `ACCOUNT-REBIND-DESIGN-20261007.md`，**未实现**）。
- 认证面 **SEC-01**（`/internal/*` 匿名可读写，根因 = 无全局鉴权中间件）**仍 live**；登录**无限流**。
  ⚠ 本轮香港验收正是经 `/internal/v1/onboarding-review/*` 完成的 —— 该路径**当前无鉴权**，属已知债务。
- `services/document_store.py` 第 6 行 docstring 仍写 "the transport is ``multipart/form-data``"，**已过时**
  （现为 raw octet-stream）。**纯注释缺陷，未修**，以免污染已验证的 `application/**` 字节。
- 二进制资产行尾坑：`core.autocrlf=true` + 无根 `.gitattributes` 会改坏不含 NUL 的二进制（本分支已加根 `.gitattributes` 修好）。

---

## 8. 下一步（按用户可见价值排序）

1. **把注册邮箱验证码通道接上香港**（§7.3）——这是唯一还挡在「新供应商能自己注册」前面的东西。
   需要 owner 授权：注入 `REGISTRATION_VERIFICATION_ENABLED=true` + email JSON + SMTP 凭据，然后重跑「注册 → 验证邮箱 → 登录」段验收。
2. **接入正式商业合同模板**（§7.4），替换 `LOCAL_TEST_CONTRACT_FIXTURE`，重跑合同段验收。
3. **`main` 与 HK 线的合流方式**（§7.2）——需一次刻意的 source-composite，属 owner 决策。
4. 给 `/internal/v1/onboarding-review/*` 加真实鉴权（§7.5；今天审核台靠的是无鉴权路径）。
5. 工程债（非立即）：查重并发原子性、登录限流、SEC-01 全局鉴权中间件。

---

## 9. 接手说明（下一个 AI 怎么继续）

```bash
# 1. 取源码
git clone https://github.com/yuguangzhi3836-glitch/GO.git
cd GO && git fetch origin chenzhenxi/supplier-onboarding-v1-20261016
git checkout chenzhenxi/supplier-onboarding-v1-20261016

# 2. 关键提示：基线不是 main
#    main 与 HK 线「无共同祖先」。香港上一版基线 = 22df468b（逐字节实证）。
#    本轮香港部署的 source commit = 3a8c43a5。
#    产品代码树：git rev-parse HEAD:application  → 应为 af37d1837a54ed7f568138638c923027a318aab5

# 3. 本地跑测试（SQLite 默认；PG 用 GO_TEST_DATABASE_URL）
cd application
python -m pytest tests/test_registration_verification.py -q
python -m pytest tests/test_legal_entity.py tests/test_legal_entity_document.py -q
python -m pytest tests/test_onboarding_hotel.py tests/test_onboarding_review.py -q
```

**判断「香港真实在跑什么」的正确方法**（不要靠 tag / 挂载 / 构建时间）：

```bash
ssh hk-staging
API=$(docker ps -q --filter label=com.docker.compose.project=go-822-staging \
                          --filter label=com.docker.compose.service=api)
docker inspect "$API" --format '{{.Image}} {{.State.Health.Status}} {{.RestartCount}}'
docker exec "$API" alembic current           # 期望 0151_legal_entity_document_blob
docker exec "$API" alembic heads
sha256sum /etc/go-hk-deployctl/environment-graph-v1.json \
          /etc/go-hk-deployctl/install-fact-v1.json
python3 -c "import json;d=json.load(open('/etc/go-hk-deployctl/environment-graph-v1.json'));\
print(d['migration_head'], d['source_commit'])"
```

**纪律**

- ⛔ **不要**用 `main` 覆盖 HK 线；**不要**把 `main` 的迁移链叠上来（`0135` 冲突）。
- ⛔ 不要从 `main` 起新分支做 B 端开发；从本分支起。
- ⛔ 部署必须走 **GO Forge** 通道；不要自己 `docker compose up`。
- ⛔ 不要伪造候选事实 / Evidence / Command-Center deploy 记录。
- 判断「现场真实字节」**必须**进容器 / 读文件算 sha256，tag / mounts / 构建时间只是**线索不是证据**。
- 判「有无回退」必须**逐套**对照上一轮 `rc/failed`；`TOTAL_PASSABLE` **不含红套**。
- 本仓 pytest **不打印汇总行** ⇒ 判据是 `rc=0` + 进度点计数。
- 变更端点需要 **CSRF 双提交**：`go_csrf` cookie == `X-CSRF-Token` 头；`/bff/auth/login` 本身不受影响。

---

## 10. 尚需产品负责人决定的事项

1. **香港注册邮箱验证通道是否配置**（§7.3）——决定「新供应商能否自助注册」。
2. **正式商业合同模板何时接入**（§7.4）——决定合同段能否算真实商业验收。
3. `main` 与 HK 线的合流方式（是否需要一次刻意的 source-composite）。
4. `/internal/*` 鉴权、短信通道、OIDC 的启用时机与优先级。
