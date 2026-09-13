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

模块须与 Bridge 同目录。安装时由操作人员暂停既有轮询、确认没有正在处理的任务，备份原始文件与 ledger 后原子替换。v4 模板部署开关保持 false；核对当前 VERIFY/TEST_PR 配置和依赖均已存在后再恢复既有 timer。不得删除重放记录，也不修改香港 Agent/执行器、Compose、数据库或服务拓扑。

若需要撤回安装，暂停轮询并保留新旧 ledger 全量记录，恢复原先经过核实的 Bridge/配置，再由操作人员决定恢复轮询。此处仅是入口文件恢复，不是应用自动回滚。

## 启用与真实验收

安装完成不等于可部署。取得具体版本的部署授权和全部发布门禁 PASS 后，先使用真实 CANARY 与近期 VERIFY 回执登记短期签名计划，执行只读 `--check-plan`，再由授权操作人员将 `deployment_requests_enabled` 置为 true，并在允许窗口提交唯一 Request PR。

验收分别记录：

1. Request PR URL / HEAD / request_id / plan_id / plan SHA256 / bundle SHA256 / 审批 ID / 版本与包指纹。
2. 指挥中心实际安装 hash、Task ID、nonce、正式 Task 提交及原始签名字节。
3. 香港对应 Task/nonce 的签名 SUCCESS/DEPLOY_OK 回执和 DEPLOY_RECORD_V2 的 ID/SHA256。
4. 部署后另一份新鲜只读 VERIFY 的签名成功回执、固定八服务运行镜像和受保护非目标状态。

源码 CI 只证明请求入口和归档适配器的隔离兼容。香港真实异镜像部署、完成后的 VERIFY、银行资金或业务最终状态并未在本轮验收。Task 已发布只代表请求被受理，不应向 Boss 显示“部署完成”。关闭开关只阻止尚未发布的新部署，不能撤销已经进入 Tasks 仓库的签名任务；已发布任务必须按原有运维程序处理。
