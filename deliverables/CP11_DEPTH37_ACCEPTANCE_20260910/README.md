# DEPTH37R2 部署前验收记录

当前源码候选：`da6897706793fafd73d09cb56013586089733f4d`；源码指纹：`cf3f13960effa346337ed549cfb58ed6bae7aec94d05aba2e3b2f00d0b9df84c`；共 1276 个文件。

本次修复 Expo 原生模块缺失造成的白屏。四个既有版本的 Expo 运行时模块已改为应用直接依赖，锁文件由隔离 npm 生成；移除了随工作目录变化而失效的自定义搜索路径。验收同时检查应用目录和生成的原生目录，启动验证保存实际界面与错误日志。

| 验收项 | 状态 |
| --- | --- |
| Node 密封、离线还原、防篡改 | PASS |
| 前端回归（244 项） | PASS |
| 供应商适配合约（27 项）与输入校验（5 项） | PASS |
| Android Release x86_64 构建 | PASS |
| iOS 模拟器构建与登录页启动 | PASS |
| Android 模拟器登录页启动 | PASS |
| Android / iOS 真机 | NOT_RUN_MISSING_DEVICE_ENVIRONMENT |
| 供应商真实认证 | NOT_RUN_MISSING_SANDBOX_INPUTS |
| 消费者、供应商、管理员真实浏览器操作 | DEFERRED_POST_DEPLOYMENT |
| 六品类真实操作闭环 | DEFERRED_POST_DEPLOYMENT |
| 真实 PostgreSQL 集成 | PASS |
| 正式放行 | HOLD |

父版本完整验收为 1,673 项通过、6 项 PostgreSQL 测试跳过、0 项失败；本次保留该历史结果，并另用一次性 PostgreSQL 实例补验这六项，独立结果见上表；没有重复执行完整后端测试。本次新增范围的结果见 STATUS.json 和原始命令记录。

Android 产物为 CI 内部签名的 x86_64 Release APK；iOS 产物用于模拟器。模拟器启动通过不代表真机权限、深链、通知和部署后网络会话均已验收，也不代表应用商店发布包可用。

供应商输入校验只证明防止缺参或不合规输入进入现有认证流程；真实认证仍须供应商认可的沙箱账号、测试库存和外部回执。所需输入及关闭条件见 REMAINING_EXTERNAL_INPUTS.md。

三角色真实浏览器操作与六品类真实闭环，按用户决定放在部署后验证；未将它们标为通过。香港负责已批准产物的服务器部署，开发和修复由 GO Command Center 负责。本记录未执行合并、部署或真实交易。

构建运行：https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34476573746

Android 启动运行：https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34478592286

ACCEPTANCE_RUNS.json 保留全部已采集尝试，包括原始白屏、检查器输出格式错误、陈旧 PR 基线拒绝以及原生目录链接失败。原始日志位于 RAW_EVIDENCE.tar.gz，逐文件指纹见 RAW_EVIDENCE_INVENTORY.json。历史“构建成功”不能覆盖实际启动失败。
