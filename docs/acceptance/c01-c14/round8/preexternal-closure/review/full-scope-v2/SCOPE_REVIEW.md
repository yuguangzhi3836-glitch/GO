# C13 R8-03/R8-16增量及18组范围审核

**PASS_SCOPED_SQLITE（新增28节点）；完整18组仍HOLD，待精确新冻结候选PG及全量CI。**

独立执行：test_c01_money_authority_matrix.py 16节点全部通过（authority-independent.xml/log）；独立test_c13_currency_day_scope.py最终4节点全部通过（currency-final.xml/log）。没有将首轮失败或试验fixture错误计入通过数；原currency-before.xml/log保留实际发现的availability顶层CNY错误和可售USD→checkout仅CNY不一致。中间失败包括phone调用者不具RESERVATIONS资格、历史fixture时钟使用实时时钟；这些构造错误已经明确纠正，不能包装成产品缺陷。

币种修复仍保持顾客CheckoutConfirmation Literal[CNY]及首试点页面资格，没有激活USD顾客支付或其他酒店顾客支付。新断言实际覆盖单项USD依旧呈现USD，但混合items顶层currency=None/currencies=[CNY,USD]，USD不可售；普通/managed页面、普通/治理电话（实际GO_ORDER_OPS+RESERVATIONS）及legacy reserve均报特定币种错误，库存/订单/夜/通知/事件不变。

日结正向fixture分清来源：本试点CNY订单走真实JWT顾客HTTP预订与checkout；USD及其他酒店是显式隔离内部历史obligation，原始reservation/stay/night/authorization在未有资金事实前构造，调用hosted_money.ensure_authorization规则化服务生成source decision/root/binding/intent/authorization movement，再通过实际HTTP入住、离店、履约和capture形成双分录。未篡改已确认CNY资金行，没有真实PSP调用。

查询证明同酒店按CNY/USD分桶不折算，外酒店资金不串入，旧订单不串入当日预订/交易/流水但历史opening net正确保留。另两条全部顾客CNY HTTP正向证明：今日预订未来入住，今日授权/预订可见、今日库存不减、仅未来库存减1且capture0；旧日capture69800次日独立裁决refund9800，今日借贷各9800、capture0、net=-9800、opening69800/closing60000、退款重试同结果，前日日结逐字段不变。原始工件在artifacts/。

16项权限矩阵源审确认：4操作×只读/真跨酒店root/撤销root/撤销session；每例操作前置真实可执行，拒绝后22类业务表逐字段不变，再同请求合法角色成功。它修补了此前预约入口权限测试不能外推入住/扣款/退款/日结的证据缺口。

18组确切节点列表见18-group-node-map.json及18-GROUP-NODE-MAP.md。不能把邻近分钟边界、返还同id、历史父PASS或workflow名称当完全断言证据。R8-05与R8-07新增8节点已独立源码审核并SQLite复跑全部PASS（boundary-replay-independent.xml/log），精确断言已补齐。当前未发现尚未实现的内部硬缺口；所有18组仍须新冻结候选PG及全量原始JUnit与源码指纹绑定。无全范围100%结论。

测试文件可原样复制到application/tests；若保留独立目录，使用-p tests.conftest加载数据库清理fixture。最终文件哈希及相关两服务/CheckoutConfirmation源码哈希见currency-authority-tested-hashes.json。本审核只写review目录，未修改实现、未部署/合并/接外部。

秒级/重放独立审核：四入口使用合法顾客或实际RESERVATIONS主体；首请求断言一订单/一HELD夜/池49/两QUEUED_NOT_SENT通知，重试及两种改body分别核22表。秒边界先长等1小时再确认，排除误用下单时间，冻结规则与hash、金额、release、cash refund及库存均有实断言；旧quote截止拒绝不写入。无新实际缺陷。SQLite共8 PASS、0失败/错误/跳过；不代表PG并发已验。

最终增量冻结：product `55ea39cd41d39e50abc221e73812ab01fec1c5ce`，application tree `c98e58256d29062a1026bc5ff64f22c99dbac92b`。6份本地源码SHA256及Git blob均独立重算匹配closure-meta.json，独立币种测试与tests副本逐字节相同。完整1556文件tree摘要由执行者提供，未由本审核重下载复算。最终状态 **PENDING_CURRENT_CI**；局部独立28项PASS，等待此候选PG/全量工件，不继承父候选结果。
