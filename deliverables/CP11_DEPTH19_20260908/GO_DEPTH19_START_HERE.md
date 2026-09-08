# GO DEPTH19 工程审阅入口

本轮接续已保存的 DEPTH18，增加逐航段、逐旅行者的签名值机事实，以及航班接送申请的持久恢复。**系统仍为 HOLD，尚未全面完工或部署。**

## 恢复

DEPTH19 交付是相对 GitHub 已保存的 DEPTH17 WORK 的累计增量，已经包含 DEPTH18 的修改。因此恢复时不需要另外叠加 DEPTH18。

1. 从同仓库 `deliverables/CP11_DEPTH17_20260908/` 获取分卷、清单和 `join_depth17_work.py`，合并出 WORK。完整 SHA256 必须为 `1b1af66dfdb71f350d5aba81544c90c95e51b7f54a380a10e3bdec6778032d79`。
2. 使用此前恢复的原始父包，其 SHA256 为 `8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb`。
3. 核对 `GO_DEPTH19_SHA256SUMS.txt` 后执行：

```bash
python3 assemble_depth19_review.py --parent /path/to/GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip --base-work /path/to/GO_CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION_WORK_20260908.zip --delta /path/to/GO_CP11_DEPTH_19_SIGNED_TRAVEL_FLEET_RECOVERY_DELTA_20260908.zip --output /new/path/go-depth19
```

输出目录必须不存在。恢复器验证父包、WORK、累计增量及每个结果文件，不覆盖现有工作目录。

进入新目录后：

```bash
./gate_runtime/python/bin/python scripts/verify_delivery.py
./gate_runtime/python/bin/python scripts/run_local_demo.py --check --data-dir /tmp/go-depth19-demo
./gate_runtime/python/bin/python -m pytest
```

## 功能与现有环境升级

- 新增 `0126_travel_operational_facts`，旧 125 个迁移、母版和品牌资产不变。先备份再通过现有迁移流程升级；有任何新事实、规则或申请记录时禁止直接降级删除证据。
- 原值机和接送绑定记录保留。未经签名的旧记录不会自动变成官方事实；旧接送缺少服务器规则快照时，需要核对原始条款，不能采用客户自己填的等待数字。
- 接送新单保存服务器规则快照。现有模拟报价的普通车型包含等待 60 分钟，高级车型包含 90 分钟；本轮隔离规则允许明确选择额外 30 分钟保护，不能超出规则上限。额外等待只用于签名事实明确标为 DELAYED 的事件；提前、普通落地与更正不会自动获得额外等待，页面区分条件上限与本次申请额度。这些是工程模拟条款，不是真实车队承诺。
- 历史订单未标时区的接车时间保持原始值，用作变更前条件；本轮不推断其时区。签名事实中的新抵达时间必须带时区，且仅在车队确认后成为订单新时间。
- 签名来源先通过 `/internal/v1/travel-fact-authorities` 登记公钥、权限、航司、链接域与期限；由另一位具有 `admin:rules` 权限的管理员批准。登记及批准均不能打开生产门禁。应用不保存签名私钥。
- 事实接口使用 `{fact, signature_hex}`。`fact` 正文包含 `authority_id/provider_id/event_id/kind/source_sequence/observed_ms/expires_ms/subject/data`，采用 UTF-8、键排序、紧凑 JSON、禁止 NaN 的规范正文签名。值机 subject 绑定当前订单、航段、乘机人、客票、行程及旅行者指纹。详细可执行例子见 `tests/test_depth19_travel_facts.py`。
- 事件重放不增加新申请；相同事件身份但内容不同会拒绝。来源更正采用递增序号，允许撤回过时的值机状态，不强制沿状态等级单向前进。
- 接送先保存建议时间和申请。隔离车队处理器持久保存回执；失联或进程中断后查询原申请，绝不盲目重发。若已确认的车队结果与当前授权、订单或绑定冲突，进入 `HOLD`，可在 `/internal/v1/mobility/flight-adjustments` 查看，等待人工核对。

隔离处理器只运行一个有上限的批次，可由本地受控调度器重复调用。它不连接真实车队，也不启动常驻自动服务：

```bash
PYTHONPATH=src ./gate_runtime/python/bin/python scripts/run_flight_ride_sync.py --simulate --receipt-db /persistent/local/path/isolated-fleet.sqlite3 --limit 100
```

回执数据库必须与应用数据库分别持久保存。不要删除回执库来尝试重发未知申请；丢失回执时应核对原申请。

## 尚未验收

真实航司/车队与司机通知、生产授权证据、跨设备视觉、PostgreSQL、真实 Redis 切换等仍独立验收。值机的 GO Trips 列表及出发前统一入口、实际等待超时后的费用/取消闭环、ETA/司机流程和未知结果人工核对闭环还需继续深化。六品类高级售后、完整费用结算及 14 个业务细胞自动执行也尚未全面闭合。

详见 `acceptance/GO_DEPTH19_REVIEW.md` 与 `verification/current_build/depth19/CURRENT_BUILD_STATUS.json`。测试数量不作为全面完成百分比。
