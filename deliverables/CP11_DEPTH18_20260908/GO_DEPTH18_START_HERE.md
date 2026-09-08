# GO DEPTH18 工程审阅入口

这是 DEPTH17 之后的媒体持久性与区域任务恢复增量。系统仍为 HOLD，尚未全面完工或部署。

本轮功能：媒体元数据事务化、多进程授权历史与并发写入、逐次授权取图、区域任务数据库租约/确认/重试、幂等分发与失败接续。详见 `acceptance/GO_DEPTH18_REVIEW.md` 和实测状态文件。

## 恢复

累计源码及运行环境继续沿用已核验父包与 DEPTH17 WORK。本增量不包含重复的离线运行环境。

1. 从 `deliverables/CP11_DEPTH17_20260908/` 使用 `join_depth17_work.py` 合并 `work_parts/`；该目录的清单会检查每卷和完整 WORK。
2. 准备此前恢复的原父包，SHA256 为 `8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb`。
3. 核对本目录 `GO_DEPTH18_SHA256SUMS.txt`，再执行：

```bash
python3 assemble_depth18_review.py --parent /path/to/GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip --base-work /path/to/GO_CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION_WORK_20260908.zip --delta /path/to/GO_CP11_DEPTH_18_MEDIA_REGIONAL_DURABILITY_DELTA_20260908.zip --output /new/path/go-depth18
```

输出目录必须不存在。恢复器验证父包、基线、每个增量文件及完整结果清单，不会覆盖已有工作目录。

进入恢复目录后：

```bash
./gate_runtime/python/bin/python scripts/verify_delivery.py
./gate_runtime/python/bin/python scripts/run_local_demo.py --check --data-dir /tmp/go-depth18-demo
./gate_runtime/python/bin/python -m pytest
```

本地演示按原隔离环境运行。生产数据和第三方渠道的发布门禁仍关闭。

## 已有环境升级要点

- 新增迁移 `0125_regional_queue`；之前的 124 个迁移不变。队列有任何记录时禁止直接降级删除表。
- 媒体 `index.json` 首次校验后导入同目录 `index.sqlite3`，保留原 JSON 及其指纹。后续以数据库为准，重启不重新导入旧授权。损坏的 JSON 不会被空索引覆盖。
- 媒体库与 `files/` 应存放在可靠的本机持久磁盘。数据库使用 SQLite 备份接口，或停止写入后与文件一并备份；运行中不要只复制数据库主文件。本轮未认证共享网络磁盘或分布式对象存储。
- 图片授权 API 现在要求提交列表所返回的 `expected_revision`，冲突需刷新后重新决定。公开与后台图片响应改为 `no-store`。此前已收到一年缓存响应的客户端需清除旧缓存；新响应无法追溯撤回已下载的图片。
- **旧 Redis 区域任务不会自动删除或丢弃。** 切换前停止旧 worker，保存原队列导出 JSON；用 `scripts/import_regional_queue_snapshot.py --snapshot <export.json> --receipt <new-receipt.json>` 先校验，再加 `--apply` 幂等导入。脚本不删除 Redis 数据，失败后可凭同一导出重试。本轮只实测导出文件→数据库恢复，未认证真实 Redis 导出/切换。
- 队列完成确认表示一次任务处理完成；酒店仍须通过内容、图片、房型与质量门禁才能被视为完整。数据库租约未被夸大为所有发现适配器副作用的恰好一次执行。

母版源段落追溯表覆盖 63 页的所有索引段落，仍逐项标为待分解、未验收；不能把收录源文当作全面完成。
