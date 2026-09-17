# 指挥中心部署计划合同（v2：计划由指挥中心派生）

> **2026-09-17 修订。** 本版把「计划由操作人员登记」改为「计划由指挥中心在收到合法 DEPLOY Request 时自动派生」。
> 上一版与 `docs/project/CC_V1_SCOPE_20260916.md` 冲突：该范围契约把「**Eason 中转**」与「**手工维护 deployment plan**」
> 明列为老板**不得**需要的步骤，并写明「以上任何一项，只要成为完成部署的必要步骤，**就是 V1 未达标**」；
> 冲突时以范围契约为准。同时按 `#103` Authority Boundary（*CC validates deployability, not product desirability*）
> 撤掉了计划里的四项产品发布声明。

本合同规定的是服务端**派生格式**与校验口径，不改变香港正式 Task 的 schema。
**没有任何人写计划**：聊天请求只能携带动作与环境，指挥中心从它自己已经持有的事实里派生出计划、校验它、登记它。

固定目录 `/etc/go-command-center/deployment-plans-v1` 为 root:root、0700。文件由指挥中心以 root:root、0600 原子写入；
不允许符号链接或组/其他用户写入。完整 bundle 不超过 128 KiB。

## 输入：DEPLOY Request 只有五个公共字段

```json
{
  "schema_version": "1",
  "request_id": "boss-deploy-request-EXAMPLE",
  "action_id": "HK_STAGING_DEPLOY",
  "environment": "HK-STAGING-01",
  "requested_at": "2026-09-17T00:00:00Z"
}
```

没有 `plan_id`。计划名由事实决定（见下），一个仍带 `plan_id` 的 Request 按**字段集合不等**拒绝（`schema_fields`），
而不是被当作「多了一个可忽略的字段」读过去。请求最多 4 KiB、有效 15 分钟；未知字段、重复 JSON 键、路径穿越、
Production、关闭/Draft/跨仓库 PR、变化的 PR HEAD 均拒绝。

## 信任材料

- `authority.pub`：既有指挥中心任务签名公钥的受控副本，必须与香港现有受信任务公钥核对指纹。
- `hk-evidence.pub`：既有香港回执签名公钥的受控副本，必须由运行档案和技术审核人员确认指纹。
- **不使用任何独立的审批签名公钥。** V1 的人工审批权威 = **经 GitHub 认证的身份** + 明确的审批意图 + 候选绑定 + 环境绑定
  （见 `docs/project/CC_V1_SCOPE_20260916.md`）。GitHub 决定谁写了 Request PR，指挥中心只读取平台给出的答案，
  并只接受下方列出的授权身份；其他人写的 Request PR 在到达计划之前就被拒（`request_pr_author_not_authorised`）。
  此前的 `approval-authority.pub` 与独立审批签名者已被该范围重置取消。
- 不创建新信任根，不轮换原有私钥，不从请求 PR 读取公钥。测试生成的临时密钥和样本不得登记到生产目录。

## 派生的输入从哪来

| 输入 | 生产者 | 怎么被绑定 |
|---|---|---|
| `candidate`（六字段） | `docs/canonical-baseline/CURRENT_CANDIDATE.json` 的 `release_candidate_v1` 块（由 candidate admission 从签名的 TEST_PR 写出） | 与签名的 TEST_PR 回执逐字段核对 |
| `expected_current_image_id` | 同一块的 `rollback_relation.previous_known_good_image_id`，与 root-only 的 VERIFY 基线 `image_id` **必须相等** | 新鲜 VERIFY 回执再证一次 |
| TEST_PR 一对 | 指挥中心自己签发的 TEST_PR Task ＋ 香港 agent 签名的回执 | 证据仓按 `<task_id>-<nonce>.json` 精确取回 |
| CANARY 一对 | 同上 | 最新一次且只认最新一次 |
| 预检 VERIFY 一对 | 同上 | 新鲜度 ≤ 5 分钟 |
| 审批 | **DEPLOY Request PR 本身** | 见下 |
| 计划名 | `hkstg-<source_commit 前 12 位>-<image 前 12 位>-<canary release_id 的 sha256 前 12 位>` | 校验器重算 |

任何一项不可读、缺失、过旧、或彼此不一致，派发**当场拒绝**（是拒绝，不是异常——轮询 tick 不会因此死掉）。

## bundle 的八个精确字段

`plan`、`approval`、`test_pr_task`、`test_pr_evidence`、`canary_task`、`canary_evidence`、`preflight_task`、`preflight_evidence`。
四个 Task/回执对象保留其原始签名字段。Hash 统一为对完整 JSON 对象（包含其 signature 字段）进行 canonical JSON 后
计算 SHA256：UTF-8、键排序、无缩进、分隔符逗号/冒号、ensure_ascii=false、不允许 NaN/Infinity。

