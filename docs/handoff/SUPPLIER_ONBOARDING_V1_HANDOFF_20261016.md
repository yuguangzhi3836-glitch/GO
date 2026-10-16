# Supplier Onboarding V1 — B 端交接文档

> **TASK ID：GO-B-HANDOFF-20261016** ｜ 交接人：Eason / `chenzhenxi1-sudo` ｜ 生成：2026-10-16
>
> 本文是 **HANDOFF** 文档，不是产品验收、不是部署凭据、不是正式 Evidence。
> 所有会变化的数字（SHA / 镜像 id / 迁移 head / 服务状态）请**现场重读**，不要引用本文的历史值。
> 基线口径：HK 运行身份以**现场容器逐字节实证**为准（方法见 §4）。

---

## 1. B 端业务能力

### 1.1 已完成并已本地验证

| 能力 | 关键实现 | 验证 |
|---|---|---|
| 三合一登录（用户名 / 邮箱 / 手机同一账号） | `security/login_identity.py`、`security/service.py`、迁移 `0150` | `test_login_identifiers_and_recovery.py` 25/25 |
| 注册通道按环境能力推导 | `services/registration_verification.py::required_channels()` | `test_registration_verification.py` 20/20 |
| 邮箱验证码（真 SMTP 通道） | `services/registration_email.py`（基线已有，本轮未改） | 同上 |
| 账号找回 | `api/routes/account_recovery.py` | `test_login_identifiers_and_recovery.py` |
| 企业主体资料 | `services/legal_entity.py`、迁移 `0146` | `test_legal_entity.py` 28/28 |
| 营业执照 / 资质证件上传（私有、内容寻址） | `services/legal_entity_document.py`、`services/document_store.py`、迁移 `0147` | `test_legal_entity_document.py` 30/30 |
| 酒店搜索与认领 | `services/hotel_search.py`、迁移 `0149` | `test_onboarding_hotel.py` 29/29 |
| 入驻审核（提交 / 退回 / 重新提交 / 通过） | `services/onboarding_review.py`、`api/routes/onboarding_review.py` | `test_onboarding_review.py` 21/21 |
| 合同阶段 | `services/onboarding_contract.py`、`api/routes/onboarding_contract.py` | `test_onboarding_contract.py` 20/20 |
| 前台 / 后台界面 | `frontend/onboarding/*`、`frontend/admin/onboarding-review.js` | 浏览器验收（见 §5.3） |

### 1.2 候选能力（代码在，但依赖未就绪）

- **短信验证码**：`services/registration_sms.py` 是**刻意的空壳**——`ready()` 恒 `False`、`send_code()` 抛 `REGISTRATION_SMS_NOT_READY`。
  注册门只在**演示替身码**模式下要求它。未接真实短信通道前，它不会成为注册阻塞项（这正是 `required_channels()` 的设计目的）。
- **OIDC 登录**：`security/service.py` 已实现但**未启用**。

### 1.3 未验证 / 未部署

- 本候选**从未部署到任何环境**；HK 当前运行的仍是基线 `22df468b`（§4）。
- 合同为**测试合同**（`legal/contract/2026-10-06-test-v1/`），非真实商业合同。

---

## 2. 产品流程（申请人 → 审核员）

```
注册账号（用户名/邮箱/手机任一为登录标识）
   → 邮箱验证码（真 SMTP；演示模式为替身码）
   → 登录
   → 填写企业主体资料（legal entity）
   → 上传营业执照 / 资质证明（私有存证，见 §6）
   → 搜索或创建酒店
   → 提交入驻申请
   → GO Admin 收到待办
   → 审核退回
   → 申请人查看退回原因
   → 修改并重新提交
   → 审核通过
   → 合同阶段
   → BUSINESS_ENABLED
   → 进入经营后台
```

**验收纪律**：必须用**真实浏览器**、两个身份（酒店申请人 / GO 审核员）走完整条链；
**不得用直接改数据库替代产品流程**。本地验证码 / 本地测试合同与 HK 的真实 SMTP / 真实合同必须区分标注。

---

## 3. 技术结构（关键入口）

