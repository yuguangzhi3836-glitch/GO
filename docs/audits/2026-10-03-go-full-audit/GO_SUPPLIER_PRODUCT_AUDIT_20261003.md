# GO Supplier Console 产品体验审计

**Task**: GO B 端 / Supplier Console 整体产品体验审计（用户视角端到端）
**Date**: 2026-10-03
**Auditor role**: 第一次接触 GO 的酒店供应商（不是开发者、不是审核者）
**Repo**: `yuguangzhi3836-glitch/GO`
**Candidate under audit**: PR #376 HEAD `9f889acfcd36a82c7565b723261ee046c2615314`（OPEN / Draft / 未合并）
**Live entry**: `https://staging-api.goaidirect.com/supplier-console/`
**Method**: 只读。clone → 本地渲染 → 现场只读 GET → 本地 fixture 还原全部状态。**零远端 mutation。**

---

## 0. 审计对象与「现场字节 = PR376」证明

审计对象是**现场运行的那一版**，不是 main。已用字节级比对证明「我审的源码 = HK 正在跑的字节」：

| 现场资源 | live `sha256` | PR376 源码 `sha256` | 一致 |
|---|---|---|---|
| `/console-assets/styles.css` | `ffb4e3c915f4d56a44e10d3591799a53e2e199408553ee283b2a6301634e7fd1` | 同 | ✅ |
| `/console-assets/app.js` | `a778de925c93bfde738d37910d8c94d335f0af60a8356222c43bdf3efe7b81b0` | 同 | ✅ |
| `/console-assets/registration-verification.js` | `25c9ad170b40127d5d8b945afb840109de2af38e7c639e5110a8f3830bf52f5c` | 同 | ✅ |
| `/console-assets/registration-terms.js` | `c921ce6644bc33f5f92eabe660ee32ba889524521314c7e4fca887d2a94cad7e` | 同 | ✅ |
| `/console-assets/api.js` | `db986136785c830041d866ef8e2193fc7b9177e0181a6432117da6f545ae36c2` | 同 | ✅ |
| `/supplier-console/config.js` | `046157745a5656945f3730994bfa0835f9d3e05c855e72d76e9e1981c28019b5` | 同 | ✅ |
| `/supplier-console/index.html` | `f270c116a94de197fa21d8f87827ba52a90d47c3be1a0e334eebf28ea37841f6` | 同 | ✅ |
| `/console-assets/catalog-remedy.js` | `90cd822c9844e98b3dea676410965ecddafbcca04365e829b299e6db0ea66b64` | 同 | ✅ |
| `/supplier-console/catalog-fare.js` | `66eb4040a8510615a2415ca1b43ad031f2ce2598bfc60715084cfe76776b2d55` | 同 | ✅ |

> 结论：`LIVE_BYTES == PR376_SOURCE`，9/9 一致。本报告所有源码结论可直接归因于现场。

三份条款正文哈希同样与现场 registry 一致（`supplier_service_terms` `cc881504…`、`privacy_policy` `23f23efd…`、`platform_operating_rules` `0eb45f3a…`），因此本地 fixture 渲染的就是现场真实条款字节。

**审计如何做**：① `git fetch origin pull/376/head` → detached worktree；② 读 `application/frontend/**` + `application/src/go_hotel/api/routes/bff.py` + `services/registration_*.py` + `services/supplier_onboarding*.py`；③ 真实 Chrome（playwright-core + 系统 Chrome）在 **1920×1080 / 1440×900 / 1366×768 / 390×844** 打开**线上** SPA 并实测 DOM/几何/disabled 状态；④ 用本地静态服务 + API fixture，把代码里存在的**全部** onboarding 状态逐个真实渲染出来；⑤ 对 staging 只做 GET。

---

## 1. Executive Summary

**一句话**：这套 B 端目前**不是一个能给酒店客户用的产品**。工程侧交付是合格的（服务健康、8 服务跑 PR376 image、字节一致），但**产品侧还停在「后端状态机 + 一页 420px 的裸表单」阶段**。

三个最硬的结论：

1. **今天这个网址发不出去**。现场 `/bff/auth/supplier/registration-terms` 返回 `enabled=false`，注册页**每一个可操作控件都是 disabled**：`获取验证码` 不可点、验证码输入框 disabled、3 个协议勾选框 disabled、提交按钮写着「条款待确认，暂不可注册」。用户能填 9 个业务字段，然后撞死。

2. **它说的原因是错的**。真正卡住的是 **邮件验证码 runtime readiness**（后端自己的诊断字段写明 `registration_verification.status = BLOCKED`、`reason = LIVE_EMAIL_VERIFICATION_REQUIRED`），但前端把这个条件折算成一句**法律/条款**的问题：「条款正文为待确认草稿，暂不能接受或提交注册。」用户被告知一个**不存在的法律阻塞**。前端**从头到尾没有读过** `release_gate` 这个诊断字段（`grep -rn release_gate application/frontend/` → 空）。

3. **就算注册打开，供应商也走不完**。主体认证要的「营业执照资料引用 / 法人身份证明资料引用 / 酒店门头照片资料引用」和合同阶段的「已盖章合同资料引用」，在前端全是**纯文本输入框**；整个产品里**没有任何文件上传能力**（`UploadFile` 路由 0 条，页面上 `input[type=file]` 0 个）。酒店工作人员被要求**手打一个「资料引用」字符串**。这是不可能完成的核心流程。

### Product Verdict

> ## `NOT_PRODUCT_READY`

判据（按任务给的产品验收标准：一个不懂技术、没人指导的酒店工作人员，第一次打开能不能理解并走完）：

- **不能开始**：注册今天全死，且没有正确原因（P0）。
- **不能完成**：核心资料无法提交（P0）。
- **不能自救**：忘记密码没有找回路径；`CONTRACT_PENDING` 等状态是死路且只显示原始枚举；错误码原样暴露（P1）。
- **不像一个产品**：登录/入驻是 420px 居中卡片（另一套观感），后台是完整 app shell，隐私页是第三套内联样式（P1/P2）。

**P0 = 2 ｜ P1 = 7 ｜ P2 = 9 ｜ P3 = 4（共 22 条）**

---

## 2. Top Blockers

