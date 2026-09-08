# GO DEPTH23 · 共享库存与改签结果恢复

本累计包从已提交 DEPTH21 继续，包含 DEPTH22 的铁路改签结果恢复和 DEPTH23 的铁路、门票共享库存。当前仍为 HOLD，未全面完工或部署。

## 独立还原

```bash
python3 assemble_depth23_review.py --parent /path/to/GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip --base-work /path/to/GO_CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION_WORK_20260908.zip --delta /path/to/GO_CP11_DEPTH_23_SHARED_CAPACITY_DELTA_20260908.zip --output /new/path/go-depth23
cd /new/path/go-depth23
./gate_runtime/python/bin/python scripts/verify_delivery.py
./gate_runtime/python/bin/python -m pytest
node --test tests_frontend/*.test.mjs
```

父包 SHA256：8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb。
DEPTH17 WORK SHA256：1b1af66dfdb71f350d5aba81544c90c95e51b7f54a380a10e3bdec6778032d79。
累计增量包含 DEPTH18–22，无需逐个叠加。校验本目录 SHA256 后，在全新目录还原；不涉及香港实例。

## 交易恢复

铁路管理接口 `/internal/v1/admin/rail/orders/{order_id}/external-state` 新增 `quote_id`，应传原改签报价编号。
确定结果先冻结，再执行补款扣取或释放授权，最后原子落盘。相同 quote_id 的原字段可重试；相反结果、改换票号或证据拒绝。已有处理历史却不带 quote_id 返回 409，避免迟到回报落到新申请。
进程直接退出后等待 30 秒数据库租约，继续原字段；资金结果不明时仍为待核对，不允许继续改签或退款。历史完成请求返回当时结果快照，之后 GET 订单获取当前状态。

## 库存与取消

- 铁路按车次、日期、席别共享整个车次的隔离库存；不同区间也保守共用，尚不做真实席位图的区间复用。
- 门票按产品、日期、场次共享库存；查询展示当前余量，预报价不占位，订单创建与名额分配同事务提交。
- 改签先占目标名额并保留原名额；确认后释放原名额，失败后释放目标名额。未知回报不释放任何名额。
- 退款资金核验完成才释放；核销后仍计入本场次已售数量。重复处理不重复释放。
- `/v1/rail/orders/{order_id}/cancel-unpaid` 与 `/v1/attractions/orders/{order_id}/cancel-unpaid` 只允许本人取消尚未启动支付的订单。已创建支付意图、已授权或结果未知时必须先核对支付。客户页面提供确认取消入口并在响应丢失后刷新原订单。
- 未支付名额不做未经付款协调的自动超时释放。历史订单没有库存记录时，相关库存查询与继续销售保持待核对，禁止把已售票当成空库存。需要另行核对旧订单才能迁移其存量。

迁移：0129_rail_change_resolution → 0130_vertical_capacity。保留历史迁移；有确认记录或库存分配历史时拒绝删除式降级。当前是隔离容量与支付功能，不表示真实渠道已连接。
