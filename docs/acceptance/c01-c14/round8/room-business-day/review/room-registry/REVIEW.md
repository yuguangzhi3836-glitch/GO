# C13 房间登记修复独立审核

结论：**PASS_SCOPED_VALIDATOR_AND_OCCUPANCY_HELPER；完整服务/HTTP/PostgreSQL待当前候选CI**。审核期间发现并反馈的规范化缺陷已经在本地源码修复；没有对尚未运行的路线或正在开发的登记管理入口给出PASS。

## 实际证据

- 最初独立复跑tests/test_hosted_room_registry.py：14 passed。
- 独立发现：registry用NFKC+casefold比较，原assign_room查询用SQL lower。房号登记由ROOM-101改为全角等价ＲＯＯＭ－１０１后，真实validator接受同一身份，持久IN_HOUSE旧房号却被原SQL谓词漏查。review/room-registry/test_independent_normalization.py记录1 FAIL，日志/JUnit保留。该探针验证真实数据库谓词，未声称完整HTTP双分配已运行。
- 执行者修复为assert_room_unoccupied统一normalized_reference，在assign_room/check_in均调用；绑定事件增加normalized_room_reference。
- 对修复后的**原函数AST**进行独立执行，连接真实SQLite表：同酒店全角等价房号冲突拒绝；另一酒店同编号允许；同酒店不同房号允许。3 passed，加14项validator共17 passed，见fix-helper.xml/log。AST提取仅绕开本地缺失alipay_safeguarded_settlement等全服务依赖，没有重写函数业务逻辑；它不是完整路由/事务/并发验证。

## 源码判断

严格offer→variant→本酒店pool、已持有night→day pool、登记来源状态及ACTIVE校验已接入。无variant/登记、错误酒店/池、重复归属及模拟资料用于非SIMULATION酒店均拒绝。assign/check_in均在hotel_context取得酒店行锁后校验，支持登记撤销后的再次核验。

本地新增HTTP文件含错误池零写入、登记撤销后入住拒绝、49真实订单消耗50池后跨餐别最后1间并发，方向与原矩阵相符，但本审核尚未运行。完整服务导入已确认受缺少alipay_safeguarded_settlement依赖阻断，不能用helper测试代替。

## Fixture与兼容性

已查看register_isolated_rooms显式将酒店标记SIMULATION，仅测试环境可用；已有variant则取对应pool，没有variant的旧fixture会显式补映射。严格产品服务没有无variant放行。business fixture登记四个已知合成房号；depth06订单fixture登记SIM-101供depth07/08/09/48继承；两旧stay/dispute fixture登记room://2401、room://2501及room://1。

注意helper覆盖目标pool整份登记并把version置1，适用于一次性隔离初始化，不能复用为实际管理入口或中途增量更新。旧fixture补variant发生在旧式reserve后，可能改变后续依据offer判断资金/库存的分支；必须用完整旧套件回归确认，当前局部单测无法证明兼容。严禁为修测试重新引入未登记放行。

旧20项独立day复制版本已与旧固定源码diff：仅docstring/import、SOURCE、ART及环境scope标签变化，业务断言保留。SOURCE现绑定当前application，ART可指定工件目录，适合当前CI重新执行，不移植旧结果。

## 必须等待的当前候选证据

完整HTTP入住/分房/撤销、规范化表示变化冲突、跨酒店同房编号与并发分房；49→50订单跨餐别竞争；20项独立营业日原始记录；14项validator在实际PG；相关旧stay/退款/信用/改期全量回归。若新增受控登记写入口，还须单独验证权限/酒店范围、版本CAS、错误来源拒绝及更新对已入住/已分房的约束。

本次检查的文件快照与SHA256在reviewed-source/与source-hashes-after-normalization-fix.json。后续实现若继续变化，需要重新冻结及增量审核。未改实现、未接外部支付、未写GitHub、未部署/合并。
