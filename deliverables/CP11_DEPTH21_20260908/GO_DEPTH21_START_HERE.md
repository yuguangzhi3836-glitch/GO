# GO DEPTH21 · 退款中断恢复

当前为工程候选，`FINAL_RELEASE_GATE=HOLD`，尚未全面完工，未部署。

本轮相对 DEPTH20 新增铁路与门票退款持久记录、退款与改签/核销互斥、退款后崩溃恢复，以及铁路补款授权中断后继续原改签。客户订单页提供原退款和原改签的继续入口。

## 恢复完整代码

本累计增量包含 DEPTH18、19、20。使用原始 CP11 父包与 DEPTH17 WORK，不必分别叠加历史增量。

```bash
python3 assemble_depth21_review.py --parent /path/to/GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip --base-work /path/to/GO_CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION_WORK_20260908.zip --delta /path/to/GO_CP11_DEPTH_21_REFUND_RECOVERY_DELTA_20260908.zip --output /new/path/go-depth21
cd /new/path/go-depth21
./gate_runtime/python/bin/python scripts/verify_delivery.py
PYTHONPATH=src ./gate_runtime/python/bin/python -m pytest
node --test tests_frontend/*.test.mjs
```

父包 SHA256：`8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb`。
DEPTH17 WORK SHA256：`1b1af66dfdb71f350d5aba81544c90c95e51b7f54a380a10e3bdec6778032d79`。

新迁移为 `0128_vertical_refund_recovery`，上接 `0127_vertical_prebook_contract`。历史订单不伪造退款记录；有退款记录时拒绝直接降级。恢复命令只创建新目录；不迁移香港数据库，也不替换运行容器。

## 故障后的继续操作

- 重新读取原订单。`REFUND_PENDING` 时重复调用原订单的退款接口，服务器核对同一申请、相同原扣款和固定退款键。
- 如果前一次处理仍持有租约，返回 409，稍后刷新原订单。进程突然终止时，租约到期后可接管；资金结果未确定时保持处理中。
- 铁路 `CHANGE_PENDING` 且报价为 `PREPARING` 时，重复执行同一 `quote_id`，继续原授权，不能申请另一份报价或发起退款。
- `REFUNDED` 后重复请求返回同一退款凭证。更换账号无权读取或继续该申请。

这些是隔离模拟执行行为，不能视作真实供应商取消确认、真实退款或生产数据库验收。浏览器连接遭环境拦截，跨设备视觉验收仍开放。详见 `acceptance/GO_DEPTH21_REVIEW.md`。
