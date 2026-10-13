# GO 代码结构说明

## 1. 仓库总览

仓库同时保存业务产品源码、AI 开发审核组件、部署定义和历史交付材料。本次快照中，Git 跟踪文件共 6,164 个。

```text
GO/
├── README.md                     人类当前入口
├── AGENTS.md                     AI 当前操作规则
├── GO_REPOSITORY_INDEX.md        仓库索引材料
├── CODEBUDDY.md                  辅助说明材料
├── .github/workflows/           GitHub Actions 工作流
├── application/                 业务产品源码
├── control-plane/               控制组件与 Runtime 仓库侧源码
├── deploy/hk-staging/            当前业务运行定义
├── ci/                          CI 配套检查与脚本
├── packaging/                   打包、封存及归档工具
├── docs/                        治理规则、设计、审计及历史文档
├── command-center/              已退役的旧 Command Center
├── hk-staging/                  2026-09-11 历史运行时快照
├── deliverables/                历史交付包
└── evidence/                    历史证据材料
```

| 目录 | 跟踪文件数 | 主要用途 |
|---|---:|---|
| `deliverables/` | 2,520 | 历史交付包 |
| `application/` | 1,379 | 业务后端、前端、移动端及测试 |
| `evidence/` | 985 | 历史证据 |
| `hk-staging/` | 629 | 历史运行时快照 |
| `control-plane/` | 320 | 控制与自动执行组件 |
| `docs/` | 151 | 文档与治理材料 |
| `ci/` | 60 | CI 检查 |
| `command-center/` | 49 | 旧系统归档 |
| `.github/` | 35 | 工作流 |
| `packaging/` | 27 | 打包与归档 |
| `deploy/` | 3 | 当前部署定义 |

以上目录合计 6,158 个文件，另有 6 个根目录文件，共 6,164 个。

`control-plane/` 包含当前 Persistent Runtime 能力，不能整体归类为退役。根入口之外的 Markdown 属于历史材料，不自行定义当前操作路线；根规则明确依赖的治理约束仍然有效。

## 2. 业务产品：application/

```text
application/
├── src/go_hotel/                Python 业务后端
├── frontend/                   网页端
│   ├── consumer/               消费者端
│   ├── supplier/               供应商端
│   ├── admin/                  管理端
│   └── shared/                 前端共享代码
├── mobile/go-app/              React Native / Expo 移动端
├── alembic/                    数据库迁移
├── tests/                      后端测试
├── tests_frontend/              前端测试
├── ci/                         应用侧检查
├── gate_toolchain/             门禁工具
├── governance/                 治理相关材料
├── design/                     设计材料
├── specs/                      规格材料
├── docs/                       应用历史文档
├── staging/                    应用测试环境相关材料
├── script/                     辅助脚本
├── scripts/                    辅助脚本
├── pyproject.toml              Python 依赖和 pytest 配置
├── package.json                Vite 和前端测试配置
├── Dockerfile                  业务镜像构建
└── docker-compose.staging.yml  应用侧 Compose 文件
```

部署与运行操作依据根 `AGENTS.md` 的当前路径，不能仅凭某个 Compose 文件或旧说明决定执行方式。

### 2.1 Python 后端

后端目录沿用 `go_hotel` 名称，内部已包含多个旅行业务域。

```text
application/src/go_hotel/
├── main.py                     后端入口
├── api/                        API 接口
├── domain/                     领域模型
├── services/                   业务服务与共享服务
├── core/                       核心基础代码
├── db/                         数据库相关代码
├── repositories/               数据访问
├── connectors/                 外部系统连接
├── flight/                     航班业务
├── rail/                       铁路业务
├── mobility/                   地面交通业务
├── attractions/                景点与门票业务
├── journey/                    统一行程
├── fare/                       价格及票规相关能力
├── payments/                   支付相关能力
├── compensation/               赔付相关能力
├── identity/                   身份相关能力
├── travel_intelligence/        旅行者智能
├── go_ai/                      AI 业务能力
├── judgment/                   判断与信任
├── truth/                      真实体验与事实相关能力
├── autonomy/                   自主执行相关能力
├── routing/                    路由相关能力
├── agent_gateway/              Agent 接口相关能力
├── security/                   安全
├── observability/              可观测性
├── queue/                      队列相关代码
├── workers/                    业务后台任务
├── incident/                   异常事件
├── recovery_adapters/          恢复适配器
├── consumer/                   消费者相关代码
├── mobile/                     移动端服务相关代码
├── control_plane/              应用内控制相关代码
├── workbench/                  Cell 与工作台相关定义
├── data/                       数据相关材料
└── merge/                      合并相关能力
```

后端依赖配置使用 Python 3.11 及以上，包含 FastAPI、Uvicorn、Pydantic、SQLAlchemy、Alembic、psycopg 和 Redis 等。依赖声明不代表这些组件已在远端运行。

### 2.2 网页 UI

消费者、供应商和管理端页面位于 `application/frontend/`，主要使用 HTML、JavaScript、CSS。

