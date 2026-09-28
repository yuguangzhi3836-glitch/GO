# Round 8 日结实现第一次静态预审

**不授 PASS；没有执行待修改目录的测试。** 本意见绑定 `day-preview-1/SOURCE.json` 保存的未冻结快照，`hosted_business_day.py` SHA256 为 `52291255000badf67ff3663d1f7828271a56c5be97f43454fcd16aa64c383b7e`。产品仍由主代理实现。

已有改进：日结读取 canonical movement/ledger；分币种统计；现金与授权释放区分；发现逐笔缺失/错额/错科目分录会阻断；未知资金/争议/待退款能进入 blocker；变化后的旧快照拒绝直接重放。这些是静态观察，不是本轮独立运行结论。

## 冻结前必须处理

| ID | 当前具体缺口 | 最小反例/后续探针 |
|---|---|---|
| P1-A | `snapshot:50–72,101–110` 资金 created_at 有期间限制，但 Guest/订单/授权/争议/退款资格取当前状态；期初也按当前 movement.state 回推。 | D已结账，D+1正常入住/离店/退款申请或UNKNOWN发生，D日重放不应拿次日状态重写/阻断原经营快照；首次补结旧日而无法证明原状态必须HOLD。 |
| P1-B | `all_intents` 从 graph movement 反推；没有movement的合法root及其孤儿ledger可能完全不进入scope，captured授权缺graph也可被报0。 | 原真实capture后删除/丢失movement但保留root/binding/ledger，或授权标captured却根缺失；不得出现“0款、无blocker”。根从订单授权+Funding发现，明细从根查询并完整核验。 |
| P1-C | hash的来源只有lifetime movement与ledger；订单金额/币种/日期、root/intent/factbinding和房池关联未完整绑定。 | 同状态下改关键来源不能保持相同关闭证据；但合法D+1改期不能被误当D日篡改，应使用当时冻结事实/新generation，不能比较当前可变订单字段冒充历史。 |
| P1-D | `days` 缺行不报错，只对找到的行做差额校验。 | 本目标5池中删除1池D日ARI，或全部缺失，可出现200/0总量且无INVENTORY_DIFFERENCE；应明确本日应有池清单，缺资料HOLD。 |
| P1-E | 负余额只按整家酒店同币种合计检查；单根资金不守恒可被别根正余额抵消。 | 两订单一根超捕获/超退款，一根保留余额；每笔ledger本身平衡仍不能批准。按root/parent capture先核验，再聚合。 |
| P1-F | movement与ledger分别以各自created_at筛日。原服务创建movement和两条ledger分别调用now。 | 单个原子capture跨本地午夜，可能被拆进两个日形成假缺账/孤儿；同一经济交易必须有统一归属日/时间，且仍检查无合法movement的ledger。 |
| P1-G | close未区分预览和完整日终，当前/未来营业日也可持久化唯一close。 | 当天8:00空/少量业务不能变成当日最终封账；后续正常营业不应只能409。预览ID为空，日终条件满足才固定。 |

并发一致性需要实际PG探针：hotel行锁只串行化参与该锁的路径。reserve会锁hotel，但capture/refund/guest迁移主要锁stay/reservation/authorization；`managed_session` 在PG没有固定多语句快照隔离。多次查询不能自行证明同一时点的经营/资金事实。需要一致DB快照/可证明的共同锁协议与明确截止点，测试close与capture/refund并发；不用SQLite串行结果替代。

## 无通用事件溯源时的最小诚实契约

1. 明确 `Asia/Shanghai` 的 `[D 00:00, D+1 00:00)`；预览的 `as_of` 是实际读取截止点，不能把未来日末写成已经观测到的时间。当天及未来日不产生最终 `daily_close_id`。
2. 完整历史经营日首次封账只接受可信的日末一致快照/检查点，或确实可重建的有时间证据事实。如果可变Guest/订单/库存已跨日更新而没有历史依据，返回 `HOLD_HISTORICAL_STATE_UNPROVABLE`。可以单列可重建的资金发生额，不能据此拼造原入住状态、原库存或整日PASS。
3. 已封账日使用存档业务快照及其自校验hash，不重新取最新Guest/订单/争议状态生成过去。D+1正常新增事实不改变D。
4. 复核已引用的不可变资金/账本/root/binding身份、金额、币种、父子关系、归属时间；删除或篡改属于原日的已引用事实须明确冲突/审查。不要把updated_at等普通后续状态字段混进“不变”的定义。
5. 订单金额/日期可能合法改期，须保存封账时订单事实及对应quote/funding generation。当前r值不能证明旧值；缺历史版本就HOLD，不能靠遗漏日期/金额字段装作历史可证。
6. 晚到的原日资金事实、后续UNKNOWN对既往事实的质疑，须形成单独补正/审查状态；保留旧封账原文，不覆盖成另一个“原日事实”。新增D+1退款正常进入D+1发生额。
7. 每个经济交易与其双边ledger统一归属；先验证逐root/逐parent守恒，再算酒店/币种期初+发生额=期末。真实PSP结算仍标未执行，不拿模拟净收入当银行结算。

## 当前测试的具体范围限制

保存的 `test_c01_aoluguya_business_day.py` 有真实会话JWT/HTTP、非零698收款/98退款、UNKNOWN解除、独立退款审批、缺1分账本修复和重放，这些路径有价值。

但 fixture 只有1池1价(圆梦大床无早698)，不是5池完整价格矩阵。时钟为D日8:00下单、14:00入住、18:00离店；房晚仍是D到D+1，并最终断言可用49。这可以作为限定提前离店/短住链，不能冒充“次日12:00正常离店且完整营业日封账”。应保留这个范围说明，并补跨日正常住客、旧订单当日离店/退款、期初期末与另酒店对照。

当前30分钟anchor已显式设HOTEL_CONFIRMED，这一修正正确；但其他零费/信用/变更规则来自隔离RULES，测试仅覆盖窗口内取消，不证明窗口外商业政策。使用的合成媒体已明确是fixture，不能结论成真实敖麓谷雅媒体、199张来源或实际发布资格完成。

下一步：等待主代理修订并固定候选。C13只在固定SHA/源码清单上运行 `INDEPENDENT_ACCEPTANCE_PLAN.md` 的有限旅程与反例；此前的14项开发侧结果不计作C13独立验收。
