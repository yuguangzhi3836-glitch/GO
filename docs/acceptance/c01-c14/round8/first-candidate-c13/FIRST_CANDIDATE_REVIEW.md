# C13 Round 8：首冻结候选独立复验

结论：**FAIL_SCOPED_BUSINESS_DAY**。55 项有限检查实际执行，50 PASS / 5 FAIL / 0 ERROR / 0 SKIP。5 个失败集中为 3 个必须修复的问题；不能授予本候选完整营业日验收通过。

绑定：product `9a298cb3a093c4e75a043bdb2a4da14594fafd3c`；application tree `ba334dadcb8899fa60c352df0410367592bc236b`；Draft PR259 gate `32e40303114008f0db499ae541612276a9fe1b7d`。C13 独立读取 GitHub tree/compare，核对 8 个 application 变更 blob、核对 gate 的相同 app tree，物化 141 个匹配远端的文件。此工作区是局部检出，非完整 application：1402 个远端路径未物化，另 1 个本地运行期 pytest cache 不符已排除。测试只能导入专属冻结目录，未导入开发目录。未改产品。

## 阻断问题

| 问题 | 实际操作与结果 | 必须达到的边界 |
|---|---|---|
| P1：授权额未与资金根核对 | 真实 JWT HTTP 预订、授权、确认 69800 后，故障注入把唯一 AUTHORIZATION movement 改成 69801，intent/binding/order 仍是 69800。日终仍创建 close，状态 OPERATIONAL_SNAPSHOT_RECONCILED、closing_held=69801。 | 根授权金额/币种与授权流水总额、个数及父子结构必须相符，否则 BLOCKED 且不落日结。 |
| P1：归档重放漏验订单源事实 | 先正常归档，再分别只改 reservation.amount_minor、currency、check_out；无合法改期或新增资金事实。三例重放均 HTTP 200 返回旧成功。 | 订单变化须有可信、版本化的业务事实解释；无法证明的源变化拒绝旧成功。不要简单重算当前生命周期，避免次日正常入住/离店/收款破坏前日日结。 |
| P1：打印凭证资金字段矛盾 | 正常履约并 capture 69800、借贷各 69800 后，由真正具备 DUTY_MANAGER 的 JWT 读取 arrival-voucher。HTTP 200 同时显示 payment_state=CONTRACT_CAPTURED_NOT_ALIPAY 与 payment_captured=false。 | 凭证应使用 canonical 模拟业务资金口径，并单独明确真实 PSP 未调用/未对账；不能硬编码 false，也不能把模拟收款冒充银行实收。 |

代码定位：`hosted_business_day.py` 的 64–71 行只核 binding 与 intent、仅检查是否存在 AUTHORIZATION；157–171 行归档复核未包含订单绑定；183–187 行由此接受旧成功。`hosted_frontdesk_uat.py` 120 行硬编码 payment_captured=false。

证据：`independent-records/authorization-amount-mismatch.json`；`archived-order-{amount_minor,currency,check_out}.json`；`captured-arrival-voucher.json`。所有故障注入都发生在隔离数据库，未修改真实资金或用户数据。

## 实际执行与范围

| 本轮执行套件 | PASS | FAIL | 说明 |
|---|---:|---:|---|
| 冻结候选营业日用例，C13 重新执行 | 10 | 0 | 完整短住异常、正常跨夜、缺日历、14 点门禁、房号重叠、日期边界、显式 HOTEL_CONFIRMED 技术规则。 |
| 冻结候选真实 JWT 授权/发布/恢复用例，C13 重新执行 | 25 | 0 | 只读/无酒店范围/角色撤销/会话撤销、跨酒店、发布内容/原图/价格变化失效、maker 自审拒绝、审批失败后恢复、未收费退出、UNKNOWN/入住保护。 |
| C13 自编营业日及反例 | 15 | 5 | 两条 HTTP 正向旅程、源缺失、日结权限、历史 HOLD、父资金预算、经济日期、ledger/account/currency/orphan、自身归档 hash，以及上述 5 失败。 |
| **合计** | **50** | **5** | 固定分母 55，不叠加开发侧 59、Round 7 的 37 或远端 CI。 |

来源为独立 pytest 执行的 3 份 JUnit。中间一版 voucher 探针用未获前台角色的 maker 被正确拒绝，已纠正为 DUTY_MANAGER 后整套 20 项重新执行；该探针选择错误没有计为产品失败或额外测试项。

## 可追溯营业日记录

1. `normal-overnight.json`：D 日 08 时下单/授权/确认，14 时入住，D 日结束封存；D+1 日 11 时离店、履约收款，前日日结逐字段相同。D 日期末 held=69800；D+1 期初 held=69800、收款=69800、期末 held=0、净收款=69800、借贷差=0。D 日库存可用 249/250，D+1 为 250/250。
2. `same-day-short-stay.json`：一单 69800 在同一受控时刻下单/确认/免费取消，授权原额释放；另单当日 14 时入住、18 时早离，按隔离协议先履约收款 69800，再由不同审批人批准服务退款 9800。合计 AUTH=139600、CAPTURE=69800、RELEASE=69800、REFUND=9800、NET=60000、held=0；库存可用 249/250。此早离分支是“已订整晚收款，再另行批准服务退款”的隔离测试，未核实实店提前离店计价政策。
3. `confirmed-rates-pools.json`：独立查询五池各 50，总 250；仅圆梦大床、圆梦双床两个池各有 69800/79800/89800 三价，餐别映射同物理池；另外三池无报价/无销售 offer。全六个 offer 的 availability 可售。

这些记录包含匿名合成订单、资金根、movement、双分录、两日日结及库存明细。HTTP 使用真实签名 JWT 与持久 AuthSession，FastAPI 路由无 dependency override；初始身份、酒店内容和库存为隔离 fixture，营业日由显式受控时钟驱动。房号为合成自由引用，**没有**证明实店房间注册表、房间与房型映射、199 张媒体来源完整性或酒店真实经营授权。通知测试只证明持久化/排队，未证明客户实际收到。

## 已确认的拒绝与恢复边界

缺资金根、缺授权流水、binding 金额不同、缺任一物理池当日日历均 BLOCKED；其他根的 held 正数不能抵消单根超收 1 分；ledger 币种、账户和孤儿交易异常阻断。跨午夜的分录时间差按 movement 的经济日期归属，不制造假日差。当日只能 PREVIEW，历史首结无法证明状态时 HOLD；归档 payload 自身被改则 409。正常次日收款可重放前日已归档结果。这些通过不抵消三项 P1。

## 商业与证据边界

`MATERIAL_PROVENANCE.json` 保留来源区别：用户 2026-08-18 原话是“30分钟内免费取消”，没有写起算事件；“酒店确认后”来自当时助手复述，检索未证明用户明确确认。因此 HOTEL_CONFIRMED 只是冻结测试的显式技术配置，不是实店已确认商业规则。实际非边界旅程的下单、授权、确认、取消同一受控时刻发生，位于三种可能锚点的 30 分钟之内；跨 14 点单测仅证明指定锚点技术行为。未知起点、199 原图来源、未知三房型价格仍 HOLD。

本报告只证明隔离 SQLite/HTTP 的有限结果。尚未独立核查 Round 8 远端 PostgreSQL 日结及并发证据；没有真实 PSP 调用、真实酒店运营、合并或部署。新修复必须另冻结源码并重新绑定、执行相关完整旅程与反例，不将本轮通过自动转移。
