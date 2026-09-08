# GO DEPTH21 · 退款恢复

**工程候选：HOLD；尚未全面完工或部署。**

基于 DEPTH20，关闭其已复现的门票退款/核销竞争，接通铁路与门票退款持久化恢复、原扣款核验、并发租约及铁路补款授权中断后的原改签恢复。客户订单页可继续原申请。

- 完整 Python 回归：1498 通过、6 PostgreSQL 跳过、0 失败/错误。
- 定向交易与恢复 42 项、独立还原后同组 42 项通过；前端逻辑 105 项、JavaScript 语法 44 项通过。
- 真实子进程直接退出后恢复；多原扣款只完成第一笔后恢复；重复请求不重复退款；退款期间不能核销或改签。
- 实际浏览器被环境拦截，不能宣布跨设备视觉已验收。共享库存、部分旅客售后、14 单元全部业务自动执行与剩余母版功能仍开放。

[审阅记录](GO_DEPTH21_REVIEW.md) · [当前门禁](CURRENT_BUILD_STATUS.json) · [恢复说明](GO_DEPTH21_START_HERE.md) · [源码差异](SOURCE_DIFF.patch) · [新增恢复服务](source/vertical_refund_recovery.py)

[完整回归](full_regression_final.xml) · [恢复副本](restored_regression.xml) · [故障复现与修复证据](recovery_probe.json) · [前端逻辑](frontend_logic.xml) · [母版核对](MASTER_CLOSURE_REGISTER.json)

恢复时使用本目录的累计 DEPTH21 增量、[DEPTH17 WORK](../CP11_DEPTH17_20260908/README.md)及此前原始 CP11 父包。先核对 [SHA256](GO_DEPTH21_SHA256SUMS.txt)，再用 `assemble_depth21_review.py` 创建全新目录。累计增量包含 DEPTH18–20，无需分别叠加。