### plan

| 字段 | 精确约束 |
|---|---|
| schema_version | 字符串 `1` |
| plan_id | 3–80 个字母/数字/点/下划线/连字符；首字符字母或数字；**必须等于上面那个派生函数的值**，且匹配文件名 |
| environment / action_id | `HK-STAGING-01` / `HK_STAGING_DEPLOY` |
| candidate.repository | `yuguangzhi3836-glitch/GO` |
| candidate.source_commit / application_git_tree | 完整 40 位小写十六进制 Git SHA |
| candidate.source_tree_sha256 | 完整 64 位小写十六进制 SHA256 |
| candidate.package_sha256 | 封存包的**内容地址** |
| candidate.image_id | `sha256:` + 64 位十六进制 |
| expected_current_image_id | 由新鲜香港 VERIFY 回执绑定的当前镜像 |
| target_services | 顺序固定为 api、recovery-worker、outbox-worker、mobile-push-receipt-worker、reconciliation-worker、mobile-push-worker、mobile-engagement-worker、judgment-worker |
| protected_non_targets | 按顺序 `redis`, `caddy` |
| migration / production / automatic_rollback | 均为布尔 false |
| test_pr_task_sha256 / test_pr_evidence_sha256 / canary_task_sha256 / canary_evidence_sha256 / preflight_task_sha256 / preflight_evidence_sha256 | 各自完整已签名对象的 canonical SHA256 |

**候选的两个身份：** `candidate.image_id` 是构建产物身份（Docker config ID），`candidate.package_sha256` 是交付身份
（封存包内容地址）。本入口**不要求也不接受 repo digest**：registry manifest digest 只在推送之后才存在，且一般不等于
image config ID；由 TEST_PR 在本机构建、且从未推送的候选根本没有 digest。执行器按 `package_sha256` 从固定 store 解析并
载入同一个镜像，载入后校验 `.Id == candidate.image_id`。

### 四项产品发布声明为什么不在计划里

上一版要求 `gates` 精确四键（`three_end_ux`、`six_vertical_closed_loop`、`sealed_node`、`final_release`）全部为
`PASS`。按本文件顶部的权威顺序，这一条被移除，理由是它**不是可部署性事实**：

- **`three_end_ux`、`six_vertical_closed_loop`** 是产品验收结论（三端体验、六纵向业务闭环），属上游；
  `#103` Authority Boundary 明写 CC 不重新评判产品方向与业务选择，且本仓没有任何进程能产出它们（在 journey 套件里
  它们的最好结果是带限定词的 `ISOLATED_WEB_SCOPED_PASS` / `ISOLATED_WEB_SIMULATOR_PASS`，且从未对本候选跑过）。
- **`final_release`** 是发布级结论。要求「必须先最终发布，才允许进入**测试**环境」，是把顺序倒过来了。
- **`sealed_node`** 是唯一一个名字代表真实技术事实的：部署将加载的产物就是这份源码封存出来的。它**不是被删掉，
  而是被事实替换**——改成校验**本候选的签名 TEST_PR**（`test_pr_proof`），它直接证明：Task 是为这个候选仓库的
  某个具名 PR 构建的，回执报告了构建自哪个 commit、产出了哪个不可变产物、封进了哪个封存包、以及封存已 proven。
  与 CANARY / VERIFY 不同，它**不设时效**：候选是不可变的，它的绑定是内容绑定，重跑是多余的而不是必需的。

### approval

精确字段：`schema_version`（字符串 1）、`approval_id`（`approval-` + `request_sha256` 前 16 位）、`approved_by`、
`approved_at`、`expires_at`、`scope`（`HK_STAGING_DEPLOY_FIXED_EIGHT`）、`plan_sha256`、`request_sha256`。

**approval 不做密码学签名，也不由任何人书写——它是那份 Request 自己。** `approved_by` 必须**等于**指挥中心从 Request PR
读到的作者登录名（不等即拒 `approval_identity_mismatch`），该登录名必须在授权名单内（否则 `approval_identity_not_authorised`）；
`approved_at` 取 GitHub 报告的 PR `created_at`（平台事实，不是审批人写的时间戳），`expires_at` 为 `approved_at + 15 分钟`；
`request_sha256` 是这份 Request 的 canonical 摘要，`approval_id` 由它派生，因此审批**只能**属于那一份内容，
事后改动 Request 内容即失效。**授权身份**（`go_deploy_request.APPROVAL_IDENTITIES`）：`yuguangzhi3836-glitch`、`chenzhenxi1-sudo`。
审批最多 15 分钟，必须晚于两份回执的完成时间，校验时剩余超过 60 秒。

