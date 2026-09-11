# DEPTH40 八服务 Staging 构建补件

本包解决固定候选缺少镜像构建定义与八服务配置合同的问题。不是香港部署结果。
交付工具独立于软件父包；不得改变下面的 1271 个源码文件，不能用香港旧容器或本地源码补齐。

| 固定身份 | 值 |
|---|---|
| Candidate | CP11_DEPTH40_P03_PARENT_20260911 |
| Parent Build Head | c909af370d55ce7644140a191425a8a66dacec9a |
| Artifact ID | 10183252130 |
| Artifact ZIP SHA256 | d0aa4b89ed0655271cf5ef7a12cce354dc8d84704cf57071f581f129458cbaf7 |
| Parent Archive SHA256 | 2909651f9b644ed56fd6ab833480c9da32b4c5b900df2e5afb192dba49ac2b00 |
| Source Tree SHA256 | 64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667 |
| Source files | 1271 |

## 交付及验证范围

- `Dockerfile` 使用 FROM scratch；完整 CPython 3.13.5、37 个冻结依赖与动态库由指挥中心打包。
- `ROOTFS_FILES.json` 记录完整构建输入字节，`ROOTFS_BINDING.json` 记录来源；不能只凭 Python 版本宣称不同构建字节完全相同。
- 离线镜像分卷及 `RUNTIME_MANIFEST.json` 绑定镜像 config Image ID、压缩包 SHA256、工具提交。
- config Image ID 与 registry RepoDigest 是不同标识。本包不伪造 registry digest；既有 R4 Executor 要求 RepoDigest，接入仍待有授权的镜像仓库及执行器合同核验。
- `compose.staging.review.yml` 是候选八服务的审核合同，不是已绑定现网的可执行清单。只引用一个已核验的既有外部网络；不创建/修改 Redis、Caddy、数据库或网络。
- API 监听容器 8000，提供 `/health`、`/go-app/`、`/supplier-console/`、`/go-admin/`。现有 Caddy upstream、三个域名与静态资源路由必须只读核对。不得假定 HTTPS 已兼容。
- 本轮 CI 直接运行新镜像及相同八个角色，验证 PG16、Redis、HTTP 静态页面/登录、旧 Head 拒绝及 Worker 存活；不等同于三端真实浏览器旅程、六品类交易验收、负载测试或香港回滚验证。

## 服务和配置名称映射

| 服务 | 固定模块/入口 |
|---|---|
| api | go_hotel.main:app，端口 8000 |
| recovery-worker | go_hotel.workers.recovery_worker |
| outbox-worker | go_hotel.workers.outbox_worker |
| mobile-push-receipt-worker | go_hotel.workers.mobile_push_receipt_worker |
| reconciliation-worker | go_hotel.workers.reconciliation_worker |
| mobile-push-worker | go_hotel.workers.mobile_push_worker |
| mobile-engagement-worker | go_hotel.workers.mobile_engagement_worker |
| judgment-worker | go_hotel.workers.judgment_worker |

八服务通过获批执行器注入 `GO_RUNTIME_ENV_FILE`，本包不附环境文件。所需名称：
`APP_ENV`（staging）、`DATABASE_URL`（postgresql+psycopg）、`REDIS_URL`、`JWT_SIGNING_KEY`、
`CONNECTOR_VAULT_MASTER_KEY`、`WEBHOOK_SECRET`、`BOOTSTRAP_ADMIN_USERNAME`、`BOOTSTRAP_ADMIN_PASSWORD`、
`BOOTSTRAP_SUPPLIER_USERNAME`、`BOOTSTRAP_SUPPLIER_PASSWORD`、`BOOTSTRAP_SUPPLIER_ID`、
`COOKIE_SECURE`、`MFA_REQUIRED_FOR_ADMIN`、`OUTBOX_TRANSPORT`、`MOBILE_PUSH_MODE`、
`HOSTED_RESERVATION_EXPIRY_WORKER_ENABLED`、`VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED`。
另需 `GO_MEDIA_CACHE_DIR=/state/media` 和经现场核验、备份的持久卷 `GO_VERIFIED_MEDIA_VOLUME`。
源码中的媒体服务在导入时会打开本地索引，不能把缓存放到只读源码目录或丢失即清空的 tmpfs。
启动预检只读验证既有 `index.sqlite3` schema=1、files/ 和权限；缺失时拒绝，不自动创建或导入旧 JSON。
只有隔离 CI 会在全新测试卷生成空索引。香港如只有 legacy JSON，必须先对备份副本验证兼容转换/恢复，再明确处理许可。
本配置合同的外部卷应以 `/state` 为挂载根、`media/` 为索引目录；若现网使用 bind mount 或不同布局，应由指挥中心根据实际只读材料定版，不在香港重排数据。
其余原候选配置按现有批准映射核对，不能在香港补开发。

