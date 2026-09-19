# 注册与全国酒店建库：部署就绪核查

核查日期：2026-09-19。只读核查，未发起 Request、Signed Task、部署、合并、迁移或权限变更。

## 结论

用户已明确要求在条款正文与真实页面验收完成后部署。无须再次泛泛征求部署意愿；但前置验收尚不能跳过，且当前会话没有 PR227 对应的已签名 TEST_PR、候选准入、CANARY、VERIFY 与 DEPLOY 成功证据。缺少签名私钥不是本会话的障碍：该私钥本来只应由 Command Center 持有。

GitHub 连接实际可以访问私库 chenzhenxi1-sudo/go-control-tasks，返回 pull:true/push:true。它是可用的正式请求入口。不得以普通 GO 代码 PR、HTTP 200 或测试数量替代部署证据。

## 读取基线与版本差异

本次读取 GO main commit `dc34ee5cabed7c6e93507d178fdd3a62a426399e` 的根 AGENTS、application/AGENTS、HK-STAGING README、OPERATIONS_GUIDE、BOSS_GPT_REQUEST_GUIDE、DEPLOY_RUNBOOK、DEPLOY_BASELINE、DEPLOYMENT_TOPOLOGY_V1、TOPOLOGY_CHANGE_POLICY、CURRENT_ARCHITECTURE、CURRENT_HK_RUNTIME、访问身份 runbook、环境契约与候选准入契约。

根 AGENTS 残留 VERIFY-only 说明；专门的请求指南与 CURRENT_ARCHITECTURE 已明确 2026-09-17 支持五字段 CANARY/DEPLOY，DEPLOY Request 自身构成人类授权，不能再要求手写 plan 或开启部署开关。不得自建签名 Task。

旧 CURRENT_HK_RUNTIME 描述 9月13日 DEPTH48、数据库0133、旧镜像；控制仓库9月18日的记录已出现 executor `0.6.0-media-topology-v2`。因此文档里的 V1/旧镜像只作历史基线，执行前必须取得最新已验证状态，不能恢复旧 hash 或猜测 V2 当前已全面成功。

## 实际公开运行检查

域名来自 CURRENT_HK_RUNTIME.health_endpoint.public。无认证、只读 HTTPS GET：

| 地址 | 结果 |
| --- | --- |
| https://staging-api.goaidirect.com/health | 200，status=ok、service=go-hotel-platform |
| https://staging-api.goaidirect.com/go-app/ | 200，1718 bytes |
| https://staging-api.goaidirect.com/supplier-console/ | 200，654 bytes |
| https://staging-api.goaidirect.com/go-admin/ | 200，2152 bytes |

以上证明入口可达，不证明 PR227 已上线、注册可完成、全国模式已开启，亦不替代浏览器/手机验收。误探测的 /v1/supplier/registration-policy 返回404；它不是核实后的候选契约路由，不能据此判断全国功能状态。

## 已有控制记录

控制 Tasks 仓库 main tree `49456a7cf38e7a0c1da3f532d85d06d76f9ef125` 可读。Evidence 仓库默认分支是 `permission-test`（不是 main），读取 tree `015b053143199a42c99fc83a9e38178084f7436b`。

- 9月19日05:40:21Z CONTROL_PLANE_HEALTH 记录 status SUCCESS，显示任务/证据仓库连通；agent 0.5.8-migration-window。记录路径：`evidence/go-boss-health-20260919T053906Z-78fa86900302-fr3t-sAN1er28QlgE3d_RKqVBgKyWEcp.json`。
- 9月18日08:20:59Z HK_STAGING_VERIFY 记录 FAILED，EXECUTOR_NONZERO_EXIT，诊断 stdout 为 executor 0.6.0-media-topology-v2 / VERIFY_REJECTED。记录路径：`evidence/go-boss-request-verify-20260918T081920Z-9f7abae94f2c-Td5luo25Gu3HrJvmwAg8SjRbe5If3DX2.json`。
- 以上读取的是带签名的记录内容，尚未在本子任务完成密码学验签，不把状态声称为已独立验签。
- Tasks PR106/105/104 是历史 PR202 的 DEPLOY/VERIFY/CANARY；不得复用到 PR227，也不得因为标题写 DEPLOY 就宣称部署成功。

## 前置完成后的具体路径

1. 冻结注册条款和页面验收通过的精确候选 PR head；不能继续改 head 却复用旧 TEST_PR。
2. 在 chenzhenxi1-sudo/go-control-tasks 从 main 建新分支，仅新增一个 requests/<unique-id>.json，建立面向 main 的 Request PR，不合并。TEST_PR 只用 schema_version、request_id、action_id=HK_STAGING_TEST_PR、environment=HK-STAGING-01、pr_number、requested_at 六字段。不得加入 commit override、image、shell、签名或环境参数。
3. 等待正常 Bridge/Agent 链，核对精确候选 SHA 的 TEST_PR_OK、封装 artifact、构建身份与 Signed Evidence。TEST_PR 本身不部署、不证明应用健康。
4. 核实 Command Center 的候选准入记录与当前 canary authority 确实指向本次候选。五字段 CANARY/DEPLOY 无法指定 PR，不能在候选仍指向旧 PR52/202 时盲发。
5. 按序发送新的 CANARY → VERIFY → DEPLOY Request。后三者均只有 schema_version、request_id、action_id、environment、requested_at；CANARY 30分钟、VERIFY 5分钟内有效，DEPLOY 必须在两者完成后新建且15分钟内处理。计划由 CC 生成，Boss 不写 plan、不改 authority。
6. 每一步读取机器拒绝原因或成功证据；被拒绝就停，不猜字段、不改权限、不重放。DEPLOY 后单独新建 VERIFY，核实镜像/拓扑/数据库/保护对象，再用真实注册流程读回全国模式。

## 全国模式的验证要求

以候选代码的正式路由和配置契约为准：查询注册及覆盖范围的服务端状态、C端注册、B端全国不同省份酒店注册/自有信息库、跨酒店隔离与审核发布边界。公共建库全国开放并不等于允许未审核图片、未授权房型或真实支付库存自动上线。环境值不得被塞进五字段 Request；若模式需要环境配置，应走已有正式配置/候选契约，不能直接改 runtime.env。

目前缺失的是已批准的条款正文/可验证经营主体、候选真实页面验收，以及本候选正式封装和最新部署链证据。若这些前置未满足，保持未部署，继续完成可执行的代码和验收准备。

## 主任务新增实际验收事实

主 agent 已通过既有云浏览器合法打开 staging 两端：C端主页无候选新增注册 header，进入“我的→注册”仅见 checkbox 文本、未见条款链接；B端登录有“申请伙伴”。此处为主任务回传事实，独立 DOM 证据由主任务保存。未证明候选安装。

另外，已确认历史产品硬约束是手机或邮箱验证码的真实闭环。当前候选只有邮箱/密码，尚未实现真实验证码闭环。因此即便增加条款正文和阅读/同意 hash gate，注册全国开放仍须 HOLD；不能把未经验证账号当作完成注册验收，也不能将这项缺口误报为签名私钥不足。
