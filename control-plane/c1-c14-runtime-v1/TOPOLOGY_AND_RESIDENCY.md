# C1–C14 独立拓扑与常驻运行方案

状态：提案完成，PROPOSED_HOLD；不安装、不启动现网、不合并、不部署。
变更分类：TOPOLOGY、INFRASTRUCTURE、CONTROL_PLANE、PRODUCT_FIX、TEST_ONLY、DOCUMENTATION。

## 1. 基线与审核范围

本轮承接 PR #285 固定候选 `dfea65841f93b51b47d33254727f0c8df98f4c21`。
其 C14 run `36734851879`、C13 run `36735391752` 为 PASS_SCOPED，
源码候选整轮 ACCEPT；这些结论不转移到本轮新 SHA。本轮需重新 C14 → C13。
原 application tree `dd815baf0105cce603e9a28b002cfb9d8b95d186` 不变。

本轮独立于现有八服务业务拓扑，定义 `GO_C_RUNTIME_ISOLATED_SINGLETON/v1`。
它不是 HK_STAGING_BUSINESS_TOPOLOGY 的升级、不是部署请求、不是 Signed Task。
不修改现有 Command Center、Agent、Executor、业务 Compose、发布 allowlist 或现网指针。
新增服务角色仍属于 TOPOLOGY；隔离验证不能解除 TOPOLOGY_CHANGE_REQUIRED。

## 2. 第一阶段：可验证的单实例常驻候选

| 项目 | 固定约束 |
| --- | --- |
| 安置 | 将来经批准的独立隔离验证宿主；本轮不选择或接触现有 CC/HK 主机 |
| 服务 | 仅 go-c1-c14-runtime，一个实例；C1–C14 是逻辑责任域，不伪称14个在线 AI |
| 代码 | 审核后的固定源码包，只读 `/opt/go/c1-c14-runtime` |
| 状态 | 独立本地磁盘 `/var/lib/go-c-runtime`；SQLite WAL，禁止共享盘/NFS与跨主机复制运行 |
| 权限 | go-runtime 专用无特权用户；不传入密钥、API 凭据、SSH、Docker socket 或 authority 数据 |
| 网络 | 无监听端口、无外部访问；候选 systemd 单元使用 PrivateNetwork |
| 任务 | Noop 仅领取 RUNTIME_PROBE；审核及业务任务不领取，不生成正式审核意见 |
| 单实例 | 同一规范化 DB 路径的 flock；锁文件不删除，进程死亡自动释放 |
| 生命周期 | 5秒 tick；12 tick watchdog；SIGTERM/SIGINT 停止新一轮并退出；20秒后 systemd 可终止残留 |
| 资源预算 | 256 MiB 内存、50% 单核 CPU、32 Tasks；是验证限额，不是生产容量承诺 |
| 重启 | 失败重启、3秒间隔，60秒最多5次；停止/反复失败保持阻断并上报 |

`topology.v1.json` 是机器可读的冻结提案；`topology.py` 对服务、副本、任务类型、
存储、网络、凭据、环境和 HOLD 做严格白名单校验，任何扩展都拒绝。
CLI 默认拒绝启动，必须显式 `--isolated-validation`；该参数只声明验证模式，
不能代替宿主授权。代码不提供真实 Worker 的动态加载入口。

systemd 的 StateDirectory、权限、文件系统与网络隔离项以官方手册为依据：
https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml 。
本轮只做静态 verify，不宣称已在目标宿主验证 Linux namespace、资源限额或开机自启。

## 3. SQLite fencing 修复与兼容性

领取成功时 attempts 单调增加。完成和续租必须传递该次 ClaimedTask.attempts 为
expected_attempt；不得从最新任务行补取代次来使旧执行通过。事务获得写锁后再取时间，
同时要求 task、owner、RUNNING、worker、attempt 匹配且 lease_until 严格大于当前时间。
过期但尚未被回收的租约同样拒绝；同名 Worker 重启不绕过代次检查。

Supervisor 收到失租拒绝只记录 LEASE_LOST，不再次 complete，也不 escalate 新持有者任务。
完成状态与 TASK_COMPLETED Evidence 同事务提交，Evidence 写失败则状态回滚。
Evidence 按 SQLite 插入 rowid 排序，避免同时间戳/时钟回拨破坏链顺序。
旧库无表结构迁移；接口为有意的 fail-closed 不兼容变更，所有本目录调用已更新。
旧进程必须退出后才可启用新包，禁止混用版本。

这只保证本地状态变更 fencing，不提供任意外部 API 的 exactly-once。
SQLite 仍不是多机 HA 后端；系统墙钟异常需暂停验证并检查，不能把本轮时钟测试
解释为跨主机时钟一致性或防篡改时钟证明。

