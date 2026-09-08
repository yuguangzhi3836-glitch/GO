# GO DEPTH23 · 共享库存与改签恢复

**当前仍为 HOLD，尚未全面完工或部署。**

从已归档 DEPTH21 继续，累计补齐铁路改签结果持久化恢复、铁路与门票跨报价共享库存、改签双库存保留及结果确认后释放、退款后释放、未支付订单取消与支付互斥。

- Python 完整累计回归：1542 通过、6 PostgreSQL 跳过、0 失败/错误。
- 定向 82 项、独立还原后同组 82 项通过；前端逻辑 111 项、JavaScript 语法 44 项通过。
- 新增 44 项 Python 测试，原 DEPTH21 的 1504 项全部保留。DEPTH22 首轮自运营子进程超时失败证据同时保留，累计完整回归原断言通过。
- 库存、报价和支付为隔离模拟。部分旅客售后、其他品类高级履约、14 单元全业务执行、PostgreSQL/Redis/冻结 Node/真实浏览器与母版全量验收仍开放。

[审阅记录](GO_DEPTH23_REVIEW.md) · [当前门禁](CURRENT_BUILD_STATUS.json) · [恢复与接口说明](GO_DEPTH23_START_HERE.md) · [母版核对](MASTER_CLOSURE_REGISTER.json)

[累计源码增量](GO_CP11_DEPTH_23_SHARED_CAPACITY_DELTA_20260908.zip) · [源码与验收合集](GO_CP11_DEPTH23_REVIEW_BUNDLE_20260908.zip) · [SHA256](UPLOAD_SHA256SUMS.txt)

[共享库存源码](source/src/go_hotel/services/vertical_capacity.py) · [改签恢复源码](source/src/go_hotel/services/rail_change_resolution.py) · [全部源码差异](SOURCE_DIFF.patch) · [完整回归](full_regression.xml) · [独立还原验收](restored_regression.xml)

还原时使用本目录累计增量、DEPTH17 WORK 与锁定 CP11 父包。累计包含 DEPTH18–22，无需逐一叠加。库存存量缺失保持待核对；本包不迁移香港运行环境。