### 🔴 BLOCKER-1｜注册流程今天 100% 不可用（P0），且原因说错（P1）

**What user sees**（1920×1080 / 1440×900 / 1366×768 三个视口实测一致）：

```
提交按钮文案   : 「条款待确认，暂不可注册」          disabled = true
「获取验证码」 : 「获取验证码」                      disabled = true
邮箱验证码输入框:                                     disabled = true
3 个协议勾选框 :                                     disabled = true
条款区提示     : 「条款正文为待确认草稿，暂不能接受或提交注册。已有账号可返回登录。」
三份文档标题   : 「GO 酒店合作伙伴服务协议 · 2026-09-19-draft-v2（草稿，待确认）」×3
```

但 9 个业务字段（企业名/酒店名/省/市/地址/联系人/邮箱/手机/密码）**全部是可输入的**（`disabled=false`）。所以用户的真实体验是：**认真填完 9 个字段 → 走到验证码那一步发现全部灰掉 → 页面底部告诉他「条款是草稿」。**

**Actual behavior（现场只读 GET，2026-10-03）**：

```json
GET /bff/auth/supplier/registration-terms  → HTTP 200
{
  "acceptance_enabled": true,          ← 条款层面：允许接受（account_stage）
  "enabled": false,                    ← 前端唯一会看的字段
  "account_stage": true,
  "formal_approval_pending": true,
  "release_gate": {
    "registration_verification": {
      "required": true,
      "implemented": false,
      "status": "BLOCKED",
      "reason": "LIVE_EMAIL_VERIFICATION_REQUIRED"   ← 真正原因，前端从不读取
    },
    "formal_terms": { "required_for_account": false, "status": "PENDING" }
  }
}
```

**Likely root cause（独立验证，两层）**：

- **BFF 层**（`application/src/go_hotel/api/routes/bff.py:117`）把两个互相独立的 readiness **与**在一起：
  `'enabled': bool(policy['acceptance_enabled'] and verification_ready)`。
  而 `policy` 来自 `services/registration_terms.py:136-141` 的 `account_registration_terms_status()`，它**硬编码** `'acceptance_enabled': True, 'enabled': True, 'account_stage': True`。也就是说 —— 条款这一侧**本来是非阻塞的**；`enabled=false` **完全由 `verification_ready=false` 造成**。
- **`verification_ready = registration_verification_service.ready()`**（`services/registration_verification.py:36-41`）→ `digest()` 可用 **且** `registration_email.ready()`（`registration_email.py:39-46`）→ 需要 `settings.registration_verification_enabled` 为真 **且** `registration_email_config_path` 指向的 SMTP 配置合法且密码文件可读。
- **前端层**（`application/frontend/shared/registration-terms.js:8`）：
  `approved = policy.acceptance_enabled===true && policy.enabled===true` → `true && false` → **false**。
  第 25 行把 `approved=false` 一律翻译成「条款正文为待确认草稿…」；`app.js:219` 把 `enabled=false` 翻译成按钮文案「条款待确认，暂不可注册」。

**Why it's a product problem**
- 用户被指向**错误的领域**（去理解法律条款），而真实原因是**平台自己的邮件服务没配好** —— 这是平台侧故障，不是用户侧条件缺失。
- 平台**已经知道**真正原因（`release_gate...reason`），**也已经在代码里写好了正确文案** —— `registration-verification.js:8` 有 `REGISTRATION_VERIFICATION_NOT_READY: '邮箱验证服务暂不可用，请稍后重试。'` —— 但这条路径**永远走不到**，因为 GET 阶段就把按钮禁掉了，POST 根本发不出去。
- 只要 SMTP readiness 抖动，同样的「条款待确认」就会再次出现。这是一个**会复发**的产品缺陷，不是一次性配置事故。

**Fix direction**
1. 把「条款 readiness」与「验证码 readiness」在 BFF 响应里**拆开**，不要再用一个 `enabled` 布尔值表达两件事。
2. 前端**失去资格的原因**必须来自 `release_gate`，而不是从 `enabled=false` 反推。
3. 平台侧不可用时，文案要说平台侧：「邮箱验证服务暂不可用，请稍后重试 / 请联系平台」，**绝不能**说成条款未确认。
4. 注册页在平台不可用时应当**整体降级**（例如顶部提示 + 不让用户白填 10 个字段），而不是让用户填完再撞墙。

**Evidence**：`shots/desktop-1920x1080-02b-register-full.png`；`audit-browser-results.json`（4 视口 `submitDisabled/codeButtonDisabled/codeInputDisabled/acceptDisabled` 全为 `true`）；`live-terms.json`；`bff.py:116-121`；`registration_terms.py:136-148`；`registration-terms.js:8,25`；`app.js:219`。

---

### 🔴 BLOCKER-2｜核心资料无法提交：产品里没有任何上传能力（P0）

**What user sees**（fixture 真实渲染，`shots-fixture/A-REGISTERED.png` / `E-VERIFIED.png`）

主体认证表单（12 个字段，其中 **7 个是注册时已填过的、自动回填**）里有 4 个字段是纯文本输入框：

| 字段 label | 后端是否必需 | 前端控件 |
|---|---|---|
| 营业执照资料引用 | ✅ `business_license_ref` | `<input type="text">` |
| 法人 / 经办人身份证明资料引用 | ✅ `identity_document_ref` | `<input type="text">` |
| 酒店门头照片资料引用 | ✅ `storefront_photo_ref` | `<input type="text">` |
| 经办授权资料引用（如适用） | ❌ `authorization_ref` | `<input type="text">` |

合同阶段（`shots-fixture/E-VERIFIED.png`）只有两个字段，第一个是必填的「**已盖章合同资料引用**」——同样是一个文本框。

**Actual behavior**
- 后端状态机 `supplier_onboarding_state.py:14-17` 的 `REQUIRED_PROFILE_FIELDS` **确实要求**这三个 `_ref` 字段非空，否则 `SUPPLIER_PROFILE_INCOMPLETE:business_license_ref,identity_document_ref,storefront_photo_ref`。
- 但**全产品没有任何上传端点**：`grep -rn "UploadFile\|File(" application/src/go_hotel/api/routes/` → **0 条**。
- 页面上 `document.querySelectorAll('input[type=file]').length` → **0**。
- 字段也没有 placeholder、没有 hint、没有示例、没有 tooltip（全部为 `null`）。