| 层 | 入口 |
|---|---|
| 前端 | `application/frontend/onboarding/{index.html,onboarding.js,onboarding.css}`、`frontend/admin/onboarding-review.js` |
| API | `api/routes/bff.py`（注册/登录/策略）、`account_recovery.py`、`onboarding_review.py`、`onboarding_contract.py` |
| Service | `services/{supplier_onboarding,supplier_onboarding_state,onboarding_hotel,onboarding_review,onboarding_contract,legal_entity,legal_entity_document,document_store,hotel_search,uscc,registration_verification,registration_sms}.py` |
| 安全 | `security/{login_identity,service,deps,rbac}.py` |
| 数据库 | 迁移 `0146`–`0150`（见 §6.1） |
| 文件存储 | `services/document_store.py`（内容寻址，见 §6.2） |

---

## 4. 当前版本（全部现场读取）

| 项 | 值 | 来源 |
|---|---|---|
| `GITHUB_MAIN` | `fa997b90b75956938be0387f73d17aab2d36f7a6` | GitHub live |
| `HANDOFF_PR` | **#592**（Draft，base = `release/hk-product-existing-fixes-20261007`） | GitHub live |
| `HANDOFF_HEAD` | 本分支 `chenzhenxi/supplier-onboarding-v1-20261016` tip；候选代码 tip = `32d0fa338b665ef137448fe393f6eb0aa6744dd9` | 本地 / 远端 |
| `HK_DEPLOYED_SOURCE` | `22df468b7ed22a66707d3108e3d9568597619f04`（**逐字节实证**：容器内 1639 文件全等 `22df468b:application/**`） | HK 容器 `sha256sum` 比对 |
| `HK_DEPLOYED_IMAGE` | `d093c89ec550`（tag `go-hk-test-pr:22df468b…`） | `docker inspect` |
| `HK_DATABASE_REVISION` | `0145_source_latest_index` | `environment-graph-v1.json`（现场重读） |

### 4.1 分支拓扑

```
main (fa997b90)                          ← 独立历史（36 提交，根 6a9155f5），无共同祖先
   ✗ 与 HK 线无共同祖先

HK 实际运行 22df468b   ← 已部署基线（逐字节实证）
   ├─ 89df1b6d2  fix(onboarding): bind mutation audit actors   (#558)
   ├─ 2c21b7181  test(c13): supply synthetic registration signing key (#558)
   ├─ 3fda010a3  test(c13): keep synthetic signing key stable per identity test (#558)
   │              = release/hk-product-existing-fixes-20261007 = #558 head = #592 base
   ├─ 9a721c704  feat(onboarding): land the Supplier Onboarding V1 build      （我方）
   ├─ 690f3209d  fix(registration): ask only for the codes the environment can deliver （我方）
   └─ 32d0fa338  test(c13): unify the synthetic signing key with the shared conftest constant （我方）
```

**基线口径**：本分支以 **HK 实际运行代码 `22df468b`** 为已验证业务基础，再叠 #558 三个提交与我方三个提交。
**不是**以 `main` 为基线——`main` 与 HK 线是两条**无共同祖先**的历史（§7）。

### 4.2 差异规模

| 对照 | 文件 | 增/删 |
|---|---|---|
| 本分支 vs HK 实际 `22df468b` | **63**（32 新增 / 31 修改） | +11604 / −249 |
| 本分支 vs #558 tip `3fda010a`（我方净贡献） | **59** | +11535 / −228 |

---

## 5. 验证结果（本轮）

### 5.1 工程测试

- **全量 24 套回归：`TOTAL_PASSABLE=245  RC_ALL=1`**，与上一轮权威值**逐项相同** ⇒ **零回退**。
- 4 套红 / 8 个失败项，**与基线逐条一致**（见 §5.2）。
- 受冲突影响的套件单独复跑全绿：`test_sprint1y_consumer_identity` 4/4、`test_sprint1h_onboarding` 5/5（证明 #558 的 `Principal.user_id` 审计绑定仍在生效）。

### 5.2 已知红色（均为基线 / 环境，非本轮引入）

