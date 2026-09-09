# GO DEPTH24 从断点恢复与审阅

本候选基于已上传 DEPTH23 `7c5a2e54e1243a8d6c1c297ef9cf8e2f2960a33b` 增量推进。历史源码、1542 项通过和6项跳过记录均原样保留。

新增铁路和门票未付款占位期限：新建订单在数据库同一事务中冻结15分钟期限，返回 payment_deadline_ms；报价阶段不占位。后台任务默认随应用启动，每30秒扫描最多100项，到期后核验原订单、支付意图、期限哈希和原始库存分配，再一次性取消、释放名额、写入原生事件与生命周期记录。任何支付意图存在均保留名额等待核对；历史订单没有期限记录时不追溯取消。

即使清理任务尚未运行，到期订单也不能创建新的支付根。支付、主动取消和到期清理都先锁原订单。火车票在支付根创建前失败时保持待付款，不虚写已授权状态。

## 独立还原

保留原父包和 GitHub DEPTH17 WORK；不能用同名但不同SHA的WORK替换。2026-09-09资料库的同名WORK已因哈希不符被拒绝，使用私有仓库13个固定分片恢复正确原件。

```sh
python3 scripts/assemble_depth24_review.py --parent /path/GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip --base-work /path/GO_CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION_WORK_20260908.zip --delta /path/GO_CP11_DEPTH_24_UNPAID_EXPIRY_DELTA_20260909.zip --output /new/empty/path
```

父包 SHA256：8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb

WORK SHA256：1b1af66dfdb71f350d5aba81544c90c95e51b7f54a380a10e3bdec6778032d79

还原器拒绝路径越界、符号链接、重复条目、错误基线和移除项，逐文件核对组合后完整清单。迁移头为0131_vertical_payment_deadline。任何已有期限历史都禁止删除式回滚；使用备份恢复。

## 运行与核验

```sh
PYTHONPATH=src gate_runtime/python/bin/python -m go_hotel.workers.vertical_expiry_worker --once
```

VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED默认true。关闭后台任务时，到期付款保护仍生效，但未付占位需要显式运行清理；不能宣称资源已自动回收。

前端验证使用原约束 Node v22.22.0，官方包SHA256为9aa8e9d2298ab68c600bd6fb86a6c13bce11a4eca1ba9b39d79fa021755d7c37。前端只显示服务器期限和持久状态，不用浏览器时间决定取消。

最终结果见verification/current_build/depth24/CURRENT_BUILD_STATUS.json及acceptance/GO_DEPTH24_REVIEW.md。FINAL RELEASE GATE仍HOLD：PostgreSQL/Redis真实执行、全部业务深度和母版验收尚未全部关闭。本工程审阅包不构成香港部署、RDS变更或真实资金操作。