**Why it's a product problem**
「资料引用」是**工程师词汇**，不是酒店工作人员能理解的词。就算他猜出「要填个编号」，他也**没有地方上传营业执照**。审核员拿到的将是一串无意义文本，主体审核必然退回 —— 而退回理由又会以原始错误码回到用户面前（见 P1-05）。

顺带一个业务合理性硬伤：**「酒店门头照片资料引用」** —— 要求人类**打字**描述一张照片。以及「法定代表人姓名」：被老板叫来注册的**收益经理 / 电商经理 / 前厅经理**通常并不知道法人姓名，也没有营业执照原件。

**Fix direction**：引入真正的文件上传（拍照/拖拽/文件选择），字段从「字符串引用」改成「上传凭证 + 本地预览 + 可替换」；`法定代表人姓名` 这类字段应说明「可稍后由管理员补充」或提供「我不知道/由主体负责人填写」的路径。**这是一个需要新增能力的改动，不是文案修补。**

**Evidence**：`app.js:243`（`onbLicense/onbIdentity/onbStorefront` → `field(...)` 生成 text input）、`app.js:253`（`contractRef`）；`bff.py:56-68`（Pydantic 全是 `str|None`，无文件类型）；`supplier_onboarding_state.py:14-17`；`probe-results.json.registerHasFileInput = 0`。

---

## 3. Complete Supplier Journey（逐阶段）

状态来源：`supplier_onboarding_state.py:9-13` —— `BUSINESS_READY={CONTRACT_ACTIVE,BUSINESS_ENABLED}`，其余全部落在入驻页；前端 `enterConsole()`（`app.js:230-234`）在 `!business_ready` 时接管整个页面。以下每一行都是**真实渲染出来的**（`fixture-render.mjs`），不是读代码推测。

| # | 状态 | 页面 h1 | 用户能做什么 | 用户不能做什么 | 下一步是否可见 | 是否死路 |
|---|---|---|---|---|---|---|
| 1 | （未登录） | `GO 合作伙伴平台` | 登录 / 点「申请成为 GO 合作伙伴」 | 无「忘记密码」 | ❌ 无 | — |
| 2 | 注册页 | `GO 合作伙伴入驻` | 填 9 个可填字段 | **无法获取验证码、无法勾同意、无法提交** | ⚠️ 文案说「条款正式确认后」 | 🔴 是 |
| 3 | `REGISTERED` | `酒店主体认证` | 填 12 字段 / 仅保存 | **4 个「资料引用」字段无法真正提供资料** | ⚠️ 只有「提交人工审核」 | ⚠️ 实质卡死 |
| 4 | `PROFILE_DRAFT` | `酒店主体认证` | 同上（已回填 7 项） | 同上 | 同上 | ⚠️ |
| 5 | `NEEDS_CHANGES` | `酒店主体认证` | 同上 + 看到退回原因 | 退回原因来自人工自由文本；**错误码场景会显示原始枚举** | ⚠️ | ⚠️ |
| 6 | `UNDER_REVIEW` | `资料正在审核` | **只有「退出登录」** | 改资料、查看进度、联系平台 | ❌ 无 | ⚠️ 无时效/无入口 |
| 7 | `VERIFIED` | `主体认证已通过` | 填「已盖章合同资料引用」 | **无法上传合同** | ⚠️ | ⚠️ |
| 8 | `CONTRACT_NEEDS_CHANGES` | `主体认证已通过` ← **标题有误导** | 改合同引用 | 同上；标题说「已通过」但正文是退回 | ⚠️ | ⚠️ |
| 9 | `CONTRACT_UNDER_REVIEW` | `合同正在审核` | **只有「退出登录」** | 查看进度、联系平台 | ❌ 无 | ⚠️ |
| 10 | `CONTRACT_PENDING` | `入驻状态待处理` | **只有「退出登录」** | 一切 | ❌ **无** | 🔴 **是** |
| 11 | 未知/未映射状态 | `入驻状态待处理` | **只有「退出登录」** | 一切 | ❌ **无** | 🔴 **是** |
| 12 | `CONTRACT_ACTIVE` | （进入 shell）`经营中心` | 10 个一级导航 | 当前酒店选择器为空 | ⚠️ | — |

**死路证据**（真实渲染文案）：

```
H-CONTRACT_PENDING →  入驻状态待处理
                      当前状态：CONTRACT_PENDING          ← 原始枚举
                      退出登录

J-UNKNOWN_ENUM     →  入驻状态待处理
                      当前状态：SOME_INTERNAL_STATE       ← 原始枚举
                      退出登录
```

**Why it's a product problem**：`CONTRACT_PENDING` 在**后端下一步映射里是存在的**（`_next_step` → `SUBMIT_CONTRACT`），但**前端没有为它写任何分支**，掉进 `else` 兜底。用户看到的是一个英文枚举 + 一个退出按钮，**既不知道发生了什么，也不知道该做什么，更没有任何求助入口**。任何未来新增状态都会自动变成死路 —— 这是结构性的。

**Fix direction**：前端对所有状态必须**穷举或显式兜底到「联系平台 + 我来处理」**；兜底页禁止出现原始枚举，改用「你的入驻状态需要人工处理，请点击这里联系平台（附主体名称与编号）」。`CONTRACT_PENDING` 应当并入 `VERIFIED` 的合同提交分支。

---

## 4. Desktop UX Findings

测量环境：真实 Chrome，`deviceScaleFactor=1`。

| 视口 | `.login-card` 实宽 | 注册页文档高 | 折算「屏幕数」 | 横向溢出 | 卡片占屏宽 |
|---|---|---|---|---|---|
| 1920×1080 | **420px** | 1676px | **1.55 屏** | 否 | **22%** |
| 1440×900 | **420px** | 1676px | **1.86 屏** | 否 | **29%** |
| 1366×768 | **420px** | 1676px | **2.18 屏** | 否 | **31%** |

