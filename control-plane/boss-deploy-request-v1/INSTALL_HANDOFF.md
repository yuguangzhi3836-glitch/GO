# 2026-10-01 候选衔接修复交接（未安装）

本修订基于 GO main `e663460e006f1267173b2e63016d85bee2cc7463`，持久 CANARY 通道改为使用与 DEPLOY 相同的候选登记和签名构建回执。此段优先于以下历史交接中关于独立 CANARY 权威配置的说明。保留原签名、公钥、Request 字段、ledger、服务范围和验收门禁。

安装须以当前运行 Bridge 文件的只读 SHA256 与来源核对为起点，保留当前运行版差异；本会话没有指挥中心主机的执行通道，未执行安装、重启或应用部署。审核后按既有安装机制同步 Bridge 与 plan_derivation.py，核对 SHA256SUMS，恢复原轮询。配置格式不变，禁止清空 ledger。

源码修复通过后仍须发布已验收的 CURRENT_CANDIDATE：source PR、源码树指纹、镜像、封存包、签名 TEST_PR、回滚基线和迁移声明必须真实一致。PR #298 的 TEST_PR 已成功，但业务容量 CI 未通过；不得将“构建成功”写成“业务验收通过”。安装完成后按 CANARY → 新鲜 VERIFY → DEPLOY → 部署后 VERIFY 验证，并保存 Task/nonce/签名 Evidence 与运行 hash。未取得这些回执前不得宣称上线完成。

---

# 安装交接（未执行）

本文件供 Eason/授权指挥中心操作人员审核。用户本轮授权补齐源码入口；本轮没有安装入口、启用部署开关、发送 Request/Task、合并 PR 或改变香港/Production。

## 安装前的具体核对

1. 取得本 Draft PR 的固定源码提交、通过的隔离 CI Run、ZIP 和 binding.json；核对 ZIP SHA256 以及解包后 `sha256sum -c SHA256SUMS`。校验清单覆盖交付文件，不递归包含自身；它不替代发布人的身份审查。
2. 只读记录当前指挥中心 Bridge、配置、单元、timer 和 ledger 的路径、权限、SHA256。候选基于 PROVENANCE.json 中的 Bridge 1.3 源码，其运行安装情况未在本轮核验。**若当前 Bridge 的 hash 不等于已知 1.2/1.3 来源，不得直接覆盖；先由技术审核合入运行版本的差异。** 即使匹配也须检查差异，保留既有 TEST_PR、签名和重放状态。不得用应用旧 ZIP 或恢复工具覆盖此控制候选。
3. 核实 root 运行的现有 Bridge 服务能导入 cryptography、访问当前签名密钥及 Tasks writer，不输出私钥或 token。保留现有服务权限、SSH host 校验、签名根、任务/证据仓库和 ledger；本候选不新增香港安装项。
4. 为 PR 状态检查在 `/etc/go-command-center/keys/github-requests-reader.token` 登记已有或经批准提供的只读 GitHub 凭据。至少能够只读目标 Tasks 仓库的 Pull requests 元数据。Bridge 对固定 API 路径发 GET，拒绝重定向，不把凭据放入 Request、日志、argv 或仓库。**此凭据和 API 可达性尚未在本轮现场确认；缺失时 DEPLOY 拒绝。** 不修改仓库权限、不自动申请更大权限；原有 VERIFY/TEST_PR 不需要此新读取步骤。
5. 按 PLAN_CONTRACT.md 核对并登记两份既有公钥的指纹，创建受保护的计划目录。实际部署包尚未满足四级门禁时不得登记 PASS 审批或创建可消费的计划。

## 经授权后的安装清单

| 候选文件 | 指挥中心位置 | 所有者/模式 |
|---|---|---|
| go-boss-request-bridge | /usr/local/libexec/go-boss-request-bridge | root:root 0755 |
| go_deploy_request.py | /usr/local/libexec/go_deploy_request.py | root:root 0644 |
| config.json | /etc/go-command-center/boss-request-bridge-v1.json | root:root 0600 |

模块须与 Bridge 同目录。安装时由操作人员暂停既有轮询、确认没有正在处理的任务，备份原始文件与 ledger 后原子替换。v4 模板只声明 `deployment_authorization`（本修订只实现 `request`），它不授予任何部署权限；注意新的配置字段集与旧配置不兼容，**旧配置会被整体拒绝（fail-closed）**，所以本修订按 3 文件成套安装：Bridge、`go_deploy_request.py`、`plan_derivation.py` 与 `config.json`。核对当前 VERIFY/TEST_PR/CANARY 配置和依赖均已存在后再恢复既有 timer。不得删除重放记录，也不修改香港 Agent/执行器、Compose、数据库或服务拓扑。

若需要撤回安装，暂停轮询并保留新旧 ledger 全量记录，恢复原先经过核实的 Bridge/配置，再由操作人员决定恢复轮询。此处仅是入口文件恢复，不是应用自动回滚。

## 启用与真实验收

安装完成不等于可部署，也不再需要任何人"打开部署开关"——没有这个开关了。一次部署的授权就是那份由授权身份开的合法 DEPLOY Request：指挥中心在同一个 tick 内读平台事实、派生并登记计划、过既有校验器、签发 DEPLOY Task。因此正确的顺序是**先跑 CANARY（≤30 分钟）→ 再跑预检 VERIFY（≤5 分钟）→ 再由授权身份提交唯一 DEPLOY Request**，而不是提前登记计划或提前开任何开关。命令行为只读复核：`--check-plan <plan_id> --approval-identity <login> --request-sha256 <hex>`。

验收分别记录：

1. Request PR URL / HEAD / request_id / plan_id / plan SHA256 / bundle SHA256 / 审批 ID / 版本与包指纹。
2. 指挥中心实际安装 hash、Task ID、nonce、正式 Task 提交及原始签名字节。
3. 香港对应 Task/nonce 的签名 SUCCESS/DEPLOY_OK 回执和 DEPLOY_RECORD_V2 的 ID/SHA256。
4. 部署后另一份新鲜只读 VERIFY 的签名成功回执、固定八服务运行镜像和受保护非目标状态。

源码 CI 只证明请求入口和归档适配器的隔离兼容。香港真实异镜像部署、完成后的 VERIFY、银行资金或业务最终状态并未在本轮验收。Task 已发布只代表请求被受理，不应向 Boss 显示“部署完成”。把 `deployment_authorization` 置为 `request` 以外的值是应急停止：它只阻止尚未发布的新部署，不能撤销已经进入 Tasks 仓库的签名任务；已发布任务必须按原有运维程序处理。

