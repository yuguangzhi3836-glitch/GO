# C13 PostgreSQL状态宽度缺陷补充审查

源基线：固定 `49965321a151fe082cbc6381341a5beb6edc93e7` 局部物化源码。主代理报告真实PG已因订单42字符和审批26字符超列宽失败；C13本文件是独立静态扩展检查，不伪称已执行PG。

C13对90个已物化Python源文件做保守AST检查，匹配322个model String字段与构造/可判定局部赋值的常量；共发现5个字段、7个写入位置。人工逐项核实如下：

| 表/字段 | 当前长度 | 实际写入常量及长度 | 状态 |
|---|---:|---|---|
| hosted_direct_reservation.reservation_state | 40 | HOTEL_CONFIRMED_AWAITING_ALIPAY_ONBOARDING，42 | 主代理PG已复现；本地3处写入同常量 |
| hosted_action_approval.state | 24 | APPROVED_PENDING_EXECUTION，26 | 主代理PG已复现 |
| alipay_credential_binding.state | 32 | REFERENCE_BOUND_NOT_EXTERNALLY_VERIFIED，39 | C13独立静态确认，未执行PG |
| alipay_reconciliation.decision | 32 | CONTRACT_ONLY_NOT_EXTERNAL_RECONCILED，37 | C13独立静态确认，未执行PG |
| omnichannel_merchant_binding.state | 24 | REFERENCE_BOUND_NOT_CERTIFIED，29 | C13独立静态确认，未执行PG |

新增三处分别为 `alipay_safeguarded_settlement.py:38,152` 与 `omnichannel_payment.py:41`。它们登记引用或模拟对账，无需真实密钥、外部PSP才能触达；本审查未执行上述外部操作。

建议维持原业务状态含义，为上述5列定向扩至64；metadata与历史迁移同步。迁移已存在64时验证schema而非再次冲突；原表不存在不凭当前metadata补造。downgrade必须先检查全部5列的实际最大长度及媒体/发布来源历史，再执行任何DDL，避免部分缩列或丢失证据。SQLite batch保持原索引/唯一约束。

静态扫描不覆盖计算生成状态、用户输入值、未物化文件或真实数据库schema drift；不能据此声称全库不存在其他字段宽度风险。修复后仍需固定新SHA、定向DDL/旅程用例和真实PGCI证明。先前SQLite通过不能覆盖VARCHAR长度行为。

原始清单：`STATE_WIDTH_SCAN.json`；可重复扫描脚本：`check_state_widths.py`。