- `UI-WIDTH-01`（**P1**）**KNOWN-01 已独立验证并成立**。根因：`styles.css` 第一条规则 `.login-card{width:min(420px,calc(100vw - 32px))}`，而**注册页、主体认证页、审核中页、合同页、合同审核中页、兜底页全部复用 `.login-card`**（`app.js:219,222,243,250,253,257,259`）。一个为「用户名+密码」设计的登录卡，被拿去承载 10~12 个字段 + 验证码 + 3 份法律文档 + 4 个勾选框。
- 具体后果：1366×768 下 10 个字段全部 360px 宽、垂直 pitch 约 83px；**主操作与全部同意控件 100% 在首屏之外**；3 份共 ~16KB 的条款正文被塞进 ~380px 宽的 `<pre>`；屏幕其余 69%~78% 是纯色空场。
- 明显的浪费：同一页面上 `.content{max-width:1500px}` 和 `.grid{repeat(4,1fr)}` 这些「宽屏设计」规则本来就在 CSS 里，**只是注册/入驻这条链路没有用**。
- 无桌面分栏：地址 4 个字段（省/市/详细地址）竖排单列，本可 2 栏；条款区本可右侧固定、左侧表单。
- 无横向溢出（好）、disabled 控件被正确跳过 tab（好）、`focus-visible` outline 已定义（好）。

`UI-WIDTH-01` 定级说明：纯宽度问题按定义是 P2（布局/专业度，不阻塞）；我定为 **P1**，因为它同时破坏了「协议知情同意」的可读性（380px 宽度读 3 份条款）并让全部主操作落到首屏之外，跨 5 个页面 —— 若 Eason 认为第一印象可容忍，这一条可降为 P2。原始测量数字已给出，可自行改判。

---

## 5. Mobile UX Findings

测量环境：390×844（iPhone 14 尺寸）。

- **注册页**：卡片 358px / 输入框 298px / 文档高 1732px（2.05 屏）。**无横向溢出**。字段垂直 pitch 与桌面相同（~83px），一屏只能看 5 个字段。**没有 sticky 主操作**，提交按钮在最底部 —— 用户必须滚过全部 10 字段 + 验证码 + 协议 + 3 份文档才能碰到「提交」。
- **输入可用性：实测合格**。10 个输入框与 3 个按钮在 390×844 下均为 **298×44px**（全局 `styles.css:134` 的 `btn,input,select,textarea{min-height:44px}` 生效），**满足 44px 触控目标**。唯一的例外是 `<a>隐私与数据权利</a>`，高度仅 **20px**（全页唯一的触控目标失败项，P3）。`#acceptTerms` 复选框本体宽 13px，但它被 `<label>` 包裹（`wrappedInLabel: true`，label 行高 60px），实际可点区域足够。
- **键盘弹出**：代码中**没有** `visualViewport` 监听、也没有 sticky/固定主操作（注册页在 `.login-screen` 下，完全不命中 `.supplier-shell` 那套移动规则）。主操作位于文档流最底部（1732px 处），键盘弹出后仍需继续滚动才能触达。
- **后台 shell（`CONSOLE-mobile-command.png`）**：**这一层做得好**。底部 5 项固定导航（首页/履约/促销权益/财务/我的）、卡片两列、表格转卡片式、`padding-bottom:82px` 避开底部栏、`env(safe-area-inset-bottom)` 已处理。
- **结论**：移动端的问题不在「适配」，而在**入驻链路根本没被当成移动端页面设计过** —— 后台有移动 IA，入驻没有。

---

## 6. Registration & Verification

**字段逐项判断**（`app.js:219`）

| 字段 | 现在必须？ | 正常供应商知道怎么填吗 | 是否过早索要 | 可否后置 |
|---|---|---|---|---|
| 企业 / 酒店主体名称 | ✅ | ⚠️ 需与营业执照完全一致，但页面没说 | 否 | 否 |
| 酒店名称 | ✅ | ✅ | 否 | 否 |
| 省 / 自治区 / 直辖市 | ❌ 可选 | ⚠️ 自由文本，无选择器；label 要求用户翻译成平台数据模型 | 否 | 可 |
| 城市 | ❌ 可选 | ⚠️ 同上 | 否 | 可 |
| 详细地址 | ❌ 可选 | ✅ | 否 | 可 |
| 联系人姓名 | ✅ | ✅ | 否 | 否 |
| 邮箱 | ✅ | ✅（但也是**登录用户名**，页面没说明这一点） | 否 | 否 |
| 手机号 | ❌ 可选 | ✅ | **✅ 过早**：全流程唯一的验证是邮箱，手机号**没有任何用途**（无短信、无验证） | 可删/可后置 |
| 设置密码 | ✅ | ⚠️ `minlength=10` 但**页面不显示密码规则**，用户要猜 | 否 | 否 |
| 邮箱验证码 | ✅ | ✅ | 否 | 否 |

**重复信息**：注册收 9 项（org/hotel/province/city/street/contact/email/phone/password），紧接着的「酒店主体认证」页**又把其中 7 项（除 email/password）重新展示一遍**。虽然做了自动回填（`shots-fixture/B-PROFILE_DRAFT.png` 已确认回填生效，这点是对的），但用户会强烈感到「我刚填过，为什么又让我确认一遍」。

**邮箱验证码**：
- 「获取验证码」**什么时候可以点**：`sending || 倒计时>0 || !policy().enabled || !accepted.checked || !choicesReady`（`registration-verification.js:51`）。当前 `policy().enabled=false` ⇒ **永久不可点**。
- **为什么不能点时是否说明真正原因**：❌ **没有**。按钮只是灰的，旁边没有任何说明，只有一个 aria-live 状态位在别处显示错误结论。
- **邮件没到怎么办**：只有一句「请查看邮箱（包括垃圾邮件），10 分钟内有效」（发送后才出现），**没有「重新发送」的独立入口、没有客服入口**。
- 重发机制（若可用）：60 秒冷却 + 文案 `N 秒后可重发`（`registration-verification.js:52`）—— 设计是对的。
- **邮箱改动后的行为**：✅ 做得好 —— 清空验证码、清空 challenge、提示「邮箱变化后请重新获取验证码。」并递增 `revision` 做竞态保护。
- **验证码错误提示**：✅ 已映射：`REGISTRATION_CODE_INVALID_OR_EXPIRED → '验证码不正确、已过期或已使用，请检查或重新获取。'`
- **SMTP / readiness 不可用时前端说什么**：❌ 说「条款正文为待确认草稿」。**正确文案 `'邮箱验证服务暂不可用，请稍后重试。'` 已经写在 `registration-verification.js:8`，但永远显示不出来。**