| 套件 | 项数 | 归类 | 说明 |
|---|---|---|---|
| `test_nationwide_registration_full_app` | 3 | BASELINE_FAILURE | 断言 `property_id`，但该键在基线与本方 `bff.py` 中**从未被返回过** |
| `test_registration_terms_admission` | 2 | BASELINE_FAILURE | 断言 `acceptance_enabled is False`，实际无条件 True |
| `test_consumer_registration_open` | 2 | BASELINE_FAILURE | 抛 `REGISTRATION_DEFERRED_TERM_OVERLAP` |
| `test_depth30_native_api_contract` | 1 | ENVIRONMENT_FAILURE | 实验环境缺 `node`（`FileNotFoundError: 'node'`） |

⚠ 判据纪律：`TOTAL_PASSABLE` **只是绿套用例之和，不含红套**；判「有无回退」必须**逐套**对照上一轮 `rc/failed`。

### 5.3 迁移（真实 PostgreSQL 18.4）

全新库验证通过：`0 → 0149 → 播种旧数据 → 0150`，`email`/`phone` 列与唯一索引正确，
回填只对合法邮箱生效（`go_admin` 保持 `NULL`），`downgrade -1` 正确删列、再 `upgrade head` 回到 `0150`。

### 5.4 通道矩阵 / 现场探针 / 浏览器 / 全流程双身份

- 通道矩阵 `MATRIX=PASS`（真邮箱→`('email',)`；替身码→双通道；皆无→门关）。
- 现场探针（真实服务 + 香港形态）`PROBE=PASS`。
- **浏览器验收**（真实 Chrome，1440 与 390 双视口，全程真实点击 / 输入 / 提交，不注入 cookie）
  `CHECKS=48 FAILED=0 VIOLATIONS=0`。
  ⚠ 本轮曾在此卡住，定性为 **ENVIRONMENT_FAILURE** 而非产品缺陷：WSL 发行版在没有活动会话时
  被回收，服务随发行版重启而中断。固定一个常驻会话后 48/48 全绿，同一脚本、同一代码。
- **全流程双身份验收**（酒店申请人 → GO 审核员，真实 HTTP 表面 + 真实 PostgreSQL 18.4，
  **每次从零建库**）：`CHECKS=52 PASS=52 FAIL=0 RESULT=ALL_PASS`。
  - **A 产品主链路 16/16**：注册 → 主体资料 → 执照上传 → 搜索（新酒店查不到）→ 认领 →
    提交 → **退回并留下可执行的原因** → 重新上传 → 重提 → 通过（酒店恰好建档一次）→
    合同（只在核实后开放）→ 上传签署件 → 确认激活 → 经营后台可进。
  - **B 新酒店建档 3/3**：审批前 canonical 0 条，审批后恰好 1 条，关系恰好 1 条。
  - **C 负例矩阵 27/27**：全部以 `not 2xx` 作答，且事后状态与行数未动。
    11 个**互不相同**的真实拒绝码（`EMAIL_ALREADY_REGISTERED`、`DOCUMENT_TOO_LARGE`、
    `DOCUMENT_TYPE_UNSUPPORTED`、`UNIFIED_SOCIAL_CREDIT_CODE_ALREADY_REGISTERED`、
    `SUPPLIER_PROFILE_NOT_SUBMITTABLE`、`CONTRACT_SIGNED_DOCUMENT_REQUIRED`…）。
  - **D 数据库不变量 6/6**（含「恰好一条合同确认」）。
- **审核台浏览器验收**（真实 Chrome 打开 `/go-admin/`，用**控制台自己的登录界面**登录一个
  `GO_GOVERNANCE` 操作员，再在 `#/onboarding-review` 队列上真实点选）：`CHECKS=21 FAILED=0 VIOLATIONS=0`。
  - 队列按「等待最久优先」列出两条真实申请；详情页确实点名企业主体、列出营业执照材料、
    写明认领方式与关系。
  - **退回**：不勾选缺项时被**当场拦下**（不发请求、状态不变）；勾选 `LICENSE_ILLEGIBLE`
    并写备注后提交 → 状态变「需修改」，原因与备注都能被申请人读到。
  - **通过**：先出现二次确认并写明「创建平台身份、之后无法自动撤销」，确认后状态变
    「主体已通过」且**确实建立了酒店归属**；两条申请都离开待审队列。
  - ⇒ **双身份、双浏览器闭合**：申请人侧 48/48（§5.4 上一条）+ 审核员侧 21/21。
  - ⚠ **一条真实约束，不是缺陷**：注册每个账号要发两条验证码，而
    `/v1/registration/challenges` 有**每来源每小时 20 次**的固定窗口硬限
    ⇒ 同一来源一小时最多批量验收 **10 个账号**。脚本已改为**复用已核实的账号**而不是再注册一个，
    让整轮跑在平台自己的限制**之内**，而不是去绕它。

