# DEPTH36R3 香港隔离验收交接单（仅准备，不部署）

日期：2026-09-10。指挥中心负责全部开发；香港仅负责明确授权范围内的运维。本单依据用户要求，将隔离验收准备从 DEPTH35R2 重新绑定 DEPTH36R3。它不是部署授权、签名任务，也不证明香港环境已经创建或连通。

旧 [DEPTH35R2 交接单](https://github.com/yuguangzhi3836-glitch/GO/blob/90fe749a926d77407c98dd6f7cba5df80340c207/docs/acceptance/DEPTH35R2_HK_SERVER_HANDOFF_20260910.md) 原样保留，仅对新候选的后续准备采用本单；禁止旧单配新包执行。

## 唯一软件与证据绑定

| 对象 | 精确值 |
|---|---|
| 仓库／候选分支 | `yuguangzhi3836-glitch/GO`／`deliverables/cp11-depth36r3-mobile-contract` |
| DEPTH36R3 候选提交 | `7bd98db21ee950aeb91c12b296b1864b5a758c3f` |
| 父候选 DEPTH36R2 | `32712e9629254fea87f50ff218bc76d5906e7cc2` |
| 父源码树 SHA256 | `a68f5f02e3f194d00d3e794bdafa08982be8c0ccb54d0a824c3008ffeb53f284` |
| 当前源码树 SHA256 | `c58edb0c0568c3f9fe80ba014c260513a07a8e74b211b608ade4d9052f8645b3` |
| 指纹文件数 | 1267 |
| CI 工具提交（不是源码候选） | `9725334a729f9ea43b6cb62c63bf52539511f312` |
| 已完成 CI | [34453179558](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34453179558)，2026-09-10 08:16:05 UTC／16:16:05 北京时间 |
| 已核验源码 ZIP | `GO_DEPTH36R3_SOURCE_20260910.zip` |
| 源码 ZIP SHA256 | `b4634f9da515a22f95fb740b979c2f77fdce29342eabbb9c54e5c666976f5b86` |
| 永久原始证据 | [同提交证据目录](../../deliverables/CP11_DEPTH36R3_INDEPENDENT_CI_20260910/README.md) |

固定源码指纹见 [候选原件](https://github.com/yuguangzhi3836-glitch/GO/blob/7bd98db21ee950aeb91c12b296b1864b5a758c3f/deliverables/CP11_DEPTH36R3_MOBILE_CONTRACT_20260910/SOURCE_FINGERPRINT.json)。不得使用 `latest` 或浮动分支代替上述指纹；不得把源码树哈希、Git 提交或源码 ZIP 哈希填成 Docker image digest。

## 本次已验证及未验证的边界

已验证：独立 CI 四分片完整收集 1679 项，1673 通过、6 项 PostgreSQL 专项因未配置测试数据库跳过、0 失败／错误；原始 JUnit 与执行清单覆盖无遗漏、无重复。每个分片另通过同一套 10 项离线包装检查，以及 148 项／87 次请求的隔离回环 HTTP 检查。CI 源码还原及测试后指纹一致；归档端又核对了五个完整 artifact ZIP 的 SHA256、40 份日志帧文件与 ZIP 原件一致、覆盖证明同字节一致、源码 ZIP 内 1267 文件指纹一致。

环境：一次性 GitHub Ubuntu 22.04 runner，Python 3.13.5，SQLite 合成数据。Node 22.22.0 仅用于后端测试的原生 API 桥接。回环 HTTP 使用真实本机进程和请求，但不是实际浏览器、设备或香港运行环境。

未验证：消费者／供应商／管理员登录后的真实桌面及移动视口旅程、原生设备、六品类完整用户闭环、真实 PostgreSQL 与队列、支付渠道、完整封存 Node 门禁、香港镜像／依赖与资源兼容性、服务器启动与回滚证据、正式控制链及签名回执。当前源码 ZIP 已验证离线完整性，不等于香港可运行镜像或已验收一键部署包。不能继承 DEPTH35R2 的 38／239 组件测试数作为 R3 新验收，也不能用历史浏览器能力快照当作当前能力实测。

## 责任分工

| 事项 | 负责人 | 本单状态 |
|---|---|---|
| 源码、支付、前端／原生端、业务、依赖与部署工具开发 | 指挥中心 | 唯一开发来源；香港不得补业务代码或另做支付实现 |
| 原始 CI 证据及源码完整性归档 | 指挥中心 | 本次已核验并与本交接单同提交归档 |
| 目标服务器现状、架构、资源、域名／证书和网络条件 | 香港 | 等待已授权只读预检回执 |
| 目标适配的完整运行包、依赖清单、启动／停止／健康检查／回滚方案 | 指挥中心 | 目标兼容性和运行／回滚证据待补，不能由源码 ZIP 代替 |
| 建立独立验收环境或更新运行版本 | 香港 | 本单不授权执行；需要明确环境、资源、候选和获批操作入口 |
| 三端真实浏览器及后续逐关验收 | 指挥中心 | 等待明确绑定的隔离环境与可用验收能力，HOLD |

## 香港只读预检回执所需字段

仅在既有已授权只读范围内收集现状。未知填写 UNKNOWN；未创建填写 NOT_CREATED；没有获批入口填写 NOT_CONFIGURED。禁止为填表安装软件、修改配置、启动容器、调整网络或调用真实订单／支付。不得提交密码、私钥、Token、完整环境文件或带凭据 URL。

| 字段 | 非秘密证据要求 |
|---|---|
| 证据身份 | UTC 时间、环境／节点标识、既有只读授权或任务引用、原始回执路径及 SHA256 |
| 目标候选 | 明确本单 R3 候选／源码树；与当前运行版本分开填写，未运行 R3 不可填成 R3 |
| 服务器与资源 | OS／版本、CPU 架构、既有 Docker／Compose 版本、可用 CPU／内存／磁盘条件 |
| 隔离边界 | 独立实例／容器项目、数据目录、数据库和网络的现有可用条件；是否与现网分离 |
| 访问条件 | 已有验收域名、证书状态、允许访问范围及端口；未分配写 NOT_CREATED |
| 当前运行事实 | 实际镜像 digest／进程版本及绑定证据；当前业务、RDS、Redis、反向代理的边界，不套用历史镜像值 |
| 获批运维入口 | 能否在明确授权下建立隔离环境的既有流程；没有则记 NOT_CONFIGURED，不套用现有固定 Staging 部署任务 |
| 控制证据 | 如已有相关签名任务／原始回执，提供 GO 已选来源中的文件引用、验签与候选／镜像／节点绑定记录；不得为补材料重跑部署或 VERIFY |

后续任何新环境准备需先具备明确资源／环境授权和指挥中心完成验证的目标运行包。仅批准只读回执不批准创建环境。本次未发送任务、联系香港、连接服务器或变更任何运行状态。

## 三端验收材料要求（准备规范，不是执行指令）

后续环境完成授权并提供实证后，须交付环境 ID、UTC 时间、固定包／镜像哈希、运行源码指纹、前端资产绑定、三端 HTTPS 入口、脱敏启动／健康日志及合成账户角色引用。入口对应 `/go-app/`、`/supplier-console/`、`/go-admin/`，Direct 页面为 `/go-app/direct.html`；当前未提供可直接验收的服务器地址。

指挥中心逐角色检查真实登录、会话／退出、权限隔离及登录后旅程，并保留实际浏览器、桌面／移动视口参数及原始证据。移动视口能力需要实测，不能用桌面页面可见代替；原生设备验收另记。合成库存／价格／支付数据需明确标记，禁止生产扣款及真实预订。酒店官方房型／内容事实仍须有已选来源中的官方核验依据。

## 冻结与控制通道边界

本次已读取当前 main `cf378e692e502d9ea663ef1c02cd66fb7a98c4da` 上的香港 [README](https://github.com/yuguangzhi3836-glitch/GO/blob/cf378e692e502d9ea663ef1c02cd66fb7a98c4da/docs/control-plane/hk-staging/README.md)、[Runbook](https://github.com/yuguangzhi3836-glitch/GO/blob/cf378e692e502d9ea663ef1c02cd66fb7a98c4da/docs/control-plane/hk-staging/HK_STAGING_DEPLOY_RUNBOOK.md)、[Baseline](https://github.com/yuguangzhi3836-glitch/GO/blob/cf378e692e502d9ea663ef1c02cd66fb7a98c4da/docs/control-plane/hk-staging/HK_STAGING_DEPLOY_BASELINE.md) 及操作合同。这些文档描述流程，不构成新部署或已连通证明。

既有 `HK_STAGING_DEPLOY` 固定针对 `HK-STAGING-01` 八服务和固定运行配置，不能更改环境名、服务集合或配置路径来创建新隔离环境；不得绕过正式 Agent／Executor。即使同镜像强制重建也属于运行变更。不得越过人类授权、CANARY、只读漂移检查、全新签名任务、持久化 previous-state、执行回执和后续正式 VERIFY。不同镜像的正式端到端路径尚不能用旧同镜像 PASS 代替。禁止 migration、自动回滚及 Production 变更；本次不触碰 RDS、Redis、Caddy 或锁定 Worker。

## 当前状态与唯一下一允许动作

`CI_RAW_EVIDENCE_ARCHIVED=YES`、`OFFLINE_SOURCE_BUNDLE_INTEGRITY=PASS`、`SERVER_PREFLIGHT=AWAITING_HK`、`HK_RUNTIME_PACKAGE_COMPATIBILITY=NOT_YET_VALIDATED`、`HK_RUNTIME_BINDING=UNKNOWN`、`DEPLOYMENT_EXECUTED_BY_THIS_TASK=NO`。

四级链：`THREE_END_REAL_UX_LOGIN=HOLD` → `SIX_VERTICAL_REAL_E2E=HOLD` → `SEALED_NODE_GATE=HOLD` → `FINAL_RELEASE=HOLD`。

唯一下一允许动作：由香港按本单补齐已授权只读范围内的服务器预检回执。无秘密，未知如实标记，不为填写回执修改配置、建立环境或启动服务。门禁未通过，不下达部署指令。