---

## 7. Terms & Consent

- `TERMS-DRAFT-EXPOSED`（**P1**）用户在注册页被要求勾选「我已阅读并接受供应商服务条款」的三份正文，**本身是内部草稿**，其首行原文：
  > 「待确认草稿｜版本 2026-09-19-draft-v2｜拟定日期 2026-09-19｜**尚未生效，不供注册勾选**。」
  > 「本文是供**运营方、业务负责人和法律顾问核定**的完整条款草稿，不是法律认证。」

  正文末尾还带一份**平台自己的法律待办清单**（「生效前必须补齐的附表」：统一社会信用代码待补、留存期限待确认、跨境清单待逐项确认、批准记录待补…）。也就是说：**一旦邮件 readiness 打开，供应商就会读到一份「我们的法律服务还没定稿」的待办清单，并被要求对此作出同意。**

- 更矛盾的是**页面自己的文案与后端策略互相打脸**：
  - 注册页文案：「**条款正式确认后**可提交入驻申请。」
  - 后端策略：`account_registration_terms_status()` **硬编码 `acceptance_enabled: True` / `account_stage: True` / `formal_approval_pending: True`**，后端部署常量 `release_gate.formal_terms.required_for_account = false` —— 即「账号阶段**允许**用草稿条款」。
  - 而条款正文说「**不供注册勾选**」。
  三方各说一套。**这不是我可以替产品/法务决定的事**，但它必须被决定 —— 当前状态下，无论 open 还是 close，页面上的话都是错的。

- `CONSENT-ABOVE-DOCS`（**P2**）DOM 顺序是：验证码区块 → **3 个「我已阅读并接受…」勾选框** → 三份文档正文。**用户在阅读文档之前就先被要求声明「我已阅读」**。
- `DEFERRED-TERMS-COPY`（**P2**，正向）**做得对的一处**：`registration-terms.js:33-35` 明确把延后条款说清楚 ——「电子签约授权将在合同阶段另行确认」「数据协作条款将在启用相应业务能力时另行确认」—— 这正是 KNOWN-02 里「分阶段」设计应有的表达方式。**但同一段代码第 25 行又把技术 gate 说成条款问题**，前后不一致。

---

## 8. Onboarding & Resume

- **可保存草稿**：✅ 「仅保存，稍后继续」按钮存在，调 `PUT /bff/supplier/onboarding/profile`，状态置 `PROFILE_DRAFT`。
- **中途退出再登录恢复**：✅ 逻辑正确 —— 每次登录 `enterConsole()` → `api.me()` → `onboarding` → 按 state 回落到对应页面，已保存字段回填。
- **但「恢复」的可见性很差**：回到页面时**没有任何「上次填到哪、还差什么」的提示**。表单 12 个字段是平的，用户不知道「还缺 4 个必填项」，必须点提交后由后端报错才知道 —— 而这个报错是 `SUPPLIER_PROFILE_INCOMPLETE:business_license_ref,identity_document_ref,storefront_photo_ref`（**原始枚举 + snake_case 字段名**，见 P1-05）。
- **重复信息**：见 §6。7 项已填字段在入驻页被再次呈现（虽回填）。
- **退回（`NEEDS_CHANGES`）**：✅ 有 `<div class="notice error">` 显示 `review_note` 原文。⚠️ 但 `review_note` 是人工自由文本，没有结构化「哪一项错了」的定位；用户要自己对照 12 个字段找。
- **无进度指示**：四个阶段（创建账号 → 主体认证 → 合同 → 开通）在任何一个入驻页上都**没有 stepper / 进度条**。用户始终不知道「我在第几步、还剩几步」。这是「用户不知道当前处在哪一阶段」的直接证据。
- **无预计时长 / 无联系方式**：`UNDER_REVIEW` / `CONTRACT_UNDER_REVIEW` 页面只有「退出登录」。没有「通常 N 个工作日」、没有「联系平台」、没有「查看进度」。

---

## 9. Contract Stage

- 入口文案正确：「下一步完成合作合同。合同审核通过后才进入正式经营后台。」
- 但**唯一的输入是「已盖章合同资料引用」文本框** —— 与 BLOCKER-2 同源。一个已经盖好章的 PDF 合同，用户**没有地方上传**。
- `CONTRACT_NEEDS_CHANGES` 复用 `VERIFIED` 的 `h1`「主体认证已通过」（`app.js:253`，两个 state 共用一个分支）。被退回的用户看到大标题说「已通过」，会以为系统出错了。`h1` 应为「合同需要修改」。
- `CONTRACT_UNDER_REVIEW` / `CONTRACT_PENDING` 是死路（见 §3）。

---

## 10. Error & Recovery

模拟与代码核查结果：

| 场景 | 用户看到 | 能否理解并恢复 |
|---|---|---|
| 浏览器刷新 | 重新走 `api.me()` → 回到同一入驻页 | ✅ 可以 |
| 关闭页面重进 | 同上 | ✅ 可以 |
| 登录过期（401 `AUTHENTICATION_REQUIRED`） | `userFacingError` 映射表**没有**此项 ⇒ 原样显示 `AUTHENTICATION_REQUIRED` | ❌ |
| **忘记密码** | **页面上根本没有找回入口**（`hasForgotPassword: false`，`<a>` 数量 = 0） | 🔴 **无法恢复** |
| 验证码失效 | → 映射为「验证码不正确、已过期或已使用，请检查或重新获取。」 | ✅ |
| 验证码输错 | 同上 | ✅ |
| **注册重复邮箱** | 后端返回 `USERNAME_ALREADY_REGISTERED`；两个映射表都没有它 ⇒ **页面显示 `USERNAME_ALREADY_REGISTERED`** | ❌ |
| 主体资料不完整 | → **`SUPPLIER_PROFILE_INCOMPLETE:business_license_ref,identity_document_ref,storefront_photo_ref`** 原样显示 | ❌ |
| 审核退回 | `notice error` 显示人工 `review_note` | ✅ |
| 合同退回 | 同上，但 h1 错误（§9） | ⚠️ |
| API 503 / 409 / 403 | `raw()` 把 `data.detail` 当 message；未映射 ⇒ 原样显示枚举 | ❌ |
| 后端 gate unavailable（`REGISTRATION_TERMS_UNAVAILABLE`） | `supplierRegisterView` 的 catch 只写进 `#loginErr`（`app.js:219`），但此时页面**已经不在登录视图**，`loginForm.isConnected` 为假 ⇒ **静默失败，什么都不发生** | 🔴 |
| 后台某视图读取失败 | ✅ 兜底卡片「页面暂时无法打开 / 读取未完成，请重新加载。…可返回经营中心」 | ✅ |