### TEST_PR / CANARY 与只读核验

Task 的签名沿用 Ed25519/hex，回执沿用 Ed25519/base64。验证 action、environment、task_id、nonce、候选/当前镜像、
成功结果、各项门禁以及 `issued ≤ started ≤ completed ≤ expires`。

- **TEST_PR**：Task 的 `parameters` 精确为 `builder_profile` + `source{repository,pr_number,commit_sha}`；回执为
  `TEST_PR_OK`、`status=SUCCESS`、`artifact_durability=PROVEN`、`artifact_package.schema=go.sealed-artifact.v1`、
  `deployment_performed=false`、四项 gate（`offline_build`/`isolated_runtime_checks`/`source_commit`/`artifact_sealed`）
  全 PASS，且 `task_canonical_sha256` 等于该 Task 未签名内容的摘要。回执的 `source_commit_sha`、`artifact_digest`、
  `artifact_package.package_sha256` 必须与计划的 `candidate` 逐字段相等。
- **CANARY**：Task 的参数精确四项（`release_id`、`candidate_image_id`、`candidate_package_sha256`、
  `expected_current_image_id`），回执为 `CANARY_OK`、必要八项 gate PASS、完成距当前不超过 **30 分钟**。
- **预检 VERIFY**：Task 的两个 image 字段都必须等于 `expected_current_image_id`，回执为 `VERIFY_OK`、必要八项 gate PASS、
  完成距当前不超过 **5 分钟**。
- 存在未知失败结果即拒绝；原有 `application_*_proven=false` 等字段保持原义，不伪装应用验收 PASS。

### 新鲜度与内容绑定的区别

探测**当前状态**的（CANARY、预检 VERIFY）会过期——它们说的是"主机此刻是我们以为的那样"。
描述**不可变候选**的（TEST_PR、候选身份）不会过期——换了 commit、换了产物、换了包，无论时间戳多新都会被拒。
**最新一次 CANARY / VERIFY 说了算**：若最新一次是失败的，派发即拒绝，不会悄悄回退到更早的成功记录。

## 派生、登记与消费

1. 指挥中心收到合法 DEPLOY Request，读平台事实（作者、`created_at`、固定 HEAD）。
2. 从已有事实派生 plan 与 bundle；**先在内存里过一遍校验器**，因此永远不会写出一个通不过自己那关的计划。
3. 以原子替换 ＋ fsync 登记到固定目录的 `plan_id.json`；**已存在且字节不同则拒绝**（`registered_plan_differs_from_derivation`），
   不覆盖、不猜测、不停人工 review。
4. 从磁盘回读该文件并校验，然后才签发 Task。
5. 运行 `python /usr/local/libexec/go_deploy_request.py --check-plan <plan_id> --approval-identity <login> --request-sha256 <hex>`
   可只读复核一份**已派生**的计划；两个附加参数从 Bridge ledger 的对应记录取，不由计划自己提供。
6. **没有部署开关**。v4 配置里的 `deployment_authorization` 只声明授权模式，不授予权限；一次部署的授权就是
   那份合法 DEPLOY Request，由指挥中心按请求派生（`approval` 块），其 `approval_id` 是 Request canonical 摘要的
   派生值而非任何人的命名，有效期受审批寿命（≤15 分钟）与 Task deadline（≤5 分钟）双重约束，且**一次性**：
   计划文件登记后不覆盖，ledger 拒绝已记录过的计划或授权。**不存在常备授权**，因此也没有"窗口开着"这回事。
   `approved_by` 必须等于平台报告的 Request 作者且 ∈ 授权身份列表。
7. 计划和审批 ID 一旦在 ledger 留下 `prepared`/`publishing`/`published` 记录即视为已消费，即使最终发送失败也不可自动重用；
   `plan_id` 已经包含本次 CANARY 的 release 摘要，所以**重试需要一次新的 CANARY**（它同时给出新的计划名），
   而被消费过的计划名会被 `deployment_plan_already_consumed` 拒绝。中断后先核对同一 Task 的远端原始字节和香港执行状态，
   再由审核人决定是否需要全新计划/审批；禁止删除 ledger 来重试。

## 正式 Task 的参数

精确为 `release_id`、`candidate_image_id`、`candidate_package_sha256`、`expected_current_image_id`、`canary_evidence_id`、
`approval_id`。`release_id`、`task_id`、`nonce` 由指挥中心生成；签名、发布和回读仍使用原有通道。
