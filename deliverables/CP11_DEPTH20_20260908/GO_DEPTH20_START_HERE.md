# GO DEPTH20 工程审阅入口

**HOLD；尚未全面完工，未部署。** 本轮继续对照 V7 母版，绑定铁路与门票的实际人数、总价和预订凭证，接通客户确认与铁路多人出票、改签补款后的原路退款。

## 恢复完整工程副本

本轮是相对 DEPTH17 WORK 的累计增量，已包含 DEPTH18 和 DEPTH19，无需另外叠加两者。

1. 使用已恢复的原始父包，SHA256：`8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb`。
2. 从同仓库 `deliverables/CP11_DEPTH17_20260908/` 获取 WORK 分卷并按清单合并；完整 SHA256：`1b1af66dfdb71f350d5aba81544c90c95e51b7f54a380a10e3bdec6778032d79`。
3. 核对本轮 `GO_DEPTH20_SHA256SUMS.txt`，使用一处不存在的新目录恢复：

```bash
python3 assemble_depth20_review.py --parent /path/to/GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip --base-work /path/to/GO_CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION_WORK_20260908.zip --delta /path/to/GO_CP11_DEPTH_20_PARTY_PREBOOK_TICKET_CONTRACT_DELTA_20260908.zip --output /new/path/go-depth20
```

恢复器逐文件校验，不覆盖已有目录。进入恢复目录：

```bash
./gate_runtime/python/bin/python scripts/verify_delivery.py
PYTHONPATH=src ./gate_runtime/python/bin/python -m pytest
./gate_runtime/python/bin/python scripts/run_local_demo.py --check --data-dir /tmp/go-depth20-demo
```

新迁移 `0127_vertical_prebook_contract` 保留历史，不为旧报价伪造条款；存在新报价或消费证据时禁止直接降级。正式环境仍按原有备份、审批及发布门禁处理，本轮没有部署。

## 客户预订与接口

- 铁路预订核验新增 `quantity`（1 至 9 的整数）。门票预订核验保留票种、日期、人数及服务器支持的 `session_time`。
- 两类下单均使用 `prebook_id`，人数与报价一致，个人库引用必须是实际不同的出行人。登录后取得的报价只属于该账号；未登录浏览取得的报价只能被一位消费者领取。
- 相同账号、报价和请求可以返回同一订单；改换人数、资料或账号不能复用。换票种或改场次应重新核验报价。
- 铁路出票及改签回执的票号数量必须与人数相同且不重复。原出票回执不可重放为不同票号。已付改签手续费不再次退还。
- 页面先明确人数与场次，选择个人库旅行者，再确认含税总价和退改规则。测试付款取消后保留原订单入口，不自动冒用昵称。

## 边界

库存为工程模拟数量观察，尚未形成跨报价共享库存持有/释放。年龄与证件的独立认证、铁路真实改签报价、改签/退款并发和人工核对仍需继续。模拟报价、场次和票据不能用于真实出行。PostgreSQL、真实供应商/支付、Redis、跨设备视觉和冻结 Node 22 均未通过最终验收。

详见 `acceptance/GO_DEPTH20_REVIEW.md` 与 `verification/current_build/depth20/CURRENT_BUILD_STATUS.json`。测试数量不折算全面完成百分比。