`RAW-ERROR-CODES`（**P1**）根因：`app.js:47` 的 `userFacingError` 只映射 8 个鉴权类码；`registration-verification.js:3-11` 的 `message()` 只映射 7 个注册类码。两个表的兜底都是 `return error?.message`（原样）。**已映射的码总数 ≈15，未映射的码会把 `SCREAMING_SNAKE_CASE` 直接印在酒店员工脸上。**

`SILENT-FAIL-01`（**P1**）上面第 13 行是一个单独缺陷：条款接口 503 时注册页会**静默不动**，用户点了按钮但页面毫无反应、没有任何提示。

---

## 11. Copy / Language

找到的「工程师语言 / 内部状态 / 英文枚举」逐条：

| ID | 出现在哪 | 原文 | 问题 |
|---|---|---|---|
| `COPY-01` | 主体认证表单 | **「营业执照资料引用」「法人 / 经办人身份证明资料引用」「酒店门头照片资料引用」「已盖章合同资料引用」** | 用了 4 次「资料引用」。含义未定义，指向一个不存在的上传动作 |
| `COPY-02` | 后台顶栏 / 侧栏 | `SUPPLIER_USER`（badge）、`SUPPLIER_OWNER`（sidebar footer，来自 `me.roles.join()`） | 原始枚举直接暴露 |
| `COPY-03` | 兜底入驻页 | 「当前状态：`CONTRACT_PENDING`」/「当前状态：`SOME_INTERNAL_STATE`」 | 原始枚举，且无任何解释 |
| `COPY-04` | 条款区 | 「条款正文为待确认草稿」 | 把技术 gate 说成法律问题（见 BLOCKER-1） |
| `COPY-05` | 注册页文案 | 「条款正式确认后可提交入驻申请」 | 与后端 account_stage 策略矛盾（§7） |
| `COPY-06` | 后台指标卡副文案 | 「**以当前可验证事实为准**」×4 | 证据/审计语言，酒店收益经理不这样说话 |
| `COPY-07` | 后台经营中心 | 「**结构化运营**」 | 内部术语 |
| `COPY-08` | 后台经营中心 | 「**技术信息 / 高级信息**」折叠区（内含「字段定义仅供技术诊断使用，不作为酒店员工的主操作界面」） | 供应商后台里出现技术诊断面板 |
| `COPY-09` | 登录页 | 「**MFA 动态码（已绑定账号填写）**」 | 合作伙伴登录页出现管理员术语，未解释 MFA 是什么 |
| `COPY-10` | 各错误提示 | `USERNAME_ALREADY_REGISTERED` / `AUTHENTICATION_REQUIRED` / `SUPPLIER_PROFILE_INCOMPLETE:…` | 原始码未翻译 |
| `COPY-11` | 条款正文 | 「待确认草稿｜…｜尚未生效，不供注册勾选」 | 内部草稿声明出现在用户同意页 |
| `COPY-12` | 后台兜底 | 「空数据不会被视为今天已完成履约」 | 审计语言混入经营文案 |

---

## 12. Backend-to-Frontend Semantic Mismatches

这一类是本次审计**最本质**的问题，单独成节。

### M-1｜`enabled` 一个布尔挤进两个独立含义

```
后端 account_registration_terms_status()   →  acceptance_enabled=True,  enabled=True,  account_stage=True
BFF  /bff/auth/supplier/registration-terms →  enabled = (acceptance_enabled AND verification_ready)
前端 registration-terms.js:8               →  approved  = (acceptance_enabled AND enabled)
```
后端**已经**把「条款可用」和「账号阶段允许草稿」表达清楚了（`account_stage/formal_approval_pending`），但 BFF 用**同一个字段名 `enabled` 二次覆盖**，把邮件服务的 readiness 掺了进去。前端无法分辨，必然误判。

### M-2｜真实原因存在但被丢弃

`release_gate.registration_verification = {status:'BLOCKED', reason:'LIVE_EMAIL_VERIFICATION_REQUIRED', implemented:false}` **就在同一个响应体里**，前端**零引用**。诊断信息已经产出、已经传输、然后被丢掉。

### M-3｜正确文案存在但不可达

`registration-verification.js:8`：`REGISTRATION_VERIFICATION_NOT_READY: '邮箱验证服务暂不可用，请稍后重试。'`
这条文案**只可能**在 `POST /bff/auth/supplier/register` 返回 503 时触发；但 GET 阶段已把提交按钮禁用 ⇒ **永久不可达**。

### M-4｜页面文案 vs 后端策略 vs 条款正文，三方互斥

| 来源 | 说法 |
|---|---|
| 注册页文案 | 「条款**正式确认后**可提交入驻申请」 |
| 后端策略常量 | `formal_terms.required_for_account = false`（账号阶段不要求正式条款） |
| 条款正文 | 「**不供注册勾选**」 |

### M-5｜后端状态存在，前端没有分支

`_next_step()` 认识 `CONTRACT_PENDING`；`supplierOnboardingView()` 不认识 ⇒ 掉进 `else` ⇒ 用户看到原始枚举死路。**新增任何状态都会自动变成死路。**

### M-6｜后端要求「资料」，前端只给「字符串」

`REQUIRED_PROFILE_FIELDS` 要 `business_license_ref` / `identity_document_ref` / `storefront_photo_ref`；Pydantic 类型是 `str|None`；前端是文本框；而**上传通道根本不存在**。三方各自都「自洽」，合起来不可用。

---

## 13. Finding Matrix

