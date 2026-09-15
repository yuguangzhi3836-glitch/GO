# DEPTH48 源码合成父包

本轮将已合并的 DEPTH47/48 修复、独立资金审计和历史完整父包合成一个可下载的源码候选包。名称为 `CP11_DEPTH48_SOURCE_COMPOSITE_PARENT_20260913`，状态为 `SOURCE_COMPOSITE_CANDIDATE`。新运行镜像尚未重建，不能把内层 DEPTH46 镜像作为本轮源码的运行证明。

`source/` 固定 main 提交 `6d0fd905d1b6004fd5cc5cf8d69d1bf26a0f700a` 的全部顶层内容（历史 `deliverables/` 单独处理），包含 2,335 个文件、142,160,449 字节；其中应用源码 1,323 个文件，应用 Git tree 为 `ad7d1de1190f86ad29d1c6cdafbcedd592e27206`。酒店金额、多航段改签、PR53 独立审计、工作流、兼容修复、控制面资料与当前证据按原提交保留。

`previous_parent/` 完整复用 DEPTH46 归档的 24 个文件，包括 16 个原始 ZIP 分卷。拼接后的历史 ZIP 为 314,723,816 字节，SHA256 为 `cc9b16be9555a2499db29a9ce0ebc25879fedd2953577bedc1f5e6e833451ce9`。其中的镜像、19 个兼容文件、PR51 补充资料及历史还原记录仍属于 DEPTH46。旧父包内的源码和本轮 `source/application/` 分开保留；没有覆盖、重标或运行旧镜像。

本轮采用 Git 对象合成，源文件、图片及二进制分卷均引用仓库中已有的真实内容对象，不用本地占位文件。仓库递归回读对照文件路径、类型、权限、大小与 Git SHA。当前环境未能取得完整二进制检出，未执行实际全包逐字节校验、解包还原或镜像构建；离线工具的 8 项合成夹具测试不能代替这些验收。

## 下载后的离线校验与 ZIP 重封装

使用 Python 3.12 或以上。在 GitHub 源码 ZIP 解压目录中，进入包含本文件、`source/` 和 `previous_parent/` 的父包目录。`--manifest-sha256` 使用仓库 `docs/canonical-baseline/CURRENT_SOURCE_PARENT.json` 中记录的外部清单指纹。

```bash
python -B verify_parent.py --directory . --manifest-sha256 <清单SHA256>
python -B create_archive.py --directory . --manifest-sha256 <清单SHA256> --output ../CP11_DEPTH48_SOURCE_COMPOSITE_PARENT_20260913.zip
```

校验包括两个有效载荷的完整 Git tree、文件数量和字节数、1,323 个应用文件的逐文件 SHA256 和总指纹、16 个分卷的 SHA256 及串接后的历史 ZIP SHA256。文件缺失、多余文件、权限变化、软链接或篡改会拒绝通过。ZIP 重封装使用固定时间戳，逐成员回读后排他写入目标，不覆盖既有文件；仅复制与校验，不安装或运行应用。校验需要保留 Git 可执行权限的文件系统；解压软件丢失权限会导致校验失败。

完整原父包的重构工具仍在 `previous_parent/`，其结果只代表历史 DEPTH46。新镜像须另行从本包固定应用树重建，并补齐固定依赖运行时 CI、PostgreSQL、真实设备及完整三端可见页面验收，再生成新的自包含运行父包。

## 证据边界

现有 DEPTH48 本地最新逐项结果为 1,796 个后端通过、6 个 PostgreSQL 跳过、270 个前端通过、原生端 TypeScript 通过、11 个 SQLite 迁移检查通过。六模块同单三角色接口及独立 SQL 检查已通过。这些是继承的源码验收记录，本次未重跑。

完整三端页面、固定运行时 CI、Sealed Node 与最终发布保持 HOLD。已有 CI 失败保留原始记录，不因打包改为 PASS。历史 `4189/consumer/` 验收仅以已有原件为准，缺失的原始返回、会话标识或运行源码指纹不能由重跑补认；本轮没有生成浏览器重跑记录，也没有用打包测试补认历史验收。香港和 Production 未访问或部署。各 `source/` 内历史状态文件固定于快照提交；本包当前状态以根清单和仓库源码父包索引为准。
