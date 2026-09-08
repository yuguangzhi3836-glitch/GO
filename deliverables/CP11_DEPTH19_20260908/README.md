# GO DEPTH19 · 签名值机与接送恢复

**工程候选：HOLD，尚未全面完工或部署。** 本目录已包含 DEPTH18 之后的值机与接送修订；累计增量直接应用于 DEPTH17 WORK。

- 完整回归 1433 通过、6 PostgreSQL 跳过，0 失败/错误。
- 新增后端 63 项；前端逻辑 88 项、JavaScript 语法 43 项通过。
- 独立恢复副本 122 项通过，隔离车队 CLI 首批确认、后续不重发及生产阻断实测通过。
- 值机按当前航段、旅行者和客票验签；无事实不生成官方状态。
- 航班接送精确绑定日期/机场，规则由服务器保存；只有已验证延误触发额外保护等待。建议时间与已确认时间分开，进程终止后查询恢复。

[审阅记录](GO_DEPTH19_REVIEW.md) · [当前状态](CURRENT_BUILD_STATUS.json) · [恢复说明](GO_DEPTH19_START_HERE.md) · [源码差异](SOURCE_DIFF.patch)

[完整回归](full_regression.xml) · [恢复副本](restored_regression.xml) · [前端证据](frontend_logic.xml) · [隔离处理器实测](restored_worker_cli.json)

[母版重点需求登记](MASTER_CLOSURE_REGISTER.json) · [完整母版源段落追溯](../CP11_DEPTH18_20260908/MASTER_V7_PARAGRAPH_TRACE.json)

## 恢复

使用本目录 `GO_CP11_DEPTH_19_SIGNED_TRAVEL_FLEET_RECOVERY_DELTA_20260908.zip`、[DEPTH17 WORK 分卷](../CP11_DEPTH17_20260908/README.md)和此前恢复的原始父包。先核对 [SHA256](GO_DEPTH19_SHA256SUMS.txt)，再运行 `assemble_depth19_review.py`，完整命令见恢复说明。无需另外叠加 DEPTH18。

## 后续工作

GO Trips / 出发前值机入口、司机 ETA / 等待超时结算和人工核对闭环仍需深化。铁路人数价格和 prebook 复用、门票人数场次与预订凭证的缺口已在隔离待支付订单中复现，见 [下一轮闭环约束](RAIL_ATTRACTION_NEXT_CLOSURE_CONTRACT.md)。这些缺口尚未关闭。

尚未完成六品类全部高级流程、14 细胞业务自动执行、完整母版需求验收、跨设备视觉、真实供应商和生产数据库验收。测试数量不折算为系统完成百分比。