| ID | Sev | Journey Step | What user sees | Evidence | Likely root cause |
|---|---|---|---|---|---|
| `DOC-REF-NO-UPLOAD` | **P0** | 主体认证 / 合同 | 「营业执照资料引用」等 4 个文本框；无上传 | `app.js:243,253`；`bff.py:56-68`；0×`UploadFile`；0×`input[type=file]` | 缺少文件上传能力；引用字段被当字符串 |
| `REG-BLOCKED-TODAY` | **P0** | 注册 | 提交按钮「条款待确认，暂不可注册」+ 全部控件灰 | `live-terms.json`（`enabled:false`）；`audit-browser-results.json` 4 视口 | `registration_email.ready()==False` |
| `SEM-WRONG-REASON` | **P1** | 注册 | 被告知条款是草稿；真因是邮件服务 | `bff.py:117`；`registration-terms.js:8,25`；`release_gate` 前端零引用 | `enabled` 语义合并 + 前端不读诊断 |
| `UI-WIDTH-01` | **P1** | 注册 + 4 个入驻页 | 1920 下 420px 竖条，1366 下 2.18 屏 | `styles.css` `.login-card{width:min(420px,…)}`；实测表 §4 | 复用 `.login-card` 承载 10-12 字段表单 |
| `NO-PASSWORD-RECOVERY` | **P1** | 登录 | 没有任何找回入口 | `probe-results.json.login.hasForgotPassword=false`，`links=[]` | 未实现 |
| `DEAD-END-RAW-ENUM` | **P1** | `CONTRACT_PENDING` / 未知态 | 「当前状态：CONTRACT_PENDING」+ 退出 | `shots-fixture/H-CONTRACT_PENDING.png`；`app.js:259` | 前端未穷举状态，`else` 兜底 |
| `RAW-ERROR-CODES` | **P1** | 全部错误路径 | `USERNAME_ALREADY_REGISTERED` 等原样显示 | `app.js:47`；`registration-verification.js:3-11` | 映射表只覆盖 ~15 个码 |
| `SILENT-FAIL-01` | **P1** | 注册（条款 503） | 页面毫无反应 | `app.js:219`（写 `#loginErr`，但登录视图已不在） | catch 写入了错误的容器 |
| `TERMS-DRAFT-EXPOSED` | **P1** | 条款同意 | 同意对象是「尚未生效，不供注册勾选」的草稿 + 平台法律待办 | 三份 `.md` 第 3、5 行与附表 | 草稿条款与账号阶段策略未对齐 |
| `CONSENT-ABOVE-DOCS` | P2 | 条款同意 | 勾选框在文档正文**之前** | `app.js:219` DOM 顺序；截图 | 渲染顺序把 decisions 放在 documents 前 |
| `RAW-ROLE-ENUMS-IN-CHROME` | P2 | 后台 | `SUPPLIER_USER` / `SUPPLIER_OWNER` | `CONSOLE-desktop-command.png`；`app.js:263` | 直接渲染 `me.actor_type` / `me.roles` |
| `NO-FIELD-GUIDANCE` | P2 | 注册 + 入驻 | 22 个输入框全部无 placeholder/hint | `probe-results.json.registerFields` | 未设计辅助文案 |
| `NO-AUTOCOMPLETE` | P2 | 注册 | 邮箱/密码/电话无法被密码管理器识别 | 同上（`autocomplete: null`） | 未设置 autocomplete |
| `H1-COLLISION` | P2 | `CONTRACT_NEEDS_CHANGES` | h1 写「主体认证已通过」但正文是退回 | `app.js:253`（两 state 共用） | 分支合并 |
| `MFA-VOCAB-ON-LOGIN` | P2 | 登录 | 「MFA 动态码（已绑定账号填写）」 | `app.js:218` | 管理员术语泄漏到伙伴登录页 |
| `ENGINEERING-COPY` | P2 | 后台 | 「以当前可验证事实为准」「结构化运营」「技术信息/高级信息」 | `CONSOLE-desktop-command.png` | 审计语言未做产品化改写 |
| `THIRD-VISUAL-SYSTEM` | P2 | 隐私页 | `privacy.html` 自带一套内联样式，非 GO VI | `privacy.html`（`#12213c`、`system-ui`、裸 `border:1px solid #ddd`） | 独立页面未接设计系统 |
| `AUTH-STATES-BARE` | P2 | 审核中 ×2 | 只有标题 + 「退出登录」，无时长/进度/联系 | `shots-fixture/D-*,G-*.png` | 状态页未产品化 |
| `NAV-MAX-VIOLATED` | P3 | 后台 | 一级导航 10 项 | `config.js` `partnerPrimaryNavMax:7` vs 实测 10 项 | 声明与实现不一致 |
| `REGISTER-DROPS-BRAND` | P3 | 注册 | 登录页有 GO 标识，注册页没有 | 两处截图对比 | 注册视图未复用 brand lockup |
| `PRIVACY-LINK-ODD` | P3 | 注册 | 「隐私与数据权利」链接位于 h1 之下、说明段落之前，是全页首个可聚焦元素；且高仅 **20px**，是全页唯一的 44px 触控目标失败项 | `probe-results.json.tabOrder[0]`；移动端实测 `minTouchFailures` | 模板顺序 + 未设 min-height |
| `NO-SKIP-LINK` | P3 | 注册 | 键盘用户需 Tab 11 次才越过表单 | `tabOrder`（10 input → 返回登录） | 未提供跳转链接 |

**统计：P0 = 2 ｜ P1 = 7 ｜ P2 = 9 ｜ P3 = 4 ｜ 共 22 条。**

---

## 14. Recommended Product Fix Order

> 只给产品方向，不给修复代码，不开 PR。

**第一步（解除硬阻塞，最小改动）**
1. `SEM-WRONG-REASON` + `SILENT-FAIL-01`：把「条款 readiness」与「验证码 readiness」在 BFF 响应里拆成两个字段；前端封锁原因**只允许**来自 `release_gate`；平台侧不可用时文案改为平台侧口吻；修掉条款 503 静默失败。
2. `REG-BLOCKED-TODAY`：确认 HK 的邮件验证 readiness 是**有意关闭**还是**配置遗漏**。若是遗漏 → 这是环境修复；若是有意 → 注册页应当整体显示「暂未开放注册，请留下联系方式」而不是让人白填 9 个字段。

