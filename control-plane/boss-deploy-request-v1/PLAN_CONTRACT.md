# 指挥中心已审批部署计划合同

本合同新增的是服务端登记格式，不改变香港正式 Task 的 schema。计划由技术审核/操作人员依据明确的部署授权登记；聊天请求只能引用 ID，不能上传或覆盖计划。**请求中的“部署”意图、源码修复授权和本候选的 CI PASS 都不能生成发布审批。**

固定目录 `/etc/go-command-center/deployment-plans-v1` 为 root:root、0700。文件为 root:root、0600（公钥可 0644）；不允许符号链接或组/其他用户写入。完整 bundle 不超过 128 KiB。

## 信任材料

- `authority.pub`：既有指挥中心任务签名公钥的受控副本，必须与香港现有受信任务公钥核对指纹。**只用于核验 CANARY / 只读核验的 Task 签名**。
- **不使用任何独立的审批签名公钥。**V1 的人工审批权威 = **经 GitHub 认证的身份** + 明确的审批意图 + 候选绑定 + 环境绑定（见 `docs/project/CC_V1_SCOPE_20260916.md`）。GitHub 决定谁写了 Request PR，指挥中心只读取平台给出的答案，并只接受本文件下方列出的授权身份；其他人写的 Request PR 在到达计划之前就被拒（`request_pr_author_not_authorised`）。此前的 `approval-authority.pub` 与独立审批签名者已被该范围重置取消。
- `hk-evidence.pub`：既有香港回执签名公钥的受控副本，必须由运行档案和技术审核人员确认指纹。
- 不创建新信任根，不轮换原有私钥，不从请求 PR 读取公钥。测试生成的临时密钥和样本不得登记到生产目录。

## bundle 的六个精确字段

`plan`、`approval`、`canary_task`、`canary_evidence`、`preflight_task`、`preflight_evidence`。四个 Task/回执对象保留其原始签名字段。Hash 统一为对完整 JSON 对象（包含其 signature 字段）进行 canonical JSON 后计算 SHA256：UTF-8、键排序、无缩进、分隔符逗号/冒号、ensure_ascii=false、不允许 NaN/Infinity。

### plan

| 字段 | 精确约束 |
|---|---|
| schema_version | 字符串 `1` |
| plan_id | 3–80 个字母/数字/点/下划线/连字符；首字符字母或数字；必须匹配文件名和 Request |
| environment / action_id | `HK-STAGING-01` / `HK_STAGING_DEPLOY` |
| candidate.repository | `yuguangzhi3836-glitch/GO` |
| candidate.source_commit / application_git_tree | 完整 40 位小写十六进制 Git SHA |
| candidate.source_tree_sha256 / package_sha256 | 完整 64 位小写十六进制 SHA256；审核人核实来源与打包/构建谱系 |
| candidate.image_id | `sha256:` + 64 位十六进制；审核人核实由上述源码和包构建 |
| candidate.repo_digest | 仓库名加 `@sha256:...`，受现有执行器限制，后缀须与 image_id 相同 |
| expected_current_image_id | 由新鲜香港 VERIFY 回执绑定的当前镜像 |
| target_services | 顺序固定为 api、recovery-worker、outbox-worker、mobile-push-receipt-worker、reconciliation-worker、mobile-push-worker、mobile-engagement-worker、judgment-worker |
| protected_non_targets | 按顺序 `redis`, `caddy` |
| migration / production / automatic_rollback | 均为布尔 false |
| gates | 精确四键：three_end_ux、six_vertical_closed_loop、sealed_node、final_release；全部字符串 PASS |
| canary_task_sha256 / canary_evidence_sha256 / preflight_task_sha256 / preflight_evidence_sha256 | 各自完整已签名对象的 canonical SHA256 |

镜像来源与 gate 结论是经过签名绑定的审核声明；入口并不从 Git 仓库或银行系统独立重做业务验收。技术审核必须核对原始源码、构建证明和验收材料，禁止将旧候选 PASS 转用于新候选。源码树 SHA256 的生成方法随原始构建证明归档，本入口将其视为固定指纹，不自行重新解释。

**已存在的执行器限制：** 一般 OCI image ID 与 manifest digest 不保证相等。本入口准确保留当前香港合同的相等约束；真实镜像不满足时必须拒绝，并另行修订和验收香港合同，不能编造 digest 或放宽本入口校验。

### approval

精确字段：`schema_version`（字符串 1）、`approval_id`（1–80 个字母/数字/下划线/连字符，首字符字母或数字）、`approved_by`（3–80 个安全标识字符，记录实际审核人员）、`approved_at`、`expires_at`、`scope`（`HK_STAGING_DEPLOY_FIXED_EIGHT`）、`plan_sha256`、`signature`。

**approval 不做密码学签名。**它的权威来自 GitHub 认证的身份：`approved_by` 必须**等于**指挥中心从 Request PR 读到的作者登录名（不等即拒 `approval_identity_mismatch`），该登录名必须在授权名单内（否则 `approval_identity_not_authorised`），其余绑定字段（`plan_sha256`、`scope`、审批时效）保持原义不变。**授权身份**（`go_deploy_request.APPROVAL_IDENTITIES`）：`yuguangzhi3836-glitch`、`chenzhenxi1-sudo`。审批最多 15 分钟，必须晚于两份回执的完成时间，校验时剩余超过 60 秒。只有受控操作流程持有签名能力，Bridge 不自动审批或签审批记录。

### CANARY 与只读核验

Task 的签名沿用 Ed25519/hex，回执沿用 Ed25519/base64。验证 action、environment、task_id、nonce、release_id、候选/当前镜像、成功结果、各项门禁以及 issued ≤ started ≤ completed ≤ expires。

CANARY Task 须与 candidate.image_id、candidate.repo_digest、expected_current_image_id 完全一致，回执为 CANARY_OK、必要八项 gate PASS、完成距当前不超过 30 分钟。VERIFY Task 两个 image 字段都必须等于 expected_current_image_id，回执为 VERIFY_OK、必要八项 gate PASS，完成距当前不超过 5 分钟。存在未知失败结果拒绝；原有 `application_*_proven=false` 等字段保持原义，不伪装应用验收 PASS。

`canary_evidence_id` 沿用当前执行器 ID 合同，填写已验 CANARY 的 release_id；完整 Task/回执身份和 SHA256 保存在被审批签名绑定的 bundle 及 Bridge ledger 中。香港执行器本身仍独立核验实时状态，不依赖这份快照替代现场 preflight。

## 登记与消费

操作人员核实完整材料后，将 bundle 原子写入固定目录对应 plan_id 文件；运行 `python /usr/local/libexec/go_deploy_request.py --check-plan <plan_id>` 只读检查。失败时修正材料并重新审批，不修改旧审批的签名内容。默认不开部署开关，不创建 Request PR。

准予本次具体版本部署后才开启 v4 开关并发布 Request。计划和审批 ID 一旦在 ledger 留下 prepared/publishing/published 记录即视为已消费，即使最终发送失败也不可自动重用。中断后先核对同一 Task 的远端原始字节和香港执行状态，再由审核人决定是否需要全新计划/审批；禁止删除 ledger 来重试。

正式 Task 的 parameters 精确为 release_id、candidate_image_id、candidate_repo_digest、expected_current_image_id、canary_evidence_id、approval_id。release_id、task_id、nonce 由指挥中心生成；签名、发布和回读仍使用原有通道。
