# GO 退款确认与接送恢复 · 工程候选

HOLD；尚未全面完工或部署。累计包含 DEPTH18 至 DEPTH23，并追加铁路、门票退款确认及接送取消恢复。

## 客户确认

铁路、门票、接送退款报价返回 `quote_hash`。客户确认报价后，分别 POST `/v1/rail/orders/{id}/refund`、`/v1/attractions/orders/{id}/refund`、`/v1/mobility/orders/{id}/cancel`，正文为 `{"expected_quote_hash":"报价返回值"}`。同一确认保留同一 Idempotency-Key。

订单、日期、票券/供应商身份或退款方案变化会拒绝旧确认。GET 同一订单的 `/refund-progress` 只读；POST `/refund-progress/reconcile` 仅恢复已经受理的同一申请。接送退款处理中禁止上车、改时或旧状态回写；车队调整已发出但结果未核清时，先核清车队动作。

旧版本已经完成的接送退款返回原收据，不补造过去的客户确认。租车与机票的确认接口仍沿用原合同，完整升级尚待继续。

## 可复现恢复

```sh
python assemble_refund_ride_review.py \
 --parent GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip \
 --base-work GO_CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION_WORK_20260908.zip \
 --delta GO_CP11_REFUND_AND_RIDE_RECOVERY_DELTA_20260908.zip \
 --output /new/go-refund-ride
```

必须使用新目录。脚本核对父包、基包、累计增量及最终每个文件。无需再叠加 18—23。进入恢复目录后可复测：

```sh
PYTHONPATH=src ./gate_runtime/python/bin/python -m pytest -q
node --test tests_frontend/*.test.mjs
```

## 保留的限制

模拟订单不能用于实际出行，模拟退款不表示银行卡到账。接送供应商的取消确认、临近出发费用与时区合同仍待认证；本次保留原隔离全额退款规则。真实供应商/PSP、PostgreSQL、Redis、跨设备视觉、六业务所有高级功能、14 个自运营业务单元及完整母版验收尚未通过。

新迁移 `0131_ride_refund_operation` 在原退款表中加入接送类型，保持旧记录；存在接送历史时禁止回滚删除其支持。验证覆盖 0127→0130 的真实表结构，再验证 0130↔0131；不声称所有历史迁移可从空库直接逐个执行。直接从 0001 逐个升级在历史 0113 遇到重复列，已保留诊断，现有父包初始化路径仍需单独遵守。