| 内容 | 位置 |
|---|---|
| 消费者网页 | `application/frontend/consumer/` |
| 供应商网页 | `application/frontend/supplier/` |
| 管理端网页 | `application/frontend/admin/` |
| 网页共享代码 | `application/frontend/shared/` |
| 前端开发及测试命令 | `application/package.json` |

网页 UI 与移动端 UI 各有源码目录，修改网页页面不代表移动端页面同步改变。

## 3. iOS / Android 移动端

移动端主体位于 `application/mobile/go-app/`，采用 React Native + Expo。业务逻辑与页面主要使用 TypeScript 和 TSX，iOS 与 Android 共用主体代码。

```text
application/mobile/go-app/
├── App.tsx                     程序入口、主导航及底部标签
├── app.json                    Expo 静态配置、平台标识
├── app.config.js               动态配置、API 地址及构建参数
├── eas.json                    EAS 构建配置
├── package.json                移动端依赖及启动、测试、构建命令
├── tsconfig.json               TypeScript 配置
├── src/
│   ├── screens/                各业务页面 UI
│   ├── components/             公共 UI 组件
│   ├── design.ts               颜色、字号、圆角和公共样式
│   ├── navigation/             导航与深链接相关代码
│   ├── api/                    后端接口调用与网络传输
│   ├── auth/                   登录和认证状态
│   ├── storage/                本地存储与安全会话
│   ├── notifications/          通知相关代码
│   └── domain/                 移动端领域相关代码
├── assets/                     本地图片和品牌素材
│   ├── brand/
│   │   ├── go-v14.png          GO 品牌图片
│   │   └── PROVENANCE.json     品牌素材来源记录
│   └── GO_HOME_BPLUS_MASTER_2026-08-19.png
├── native/apple/               Apple 原生 Swift 文件
├── qa/                         QA 材料
├── scripts/                    移动端辅助及契约检查脚本
└── store/                      发布检查及隐私数据映射材料
```

### 3.1 UI 修改位置

| 需要修改什么 | 主要文件或目录 |
|---|---|
| 首页布局 | `src/screens/HomeScreen.tsx` |
| 登录页面 | `src/screens/LoginScreen.tsx` |
| 酒店详情 | `src/screens/HotelDetailScreen.tsx` |
| 航班搜索 | `src/screens/FlightSearchScreen.tsx` |
| 铁路搜索 | `src/screens/RailSearchScreen.tsx` |
| 个人资料页面 | `src/screens/ProfileScreen.tsx` |
| 公共控件 | `src/components/UI.tsx`、`src/components/GO.tsx` |
| 品牌颜色、字号、圆角、公共样式 | `src/design.ts` |
| 底部标签、页面注册及主导航 | `App.tsx` |

页面结构和部分样式直接写在各 `.tsx` 文件中。公共样式从 `design.ts` 导入，页面也可能通过 `StyleSheet.create(...)` 定义专用样式。

### 3.2 图片与资源

- 本地品牌素材保存在 `assets/brand/`。
- `src/components/GO.tsx` 通过 `require('../../assets/brand/go-v14.png')` 加载品牌图片。
- 首页推荐酒店图片使用接口返回的 `image_url`，通过 React Native `Image` 的 `uri` 加载，因此业务图片并不全部保存在本地资源目录。
- `GO_HOME_BPLUS_MASTER_2026-08-19.png` 是目录中存在的设计资源文件；文件存在本身不证明当前页面使用它作为界面或背景。

### 3.3 iOS 原生代码与构建边界

当前目录包含两个 Swift 文件：

```text
native/apple/GOTravelTransactionIntents.swift
native/apple/GOTransactionLifecycleIntents.swift
```

本次读取的移动端根目录没有完整 `ios/` Xcode 工程。现有 Expo 配置声明 iOS Bundle ID 为 `travel.go.consumer`，项目同时提供 iOS 构建脚本。

仅凭这些源码和配置，不能确认 Swift 扩展已经接入构建，也不能确认 App 已完成签名、TestFlight 分发或 App Store 上架。

## 4. C01–C14 与执行体系

Cells 是业务责任域和审核责任域，不对应 14 个顶层代码目录，也不等于 14 个同时运行的独立代理。

| Cell | 责任域 | 代码阅读起点 |
|---|---|---|
| C01 | 酒店 | `services/`、`domain/`、`api/` |
| C02 | 航班 | `flight/`、`connectors/` |
| C03 | 铁路 | `rail/`、`connectors/` |
| C04 | 租车 | `mobility/` |
| C05 | 接送 | `mobility/` |
| C06 | 景点体验 | `attractions/` |
| C07 | 旅行者智能 | `identity/`、`travel_intelligence/` |
| C08 | AI 规划与执行 | `go_ai/` 等相关能力目录 |
| C09 | 判断与信任 | `judgment/`、`truth/` |
| C10 | 统一行程 | `journey/` |
| C11 | 交易财务 | `payments/` 及共享资金服务 |
| C12 | 平台、安全、模型网关 | `core/`、`security/` 等平台能力，以及 Runtime 组件 |
| C13 | 独立质量验收 | `control-plane/c13-c14-lite/`、相关工作流 |
| C14 | 规则与边界审核 | `control-plane/c13-c14-lite/`、相关工作流 |