**第二步（让流程真的能走完）**
3. `DOC-REF-NO-UPLOAD`：引入文件上传（营业执照 / 身份证明 / 门头照 / 已盖章合同）。这是本次审计中**唯一需要新增能力**的一项，也是 P0。
4. 同步把「资料引用」这类词汇换成「上传营业执照 / 上传身份证件 / 上传门头照」+ 预览 + 替换。

**第三步（把入驻链路从「裸表单」改成「产品」）**
5. `UI-WIDTH-01`：为注册/入驻链路建立**独立的宽屏布局**（表单分栏、条款侧栏、宽屏容器），停止复用 `.login-card`。
6. `DEAD-END-RAW-ENUM` + `RAW-ERROR-CODES` + `NO-PASSWORD-RECOVERY`：状态穷举 + 错误码全量映射 + 登录找回入口。这三项合起来决定「用户出事时能不能自救」。
7. `AUTH-STATES-BARE`：审核态加 stepper / 预计时长 / 联系方式。

**第四步（产品化收尾）**
8. `TERMS-DRAFT-EXPOSED` + `M-4`：就「账号阶段是否允许草稿条款」给出**一个**产品/法务决定，然后让页面文案、后端常量、条款正文三者一致。
9. `CONSENT-ABOVE-DOCS`、`H1-COLLISION`、`RAW-ROLE-ENUMS-IN-CHROME`、`ENGINEERING-COPY`、`THIRD-VISUAL-SYSTEM`、`COPY-*` 其余项。

---

## 15. 最后三个问题的明确回答

### 1. 今天如果把这个网址发给一个真实酒店，让他自己注册，是否合适？

**不合适。明确不合适。**

理由（任一条单独就足以说不）：
- 他今天**注册不了** —— 填完 9 个字段后会撞上一个全部灰掉的表单。
- 他得到的解释是**错的** —— 页面告诉他「条款待确认」，真实原因是平台自己的邮件服务没就绪。他会去质疑「你们协议没定稿就让我注册？」而不是「你们服务没配好」。
- 就算注册打开，他在**主体认证第二步就会永久卡住** —— 被要求「填营业执照资料引用」，而产品里没有上传按钮。
- 他如果忘密码，**没有任何找回途径**。

### 2. 最大的 5 个产品问题是什么？

1. **注册今天全死，且把技术问题说成法律问题**（`REG-BLOCKED-TODAY` + `SEM-WRONG-REASON`）。
2. **核心资料无法提交 —— 产品没有上传能力**，被要求手打「资料引用」（`DOC-REF-NO-UPLOAD`）。
3. **整个注册/入驻链路复用 420px 登录卡**，10~12 字段 + 3 份条款挤在一条竖条里（`UI-WIDTH-01`）。
4. **状态与错误对用户不可读**：`CONTRACT_PENDING` 死路只显示原始枚举，错误码原样暴露，无找回密码（`DEAD-END-RAW-ENUM` + `RAW-ERROR-CODES` + `NO-PASSWORD-RECOVERY`）。
5. **同意对象是内部草稿条款**，且页面文案、后端策略、条款正文三方互斥（`TERMS-DRAFT-EXPOSED` + `M-4`）。

### 3. 是「局部补几刀」就够，还是需要对 Supplier onboarding UI 做一次集中重构？

**需要一次集中重构 —— 但要分开看两件事：**

- **环境侧**（第 1 条）：是**配置 readiness**，不是产品缺陷。补一刀即可解除「今天不能注册」。
- **产品侧**：**不是补几刀能解决的**。原因是缺陷集中在**同一条链路、同一套结构**上：
  - 5 个页面共享一个错误的布局基座（`.login-card`）；
  - 6 个状态共享一个没有穷举的渲染函数（`supplierOnboardingView`）；
  - 2 个映射表共享同一个「兜底原样输出」的错误处理；
  - 1 个布尔字段承载 2 个语义；
  - 1 个不存在的上传能力被 4 个必填字段依赖。

  这些都是**结构性**的，逐条打补丁会得到「5 个各自变宽但依然不统一的页面」+「新增状态继续变成死路」。**建议把 Supplier 入驻链路（注册 → 主体认证 → 审核 → 合同 → 开通）当成一个独立产品面，做一次集中重构**：统一的宽屏表单布局、显式状态机 UI（含 stepper 与兜底）、文件上传能力、全量错误文案表。后台 shell（`CONSOLE-*`）**不在重构范围内** —— 那一层已经是一个像样的产品，移动端 IA 也做对了。

---

## 附录 A：本地产物与可删除性

| 路径 | 内容 |
|---|---|
| *(local ephemeral detached worktree at PR376 head; not archived, reproducible via `git worktree add`)* | PR376 detached worktree（`git worktree remove` 即可） |
| `.../shots/` | 现场 4 视口截图（含 fullPage） |
| `.../shots-fixture/` | 全部入驻状态 + 后台截图 |
| `.../audit-browser.mjs` / `audit-browser-results.json` | 现场只读浏览器审计与其结果 |
| `.../fixture-render.mjs` / `fixture-results.json` | 本地状态还原夹具与其结果 |
| `.../probe.mjs` / `probe-results.json` | 字段/键盘/技术面板补充探针 |
| `.../live-terms.json` / `live-assets/` / `live-index.html` | 现场只读抓取 |
| `playwright-core`（local isolated node workspace；非仓库路径） | 浏览器驱动（隔离工作区） |

## 附录 B：未执行的 mutation（明确声明）

- ❌ 未修改任何 GitHub PR / branch / commit / merge
- ❌ 未 push、未 commit
- ❌ 未部署、未修改 HK-STAGING、未修改 Production
- ❌ 未修改数据库、未创建任何供应商账号
- ❌ 未执行任何管理员审批（profile-decision / contract-decision 均为 `admin_principal` 保护，未调用）
- ❌ 未调用 `/v1/registration/challenges`（会写 challenge 行并发信）
- ✅ 唯一的 POST 是 `POST /bff/auth/supplier/register` 带**空 body**，被 Pydantic 在进入 handler 前以 `422` 拒绝，**未产生任何数据**
- ✅ 全部现场交互均为匿名只读 GET

因此**不需要回滚**。
