# C13 房间登记写API独立审核：PASS_SCOPED_SQLITE

结论只覆盖下列固定本地源码与15项实际HTTP/SQLite检查。**不代表PostgreSQL并发已验证，不代表全范围100%，不代表外部支付已就绪。** 初始CAS缓存缺陷已反馈并修复；原失败证据保留。

## 实际独立运行

| 套件 | tests | failures/errors/skips | 证据 |
|---|---:|---|---|
| C13自编独立HTTP反向测试 | 7 | 0/0/0 | http.xml、http.log、test_independent_registry_http.py |
| 开发侧现有房间登记旅程，C13重新执行 | 8 | 0/0/0 | journey.xml、journey.log |

独立七项使用真实JWT、持久AuthSession与实际API，无dependency override。ARRIVED和真正check_in后的IN_HOUSE各执行移除/改BLOCKED四例，均拒绝且登记版本/内容、登记审计、住客状态/房号及住客事件完全不变。另一酒店合法root先通过其酒店scoped(root_only)权限检查，再尝试目标酒店写入，正确拒绝；撤销root与撤销session后旧JWT也拒绝且无业务写入。

独立目录运行命令：`PYTHONPATH=src:tests:review/room-registry-v2 APP_ENV=test python -m pytest -p review_fixture_plugin review/room-registry-v2/test_independent_registry_http.py -q --junitxml=review/room-registry-v2/http.xml`。review_fixture_plugin.py是固定gate application/tests/conftest.py原样副本，仅用于将应用数据库清理fixture加载至独立目录；没有同时加载第二份conftest。实施八项使用正常tests/conftest.py：`PYTHONPATH=src:tests APP_ENV=test python -m pytest tests/test_c01_room_registry_journey.py -q --junitxml=review/room-registry-v2/journey.xml`。

八项包含wrong-pool零事件/分配、登记撤销后入住拒绝、49真实订单消耗50池后跨餐别最后一间竞争、Unicode等价房号冲突、入住重验占用、版本CAS、非酒店确认来源限制/占用保护、并发更新一成功一冲突且只一审计。均为隔离合成库存与资金。

## 初始缺陷及修复判断

初始服务先加载Pool ORM probe，再等待hotel行锁，随后普通锁查询复用缓存对象，存在CAS读取旧version风险。两个真实Session的独立缓存层反例1 FAIL保留于cas.xml/log与test_identity_map_cas.py；该反例描述旧查询，不应再当现源码失败测试执行。

修复后先读Pool.hosted_hotel_id标量，不预载pool对象；锁后Pool查询显式populate_existing=True，validate_room的锁查询也刷新。源审确认解决所发现缓存入口，SQLite服务并发八项中的同version测试通过。**实际PG仍须新候选CI的同version并发、原始audit计数和最终version验证。** SQLite全库锁不能替代PG酒店锁等待时间线。

## 权限/来源/写入边界

路由hosted_admin按room_registry动作要求admin:rules，并从pool_id数据库归属解析酒店；服务内root_only权限二次校验。提交者不能靠body伪造酒店、registered_by、version或HOTEL_CONFIRMED，登记只允许isolated://来源且酒店为SIMULATION。被拒绝的真实确认状态不产生新事实。审计与登记在同一事务提交。

占用保护覆盖本酒店ARRIVED/IN_HOUSE的规范化房号，拒绝从原登记删除或停用有效占用；全酒店跨池重复房号拒绝逻辑保留。占用校验与登记修改按同一酒店锁协调。注册API没有借助无variant或未登记fallback放行。

## 仍需的门禁

新固定候选PG并发、全量旧fixture兼容、20项独立营业日以及其余完整范围断言仍须独立绑定当前工件；本报告不移植7c006399旧候选PASS。若此后源码继续变化，须重新冻结并核对。未改实施源码或实施tests；所有审核写入都在review/room-registry-v2。没有GitHub写入、真实PSP、商户密钥、香港、部署或合并。

## 审核后源码SHA256

- `src/go_hotel/services/hosted_room_registry.py`: `81abc7fab8af87c6f8ab23b6fddb584b2206cec585f26f573f98d843e88b0746`
- `src/go_hotel/services/guest_stay_fulfillment.py`: `d18472f924c1be5e7be41cc6c3f2b90ae017970c1d8ed47a29b56adfcafaa223`
- `src/go_hotel/api/routes/hosted_direct_booking.py`: `fef4e357d04e9ff97c72e19bc3ab993acf53c087a4f784d5600c3d3095ffb23b`
- `src/go_hotel/services/hosted_operation_authority.py`: `127554f332f0422dd25d428dd7aaf58d561c9f4ec3afb784e4ba93756dc47cfb`
- `tests/test_c01_room_registry_journey.py`: `3f6c0b79c975eebb738de1702418d356fecea4b468c39c318de64db55d4785c8`
- `review/room-registry-v2/test_independent_registry_http.py`: `33f3f05b1bfaa97c3c0d5a0056440cd799a6016c7f5185eb5ee6de1962addcd0`