本补件只允许已审核的 Redis/logging outbox 模式和 mock mobile push；如现网值不同，停止并回传配置**名称**及不兼容项。
不强行改成 CI 值。HTTPS 要求 `COOKIE_SECURE=true`，管理员 MFA 按已批准策略核对；CI 的 false 仅供无外呼 HTTP 测试。
运行时所需 CA 文件可以来自只读 Secret/证书挂载，但路径和哈希需在最终清单明确；本包不修改服务器证书。

镜像默认只执行只读 preflight；未知角色、锁定区域 Worker、Production 环境、缺失配置和默认密钥均拒绝。
预检通过后，角色启动仍须香港正式执行授权与签名任务；preflight PASS 本身不是部署许可。

## 数据库和迁移决定

`MIGRATION_EXECUTED=NO`；香港本次不执行 upgrade、stamp、downgrade 或 create_all。
要求当前 RDS 已在 `0132_rail_runtime_field_widths`，且模型所需列与关键铁路字段宽度通过只读检查。
此 Head 是本源码完整服务的保守启动前置条件，不表示已批准从香港未知 Head 迁到此处。

预检使用数据库 `default_transaction_read_only=on`，连接/语句有超时，固定 public schema，只做 SELECT/SHOW；Redis 只 PING。
应用启动会调用 ensure_user，因此预检必须确认两个 bootstrap 对应用户已存在、类型/状态/供应商绑定正确，避免意外创建账户。
所有服务启动前执行同一门禁；失败只输出脱敏错误码、结构差异和版本，绝不自动修复。

CI 在全新、断开外网的 PG16 测试库运行真实迁移链并生成临时身份；其结果明确标为 `DISPOSABLE_CI_DATABASE_ONLY`。
CI 迁移失败时保留原始日志，不能改为 create_all/stamp 来宣布迁移通过。
香港 Head 未回传，`HK_DATABASE_COMPATIBILITY=HOLD`；需要新迁移方案时先由指挥中心设计、验证、单独明确批准。

## 资源预算与现场补件

实际镜像大小见清单。磁盘规划：2×压缩镜像包 + 2×解压镜像层 + 160 MiB 日志 + 2 GiB 宿主机余量 + 实测可恢复备份字节。
备份体积未知，因此完整磁盘需求保持 UNKNOWN。禁止删除旧镜像、清库、清媒体来满足预算。
内存上限规划为 API 512 MiB + 7×192 MiB = 1856 MiB；另留至少 768 MiB 主机缓冲。
这是上限预算，不是实测峰值，也不能把替换后释放的现有内存提前计入可用量。
需要由已批准的只读入口核验当前可用资源和替换时的峰值预算。

香港只读材料仍需：当前 RDS Head/版本、八服务实际配置和环境**名称映射**、Caddy upstream/域名及 TLS 相关映射、
当前网络标识与挂载、可恢复备份方案与大小、既有正式签名任务入口/允许的镜像来源。
运行 Image ID 与 RepoDigest 的绑定需同次脱敏 inspect 原件；不得仅凭不同摘要认定运行已变。

## 停止与回退方案

1. 切换前由正式执行器保存 durable previous-state：当前八服务镜像 config ID/RepoDigest、清单和配置哈希、RDS Head、健康/Worker 状态、非目标指纹、已验证备份位置/哈希。Secret 只记名称。
2. 若包/源码/环境/数据库/预算/回退入口任一未通过，停在切换之前。不得让新镜像试着适应未知旧库。
3. 应用回退只能在未执行 schema 变更、存在可恢复旧镜像和配置、实际前后数据库兼容、没有需要处理的部分交易影响时进行。
4. 旧 R4 固定执行器明确没有自动回滚。本用户已表达失败回退授权，但执行工具和现场目标尚未绑定；不能附一条泛化 `compose up` 命令冒充已经验证的回退。
5. 切换后故障按已审核的停止/回退入口对精确八服务操作，禁止碰 Redis/Caddy/Control Plane，禁止降级数据库、自动恢复数据库快照或在线改源码。
6. 对真实交易/外部副作用做清单核对，应用镜像回退不能撤销资金/供应商副作用。测试仅使用另行已授权沙箱。

`HK_ROLLBACK_READY=HOLD_LIVE_PREVIOUS_STATE_AND_APPROVED_EXECUTOR_MAPPING`。
最终目标绑定缺失时，本包不包含可直接执行的香港切换/回退脚本，避免绕过既有签名控制路径。

## 当前授权及门禁

用户已授权固定 DEPTH40 的 HK Staging 部署方向；随后明确在兼容补件对齐前停止构建/容器切换。
本次指挥中心范围为构建补件、隔离 CI 和私有仓库归档。没有执行香港命令，也未要求重复审批已授权的代码归档/CI。
继续保持 MERGE=NO、HK_RUNTIME_MUTATION=NO、MIGRATION=NO、PRODUCTION=NO。
实际香港包→镜像→容器→Runtime 绑定和签名回执由获批执行产生；不提前填写 PASS。
`PHYSICAL_IPHONE_GATE=HOLD_EXTERNAL_DEVICE_RUNNER`；其他 Gate 均以同候选原始证据为准。
