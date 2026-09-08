# GO DEPTH20 · 人数、报价与出票约束

**工程候选：HOLD，尚未全面完工或部署。** 本轮相对 DEPTH17 WORK 累计封装，包含 DEPTH18 和 DEPTH19。

- 完整回归 1481 通过、6 PostgreSQL 跳过，0 失败/错误；48 项本轮后端用例包含其中。
- 前端逻辑 99 项、JavaScript 语法 44 项通过；独立恢复副本 140 项通过。
- 1,003 个冻结源文件与独立恢复副本逐个指纹一致；最终 1,775 个交付结果文件校验通过。
- 铁路与门票绑定实际人数、单价、含税总价和不可复用的报价；登录报价归属于当前账户。
- 客户明确选择旅行者、日期/场次和总价；取消确认不创建订单；支付取消后可以回到已有订单。
- 铁路出票必须有与人数一致的不同票号，改签按人数计算并保留既有条款；改签后退款涵盖原票款及补款的原支付来源。

[审阅记录](GO_DEPTH20_REVIEW.md) · [当前状态](CURRENT_BUILD_STATUS.json) · [恢复说明](GO_DEPTH20_START_HERE.md) · [源码差异](SOURCE_DIFF.patch)

[完整回归](full_regression.xml) · [恢复复测](restored_regression.xml) · [前端逻辑](frontend_logic.xml) · [恢复校验](GO_DEPTH20_SEALED_RESTORATION.json)

[母版重点需求登记](MASTER_CLOSURE_REGISTER.json) · [母版全部源段落索引](../CP11_DEPTH18_20260908/MASTER_V7_PARAGRAPH_TRACE.json)

## 恢复

使用本目录 `GO_CP11_DEPTH_20_PARTY_PREBOOK_TICKET_CONTRACT_DELTA_20260908.zip`、[DEPTH17 WORK 分卷](../CP11_DEPTH17_20260908/README.md)及此前恢复的原始父包。先核对 [SHA256](GO_DEPTH20_SHA256SUMS.txt)，再按恢复说明运行 `assemble_depth20_review.py`。无需再叠加 DEPTH18 或 DEPTH19。

## 未完成项

库存占用与释放、独立年龄/证件核验、真实铁路改签报价、部分履约/退款及售后竞争仍需深化。门票退款与核销竞争已有确定性复现，详见 [售后审计](next_after_sales_audit.json) 与 [实施边界](DEPTH20_IMPLEMENTATION_BOUNDARY.md)，下一工作副本继续修复，本轮不宣称此问题已关闭。

六业务全部高级流程、14 细胞业务自动执行、完整母版验收、跨设备视觉、真实供应商/支付、PostgreSQL 与 Redis 切换均未全面验收。测试数量不折算系统完成百分比。