## 4. 监测与无人值守恢复

每次成功 tick 原子替换 `runtime.db.health.json`：run_id、PID、ticks、updated_at、
STARTING/RUNNING/STOPPED/FAILED。健康只代表调度进程，不代表14个外部模型在线。
建议外部只读监测每15秒检查：RUNNING且更新时间不超过30秒；文件缺失、停止、
未来时间异常或连续停滞应告警。监测器及通知渠道接入另行审查，本轮未发送通知。

进程 SIGKILL：健康文件可能留下旧 RUNNING，必须依赖更新时间判陈旧；重启重建
Runtime 并回收过期租约，未过期任务等待到期，不强制夺取有效租约。
DB busy/磁盘满/权限错误：进程失败退出，不伪造任务成功；受重启频率限制。
最大尝试耗尽进入升级队列；Evidence 不通过则不得作验收或继续正式交接。
空闲责任域不因 Runner 心跳自动宣称 BUSY/工作完成。

## 5. 备份、恢复、回退

授权安装前先固定候选 SHA、Runtime tree、拓扑 JSON SHA256、服务单元 SHA256、
审核 run/artifact/root 和源码 SHA256 清单。记录旧服务不存在或旧版本身份，不凭记忆覆盖。
SQLite 在线备份应使用 SQLite backup API；不要只复制运行中的 .db 而遗漏 WAL。
恢复前停止服务，备份原 DB/WAL/SHM，校验数据库 integrity_check 和 Evidence 链，
在隔离副本验证任务/长期状态与恢复语义后再申请受控恢复。

回退仅作用于这个独立服务：先停止领取、保留状态与证据，再切回兼容的固定代码包。
旧 dfea6584 没有完成/续租代次门禁，禁止在保留待处理任务时直接恢复旧执行器；
此时安全回退结果是 STOPPED/HOLD，由后续修复包接管。禁止删除任务库“恢复健康”。
不得以回退名义重启或修改任何业务服务、保护组件或 HK 控制面。

## 6. 第二阶段：真实24×7团队的后续接入合同

第一阶段只能证明服务生命周期；不能交付真实 AI 团队值守。
真实运行需新增独立审核范围：PostgreSQL 作为协调状态/队列/Evidence 的单一权威存储，
把已验收队列适配器接入完整 Runtime（当前尚未接入），禁止 SQLite 与 PG 双写双真相；
外部模型/代码 Worker 的任务预算、取消、续租、重试和幂等 effect；凭据隔离；
只读监测及升级渠道；跨 C 真实请求和正式 C14/C13 回传验证。

真实适配器须在调用外部动作前校验租约/权限，effect 接收端同时核验 fencing token
及幂等键。模型/API 超时与未知结果进入恢复/核对，不得依赖重试实现“恰好一次”。
多实例/扩容、外网、凭据或新增数据库依赖必须发布新拓扑版本及对应门禁，不能修改
第一阶段 v1 含义后继续引用旧验收。Google KMS/HSM 不是本探针服务依赖；现有权威
签发边界保持原状，本轮不作变更。

## 7. 启用顺序与未完成门禁

1. 本轮隔离回归、进程恢复和拓扑扩展拒绝测试；独立 Draft PR 留痕。
2. 冻结新 SHA 与文件摘要，对此新候选重新执行 C14 → C13。
3. 指挥中心核验独立拓扑审核、环境验证、候选绑定、资源/目录/账户/隔离条件；
   安装 preflight 新增四个拓扑事实，缺失或非严格 true 一律 TOPOLOGY_CHANGE_REQUIRED。
   这些输入只能由验证器导出，调用者布尔值或 PASS 字符串不是执行权威。
4. 人明确批准这个固定包在明确隔离宿主上的安装/首轮 E2E，使用届时已批准的控制面入口；
   本轮不发明 action_id、不生成 Signed Task、不扩展现有 DEPLOY 服务列表。
5. 授权首轮 E2E 验证隔离、启动/停止/重启、限额、断电恢复、备份恢复及安全停止；
   读回产物和状态证据后才能登记拓扑已证明。首次验证是单独授权通道，不走普通 DEPLOY。
6. 获得独立拓扑审批和正式证明后，才可能满足常驻安装的最终资格；安装 gate 本身
   永远 authorizes_any_action=false，不是安装器。

目前第4–6项未授权、未执行；第2–3项仍须新候选独立审查。安装 BLOCKED，
TOPOLOGY_CHANGE_REQUIRED/HOLD，Production/HK/真实支付/真实供应商均未触碰。
