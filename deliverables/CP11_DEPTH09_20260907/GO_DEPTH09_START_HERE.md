# GO DEPTH09 · 酒店快速复制准确性候选

**当前不能认定一键建酒店库功能齐全或已经具备真实批量复制能力。**
`HOTEL_REPLICATION_GATE=HOLD`，`FINAL_RELEASE_GATE=HOLD`，未部署。

本批继承 DEPTH08，仅处理酒店建库的身份、官网房型采集、图片对应、页面版本与完成统计问题。
原有六大业务与 DEPTH08 自运营执行内核保持原件；没有向香港下发任务。

## 先看这些文件

- `acceptance/GO_DEPTH09_REVIEW.md`：发现、修复、验证范围与剩余缺口。
- `verification/current_build/depth09/CURRENT_BUILD_STATUS.json`：当前测试数字与门禁。
- `acceptance/DEPTH09_SOURCE_CHANGES.json` 和 `.patch`：逐文件源码差异。
- `verification/current_build/depth09/full_regression.xml`：最终完整 Python 回归。
- `verification/current_build/depth09/targeted.xml`：从同一次完整回归抽取的新测试原记录。
- `verification/current_build/depth09/live_official_probe.json`：应用采集器对敖麓谷雅官网的只读探测；当前执行环境 DNS 不可解析，未按“抓取成功”记录。

## 恢复完整候选

准备原 CP11、DEPTH07 WORK、已归档的 DEPTH08 增量和本批 DEPTH09 增量。
在同一目录放置 `assemble_depth08_candidate.py` 与 `assemble_depth09_candidate.py`，执行：

```bash
python3 assemble_depth09_candidate.py \
  --parent GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip \
  --depth07-work GO_CP11_DEPTH_07_DIRECT_MONEY_LEDGER_WORK_20260907.zip \
  --depth08-delta GO_CP11_DEPTH_08_DURABLE_EXECUTION_DELTA_20260907.zip \
  --delta GO_CP11_DEPTH_09_HOTEL_REPLICATION_DELTA_20260907.zip \
  --output GO_DEPTH09_REVIEW
```

恢复只允许新目录；核对依赖原件、ZIP CRC、内部文件哈希、每个修改文件的旧哈希，以及最终源码树。
这一步恢复已通过的基线，不重新开发 DEPTH07/08。

## 隔离复核

在恢复目录运行：

```bash
gate_runtime/python/bin/python -m pytest tests/test_depth09_hotel_replication.py
```

测试使用隔离数据库和明确的合成官网/图片；不会连接真实供应商、发送酒店邮件或部署。
覆盖 10 家合成酒店复制与重复导入、并发同源更新、跨酒店房型与照片隔离、事务回滚、
不完整更新保留上一版完整页面、人工下架保持、图片失效后的阻断和管理端写权限。

## 已接入的产品行为

现有 `POST /internal/v1/hotel-discovery/seeds` + `/jobs/{job_id}/run` 对
`OFFICIAL_WEBSITE` 和 `GROUP_OFFICIAL` 使用新采集器。来源须明确给出酒店名称与官网 URL。
采集器支持酒店节点通过 `containsPlace` 明确引用 `HotelRoom`/`Suite` 的 JSON-LD，
仅读取同源房型页面，保留来源页面和文档哈希；每次最多 32 页，预算 90 秒。
跨源房型、名称不匹配、歧义、缺页或不支持的结构均不能变成完整候选。

`state=COMPLETED` 的来源任务仅表示来源处理结束，必须同时查看 `stage`、`build_state`
和 `catalog_quality`。区域统计不再把资料待补的酒店算成建库完成。

房型全量清单核验与内容采集分开记录。采集器不会自称已经覆盖官网全部房型；
`containsPlace` 条目数和酒店物理客房总数不能替代完整房型清单。
完整目录核验记录应由具有 `admin:rules` 的管理员在对照官方清单后提交，
绑定原始页面 SHA、所核对的全部房型 ID 和复核人；不得使用样例记录充当真实证据。
目前该复核记录通过现有受控来源导入接口接入，专用复核界面仍待建设。

图片必须来自对应官网条目的明确绑定，并通过现有缓存文件、哈希和当前可发布状态检查。
官网只有两张图就核对这两张，不凑第三张。图片候选仍需接入实际下载和审核链，
本批没有把“采集到了图片 URL”视为媒体建库完成。

## 部署边界

本批没有新增数据库迁移，保留 `0116_autonomy_durable`；PostgreSQL 并发分支未实机验收。
新增的发布条件会阻止旧的“只有名称和地址”的简页公开，也会拒绝无新质量证据的旧版本公开读取。
已有完整版本在新资料不完整时保留；管理员下架不会因重新采集而自动恢复。
因此香港部署前必须先对现场旧页面进行兼容性盘点，不能直接将本候选覆盖线上。

快速准确复制的最终验收还包括：截图入口、真实官网适配、完整媒体流水线、区域任务持久恢复、
Canonical 到直订房型池的通用映射、跨酒店实测速度/准确率及真实浏览器/移动端验收。