---

## 6. 数据库与文件持久化

### 6.1 迁移链

```
0145_source_latest_index
  → 0146_legal_entity
  → 0147_legal_entity_document
  → 0148_onboarding_constraints
  → 0149_hotel_search_indexes
  → 0150_identity_login_identifiers   （唯一 head）
```

- 链连续、无缺口、唯一 head。
- **与 `main` 的迁移链在 `0135` 正面冲突**：`main` 是 `0135_supplier_onboarding`，
  我方是 `0135_go_ai_execution` + `0135_journey_search_trigram`（同号不同 revision）。见 §7。
- 正式香港迁移**必须由授权部署通道执行**；⛔ 禁止对香港数据库直接跑未经检验的 Alembic。

### 6.2 文件持久化（**部署前必须处理**）

`services/document_store.py`：内容寻址（`led_<sha256前48><ext>`）、原子写、读回重算 sha256、
路径遍历防护（storage key 由系统生成，拒绝分隔符 / `..`）、10 MB 上限、魔数嗅探（不信任文件名/扩展名/`Content-Type`）。
**DB 只存元数据 + sha256，字节只在挂载卷上。**

**本轮实测（配好 `GO_SUPPLIER_DOCUMENT_DIR` 之后）**：验收共写入 12 个私密文件；服务重启前后
文件计数与逐个 `sha256` **完全不变**；12/12 的文件名等于其内容 sha256 的前 48 位（内容寻址在
真实字节上成立，不是设计声明）；目录位于应用树之外 ⇒ 与进程 / 容器生命周期解耦。
另一条独立佐证：两轮验收之间数据库被**整体 drop 重建**（清空全部文档行），第一轮写入的文件
仍在盘上 —— 存储与数据库是解耦的。

⚠ **现状缺口**：香港现有 compose（`go-822-staging`）**没有** `GO_SUPPLIER_DOCUMENT_DIR` 的环境变量或挂载。
默认根为 `var/supplier_documents`（容器内 `/app/var/supplier_documents`）⇒ 直接部署会把证件写进容器**可写层、重建即丢**。
对照：媒体缓存走 `GO_MEDIA_CACHE_DIR` + 宿主 `/var/lib/go-hotel/media-cache` 绑定（宿主根盘普通目录，重建不丢）。

⇒ **部署前置**：新增一个宿主持久目录（如 `/var/lib/go-hotel/supplier-documents`）绑定进 api 与各 worker，并设 `GO_SUPPLIER_DOCUMENT_DIR` 指向它。

---

## 7. 已知问题与阻塞

### 7.1 香港部署：**BLOCKED**（设计性，非缺陷）

| 阻塞 | 证据 |
|---|---|
| 候选未准入 | CC `current-candidate-override-v1.json` 指向 `b0c62bd6…`（旧 depth48 候选）；HK `/etc/go-hk-deployctl/candidates-v1/` 5 个契约均为 10-07 产物；**本候选 head 不在其中** ⇒ Forge 报 `NO_ADMITTED_CANDIDATE_FOR_HEAD` |
| 声明基线缺失 | `docs/canonical-baseline/CURRENT_HK_RUNTIME.json` 在 **`main` 上 404**（仅存在于 HK 血统分支）⇒ Forge R1 源读取 fail-closed |
| 存储未就绪 | §6.2，`PERSISTENT_STORAGE_READY = NO` |
| 权限边界 | **candidate 准入与 baseline 推进属 owner 侧**；Forge 不得自铸 candidate，我方不得推进 candidate/baseline |

⇒ 按任务约定：**不绕过、不伪造、不切旧通道、不重复建任务**；停止部署，保留交接成果。

### 7.2 GitHub main 整合：**BLOCKED**（安全条件不满足）