表中路径是阅读导航，不是精确写权限或代码所有权清单。共享文件必须按业务语义与现有实施负责人协调，尤其不能因能修改 `services/` 就直接改写资金事实。

### 4.1 Runtime 仓库侧代码

```text
control-plane/
├── runtime-host-channel-v1/
│   ├── c1_issue_ingress.py           开发 Issue 入口
│   ├── c1_issue_consumer.py          Issue 消费相关能力
│   ├── c1_ghaw_builder_worker.py     Builder 执行器
│   ├── c1_review_issue_ingress.py    审核 Issue 入口
│   ├── c1_c13c14_review_worker.py    C14/C13 审核执行器
│   ├── c1_c13c14_review.py           审核链传输
│   ├── c1_execution_contract.py     执行契约
│   ├── c1_execution_loop.py         执行循环
│   ├── c1_dispatch_outbox.py         分发 outbox
│   ├── c1_result_pull.py            结果读取
│   ├── c1_worker.py                 共享执行库
│   ├── systemd/                    服务定义
│   └── test_*.py                   组件测试
└── c13-c14-lite/                    独立审核组件
```

根规则定义两条执行链：Builder 和 C13/C14 审核。常规顺序为开发 Formal Issue、Builder、一个 Draft PR、C14、符合准入条件后 C13，最后形成密封审核结论。

`c1_worker.py` 是共享库。实际忙闲情况要读取 Runtime 进程、队列和租约，不能根据文件数量推断。

根 `AGENTS.md` 明确记录：部分 Runtime 源码在 `main` 为零字节，源码记录保留在分支中。这是已知来源缺口，本文只报告，不据此修复、删除、重装或调整主机。

## 5. 部署、CI 与历史材料

| 位置 | 用途与边界 |
|---|---|
| `deploy/hk-staging/docker-compose.business-runtime.yml` | 当前业务运行定义，不是实际运行状态证明 |
| `.github/workflows/` | Builder、C13/C14、检查、打包等 GitHub Actions 定义 |
| `ci/` | CI 配套脚本与检查材料 |
| `packaging/` | 打包、封存及历史归档能力 |
| `docs/governance/` | 根规则明确依赖的变更治理约束 |
| `docs/runtime/`、`docs/go-forge/` 等 | 历史设计与取证材料，不能替代根当前入口 |
| `command-center/` | 旧 Command Center 归档 |
| `hk-staging/` | 旧运行时快照 |
| `deliverables/`、`evidence/` | 绑定原始提交的历史交付和证据 |

当前部署和检查分别使用 GO Forge 的 `FORGE_DEPLOY`、`FORGE_INSPECT`。提交任务后需读取同一 task_id 的 Receipt 和正式 Evidence。主机运行身份取自最新 signed VERIFY Evidence，不能从本仓库文件推断。

## 6. 主要开发语言

| 部分 | 主要语言 | 技术框架或文件形式 |
|---|---|---|
| 业务后端 | Python | FastAPI、Pydantic、SQLAlchemy |
| 数据库迁移 | Python | Alembic |
| iOS / Android 主体 | TypeScript | React Native、Expo，`.ts` / `.tsx` |
| Apple 原生扩展 | Swift | `native/apple/*.swift` |
| 网页端 | HTML、JavaScript、CSS | `frontend/`，Vite 开发配置 |
| Runtime 仓库侧组件 | Python | `control-plane/runtime-host-channel-v1/` |
| 检查与辅助工具 | Python、JavaScript 及 Shell 等 | 按具体脚本确认 |
| 构建、工作流与平台配置 | YAML、JSON、JavaScript 等 | Compose、GitHub Actions、Expo / EAS 配置 |

## 7. 新开发人员的阅读顺序

1. 阅读根目录 `AGENTS.md` 和 `README.md`，确认当前工作路径与权限边界。
2. 确认业务负责人、现有工作和接口边界，定位对应业务源码。
3. 后端从 `application/src/go_hotel/main.py`、相关 API 和领域服务进入。
4. 网页从对应 `frontend/consumer/`、`supplier/` 或 `admin/` 进入。
5. 移动端从 `App.tsx`、目标页面、公共组件和 `design.ts` 进入。
6. AI 执行与审核从根规则和 `control-plane/runtime-host-channel-v1/` 进入。
7. 历史交付与证据按具体问题查阅，保留版本与范围信息。

开发永久改动遵循短期分支、提交与测试、PR、复核及具体授权的合并流程。目录和源码存在、CI 通过、PR 合并与产品完成、实际部署分别记录。

## 8. 核对依据

- 根 `AGENTS.md`、`README.md`。
- 本地目录枚举与 `git ls-files`。
- `application/pyproject.toml`、`application/package.json`。
- `application/mobile/go-app/package.json`、`App.tsx`、`app.json`、`app.config.js`。
- `application/mobile/go-app/src/design.ts`、`src/components/GO.tsx`、`src/screens/HomeScreen.tsx`。
- 移动端 `assets/`、`native/apple/` 及 Runtime 仓库侧目录。

本次未执行产品功能验收，未读取 iOS 发布平台、香港主机或 Runtime 主机实时状态。