# DEPTH36R3 — CI 34453179558 原始证据永久归档

本归档只保存已完成 CI 的原始数据并进行离线校验，不重跑 CI、不修改业务代码、不合并、不部署。新增独立证据分支，不移动任何旧候选或验收分支。

## 精确绑定

| 项目 | 固定值 |
|---|---|
| 仓库 | `yuguangzhi3836-glitch/GO` |
| 源码候选 DEPTH36R3 | `7bd98db21ee950aeb91c12b296b1864b5a758c3f` |
| CI 工具提交／归档父提交 | `9725334a729f9ea43b6cb62c63bf52539511f312` |
| CI | [34453179558，attempt 1](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34453179558) |
| CI 完成时间 | 2026-09-10 08:16:05 UTC／16:16:05 北京时间 |
| 源码树 SHA256 | `c58edb0c0568c3f9fe80ba014c260513a07a8e74b211b608ade4d9052f8645b3` |
| 源码文件 | 1267 |
| CI 原始源码 ZIP SHA256 | `b4634f9da515a22f95fb740b979c2f77fdce29342eabbb9c54e5c666976f5b86` |

源码候选、CI 工具提交、此证据提交、源码 ZIP 和香港运行镜像是不同对象。源码 ZIP 不是 Docker 镜像，也不是已批准的香港部署包。

## 已直接核验

已读取四个分片和覆盖作业的完整原始日志；下载五个原始 artifact ZIP，分别重算 SHA256，与 GitHub artifact 元数据完全一致。各分片 27 个原始成员均保留在可逐字节还原的 ZIP 中。每个分片的 26 个非源码包文件另行展开，便于审阅；共同源码 ZIP 随原始 ZIP 永久保存。

日志中的 40 份 Base64 原始记录均通过字节长度和 SHA256 检查，并与下载产物中的原文件逐字节一致。覆盖作业打印的 JSON 与下载所得 `coverage.json` 逐字节一致。原始源码 ZIP 内 1267 个源码文件已在归档端独立重算哈希，与绑定指纹一致；这是离线文件检查，不是重新执行应用测试。

| 分片 | 原始作业 | 选中／收集后执行 | 通过 | PostgreSQL 跳过 | 失败／错误 |
|---|---|---:|---:|---:|---:|
| 0 | [102793384757](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34453179558/job/102793384757) | 396 | 391 | 5 | 0／0 |
| 1 | [102793384777](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34453179558/job/102793384777) | 444 | 444 | 0 | 0／0 |
| 2 | [102793384639](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34453179558/job/102793384639) | 382 | 382 | 0 | 0／0 |
| 3 | [102793384454](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34453179558/job/102793384454) | 457 | 456 | 1 | 0／0 |
| 合计 | [覆盖作业 102796665079](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34453179558/job/102796665079) | 1679 | 1673 | 6 | 0／0 |

归档端独立检查了完整测试集合、分片归属、JUnit 单项身份与计数、运行阶段报告、集合并集和无重复性：230 个测试文件的 1679 项测试没有漏分片或重复计入。6 项跳过的原始原因均为 `POSTGRES_TEST_DATABASE_URL not configured`，不是通过，也不是测试失败。

CI 环境为一次性 Ubuntu 22.04 runner、Python 3.13.5、SQLite 和合成数据。每个分片另完成同一套 10 项离线包装检查及 148 项／87 次请求的本机回环 HTTP 检查；四次重复运行不计作 592 项不同验收。原始记录确认离线包还原及测试后 1267 文件无漂移。Node 22.22.0 用于后端测试中的原生 API 桥接，不是完整封存 Node Gate。

## 证据目录与复核

- `shards/0..3/workflow.log`：原始完整作业日志；同目录保留展开的原始测试、依赖、还原、HTTP 和校验记录。
- `coverage/workflow.log`、`coverage.original.json`、`coverage.from-log.json`：覆盖作业原始输出与两条来源的同字节 JSON。
- `artifact-parts/`、`verification/artifact-parts.json`：五个原始 ZIP 的无损 Base64 分片和排序／长度／SHA256 清单。为去除重复存储，仅切分原始字节，未重压缩或改写 ZIP。
- `verification/frame-checks.json`、`independent-audit.json`、`artifact-audit.json`、`skipped-tests.json`：归档端重算结果和所有跳过项。
- `binding/`：GitHub 元数据快照、原始指纹及候选清单；`producer/` 是运行时所用 CI 脚本的固定提交副本，不在本次执行。
- `SOURCE_INDEX.json`：每类证据的精确来源、时间和可信范围；`SHA256SUMS` 是本归档文本及 Base64 分片文件的校验清单。

仅离线复核已有证据，不安装依赖、不启动服务：

```sh
sha256sum -c SHA256SUMS
python verify_archive.py
python verify_artifacts.py
```

第二个脚本可从已归档分片还原五个原始 ZIP，并检查 ZIP 哈希、CRC、成员内容及源码指纹。脚本发现既有文件内容不同会停止，不覆盖旧证据。恢复出的 ZIP 是复核中间文件，不需再次提交。

## 限制与交接

`THREE_END_REAL_UX_LOGIN=HOLD` → `SIX_VERTICAL_REAL_E2E=HOLD` → `SEALED_NODE_GATE=HOLD` → `FINAL_RELEASE=HOLD`。

本次不能证明真实浏览器登录、桌面／移动视口或原生设备体验、真实 PostgreSQL／Redis、支付渠道沙箱接通、酒店官方事实完整性、六品类用户旅程、香港控制回流／运行绑定、运行镜像兼容性或回滚演练。旧候选上的前端通过数不得合并进本候选。未收到的香港预检／签名回执保持 UNKNOWN，不据缺失证据制造失败。

新隔离验收交接单为 [DEPTH36R3_HK_SERVER_HANDOFF_20260910.md](../../docs/acceptance/DEPTH36R3_HK_SERVER_HANDOFF_20260910.md)。旧 DEPTH35R2 交接单与所有候选原样保留；不得拿旧交接单部署新候选。PR #20 的既有 `PENDING` 摘要快照是归档前状态，不是本次原始日志核验结果。本次不修改 PR、不触发额外 CI。

唯一下一允许动作：由香港在既有已授权只读范围内，按新交接单补齐服务器预检回执；未知项如实标记，不为填写回执创建环境、启动服务或修改配置。指挥中心负责开发，香港只负责获批运维。