- **两线无共同祖先**（`git merge-base` 为空；`main` 36 提交，本线 424 提交）。
- 树差异 **814 文件**（+63410 / −52043；326 仅我方、**118 仅 main**、370 双方都改）。
- **118 个 main-only 路径**含 CI workflow（`registration-candidate-acceptance.yml`）、
  `control-plane/c13-c14-lite/*`、`control-plane/runtime-host-channel-v1/*` 等 ⇒ 直接合并有**丢失 main 独有工作**的风险。
- **迁移链在 `0135` 冲突**（§6.1）。

⇒ 任务明令「不允许通过简单覆盖某个目录来消除差异」「不允许让 main 的旧迁移链覆盖香港现有迁移链」
「无法安全完成 main 整合时可以只完成交接」。**故本轮不创建 main-target PR，避免制造一个不可安全合并的 PR**。
正确的对账方式是一次**刻意设计的 source-composite**，属 owner 决策。

### 7.3 其它

- `test_depth30_native_api_contract` 的实验室环境缺 `node`。
- 应用层「查重 + 写入」**无原子性**、DB 唯一索引**按列** ⇒ 并发窗口仍在（换绑设计见 `ACCOUNT-REBIND-DESIGN-20261007.md`，未实现）。
- 认证面 **SEC-01**（`/internal/*` 匿名可读写，根因 = 无全局鉴权中间件）**仍 live**；登录**无限流**。
- 二进制资产行尾坑：`core.autocrlf=true` + 无根 `.gitattributes` 会改坏不含 NUL 的二进制（本分支已加根 `.gitattributes` 修好）。

---

## 8. 下一步开发任务（按用户可见价值排序）

1. **补 HK 存储挂载**（`GO_SUPPLIER_DOCUMENT_DIR` + 宿主持久目录），使证件可持久化 —— 部署硬前置。
2. **产品负责人推进 baseline / 准入候选**，使新候选可被 Forge 识别。
3. 打通真实 SMTP 收信，把「本地替身码」与「HK 真实邮件」在验收中明确区分。
4. ~~审核员侧浏览器验收~~ —— **本轮已补齐**：审核台在真实 Chrome 里登录、读案、退回、通过，
   21/21 全绿（见 §5.4）。真正剩下的产品验收缺口是**真实邮件投递下的注册**：香港当前
   `enabled:false`（在线验证未配置），门是关的（§7.1）。
5. 视产品优先级再决定：真实合同、短信通道、OIDC 启用。
6. 工程债（非立即）：并发原子性、登录限流、SEC-01 鉴权中间件。

---

## 9. 接手说明（下一个 AI 怎么继续）

```bash
# 1. 取源码
git clone https://github.com/yuguangzhi3836-glitch/GO.git
cd GO && git fetch origin chenzhenxi/supplier-onboarding-v1-20261016
git checkout chenzhenxi/supplier-onboarding-v1-20261016

# 2. 关键提示：基线不是 main
#    main 与 HK 线「无共同祖先」。HK 实际运行 = 22df468b（逐字节实证）。
#    本分支 = 22df468b + #558 三提交 + 我方三提交。

# 3. 本地跑测试（SQLite 默认；PG 用 GO_TEST_DATABASE_URL）
cd application
python -m pytest tests/test_registration_verification.py -q
python -m pytest tests/test_legal_entity.py tests/test_legal_entity_document.py -q
```

- ⛔ **不要**用 `main` 覆盖 HK 线；**不要**把 `main` 的迁移链叠上来（`0135` 冲突）。
- ⛔ 不要从 `main` 起新分支做 B 端开发；从本分支起。
- 判断「现场真实字节」**必须**进容器 `sha256sum` 对 git object（`git cat-file --batch`），
  tag / mounts / 构建时间只是**线索不是证据**。
- 判「有无回退」必须**逐套**对照上一轮 `rc/failed`；`TOTAL_PASSABLE` 不含红套。

---

## 10. 尚需产品负责人决定的事项

1. baseline / 准入候选何时推进（决定部署可行性）。
2. HK 是否新增证件持久化挂载（决定 §6.2 能否满足）。
3. `main` 与 HK 线的合流方式（是否需要一次刻意的 source-composite）。
4. 合同、短信、OIDC 的启用时机与优先级。
