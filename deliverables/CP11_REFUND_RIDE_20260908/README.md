# GO 退款确认与接送恢复

**本轮源码与最终测试证据已分别保全；系统仍为 HOLD，尚未全面完工或部署。** 累计源码包含 DEPTH18—23 及铁路、门票、接送退款确认和接送资金恢复。

- 完整 Python 回归：**1,574 通过、6 PostgreSQL 跳过、0 失败/错误**；32 项新增用例包含其中。
- 前端逻辑：**134 项通过**，包含 11 项新增移动端控制逻辑；原生构建、真机与视觉验收仍待完成。
- 直接从本目录源码包恢复的副本：**160 项后端专项、134 项前端逻辑通过**，1,339 个冻结文件全部匹配。
- 接送退款先持久保存申请并占用订单，防止同时上车、改时或未核清的车队动作；丢失回执和进程退出后恢复原申请。
- 网页及移动端三条退款入口绑定当前报价，重新读取订单和退款记录后才能显示完成。

[审阅记录](GO_REFUND_RIDE_REVIEW.md) · [状态与未完成项](CURRENT_BUILD_STATUS.json) · [母版对照](MASTER_CLOSURE_REGISTER.json) · [源码差异](SOURCE_DIFF.patch)

[完整回归](full_regression.xml) · [恢复复测](restored_regression.xml) · [恢复后的前端测试](restored_frontend_logic.xml) · [源码与最终证据对应关系](SAVED_DELIVERY.json)

## 已保存的文件与恢复

[parts](parts/) 中的八卷构成完整累计源码增量，合并命令：

```sh
python join_refund_ride_parts.py
```

恢复出的 ZIP 为 7,614,559 字节，SHA256：

`1afc010d364b3dcdbd50c201fa18571c50d25504512fef89bfc3dcc4928535d2`

再按 [恢复说明](GO_REFUND_RIDE_START_HERE.md)，使用原始 CP11 父包与 [DEPTH17 WORK](../CP11_DEPTH17_20260908/README.md) 组装；无需逐个叠加 18—23。源码包内的阶段性状态早于最终回归；**最终测试结果以本目录单独保存的报告为准**，两者源码指纹完全一致。原检查点保留在 [checkpoints](../../checkpoints/CP11_REFUND_RIDE_20260908/README.md)。

工作区先发生目录丢失，后整个执行环境断连。含全部最终报告的另一个本地封包 `f300298c…e9b465` 完成过校验，但未完成上传；它的 [本地校验记录](local_seal_before_disconnect/SEALED_RESTORATION.json) 仅为历史实测证据，**不是已保存的 ZIP**。本目录采用已完整保存的同源码恢复包及单独的最终报告，避免依赖失联工作区。

最后一次恢复使用此前逐项验证的 1,675 个基线文件；未重新读取原始父包 ZIP。见 [恢复源码核对](restored_source_equivalence.json) 和 [中断记录](workspace_interruption.json)。

真实供应商取消与银行到账、机票/租车确认升级、部分退改、接送取消时限合同、六业务全部高级流程、14 个自运营业务单元、PostgreSQL/Redis、原生构建、跨设备视觉及完整母版验收仍待推进。测试数量不折算系统完成度。
