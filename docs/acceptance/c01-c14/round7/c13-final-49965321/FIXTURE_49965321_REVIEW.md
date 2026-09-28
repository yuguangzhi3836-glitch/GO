# C13 旧测试前置条件适配与新候选限定复验

固定产品：`49965321a151fe082cbc6381341a5beb6edc93e7`。
Application tree：`6020fbe993a07728f5b7a1a0e2b5ed6fb386a72c`。

结论：**7份测试改动符合新授权/发布契约，没有发现用放松真实门禁或测试替身取绿。新SHA的29项限定独立复验通过。** 完整新候选全量CI/PG结果仍需补齐，不签发全系统/生产C13 PASS。

## 独立来源核验

C13直接读取GitHub新旧完整递归tree，确认相较 `f8126454…` 仅7个测试文件改变，没有业务代码或0139迁移变化。C13另外按旧SHA读取7份原始测试逐行比较。136个新候选物化文件逐项Git blob和SHA256匹配，见 `INDEPENDENT_FIXTURE_REMOTE_BINDING.json` 及 `CANDIDATE_49965321.json`。

## 7份测试差异审查

| 文件 | 改动及判断 |
|---|---|
| test_depth10_disruption_api.py | 给真实登录管理身份增加酒店专属工程授权；消费者/供应商拒绝、过期审核等原断言保留；没有替换权限依赖。 |
| test_hosted_direct_inventory_matrix.py | 库存测试预先执行legacy_publication，经过实际内容/媒体/独立审批服务，未mock发布门禁；库存扣减、变体共享及取消恢复断言保留。 |
| test_v70_r4_c01_unknown_episode.py | 新增有效管理员但无酒店scope时403的断言，再显式授酒店scope进入既有合法UNKNOWN流程。 |
| test_rc15_aoluguya_supply_truth.py | 官方供货投影不等于内容/媒体审批，因此page应被门禁阻断；原非测试价格/价格集断言仍从数据库offer核验。原page.payment_available断言因page被拒不再适用，正常发布页面由完整旅程用例覆盖；没有把此供货测试伪装成发布通过。 |
| test_depth48_flight_migration.py | 期望新增表集合准确增加hosted_publication_review；历史数据及拒绝丢失降级断言保留。 |
| test_parent_implementation_code_review_debt_closure.py | Alembic唯一head期望由0138更新0139，历史列及数据断言不变。 |
| test_supplier_import_migration.py | head期望更新0139；降级已空0139后，0138因有授权历史拒绝丢失，版本落点应为0138；数据保留和清空后可逆断言仍在。 |

`legacy_publication` 仅用于测试工程隔离准备，执行真实服务与独立maker/checker；未出现在产品API，未用其充当真实酒店授权证据。

## 新SHA上的实际独立执行

C13在独立进程、固定 `candidate-49965321/` 来源及隔离SQLite中实际执行：

- 自编18项真实JWT/HTTP完整旅程、授权拒绝、媒体自审拒绝、失败恢复、库存/Trips/通知一致性及租车差额探针。仅将脚本的候选来源目录由旧快照改为新快照；断言与逻辑未改变，逐例检查导入来源。
- 8项迁移专项：6个SQLite真实DDL用例和2个PG反射类型检查（后两项不是真实PG迁移）。
- 3项库存矩阵回归：真实工程发布前置下共享房型/价变体库存与恢复。

**29 PASS，0失败/错误/跳过**。证据：`fixture-49965321-junit.xml`、`fixture-49965321-test.log`、`test_independent_49965321.py`。

没有在本地运行完整main、全库、浏览器或物理真机。其余6份改动测试本轮作逐行审查，未声称全部在局部检出运行；完整远端回归负责验证其执行结果。

## 与此前证据关系

旧SHA `8f66ebfc…` 的79项和 `f8126454…` 的8项原始证据保留；不把它们相加冒称新SHA总通过数。新SHA准确报告本次29项实际执行，未执行范围只能按源码无变化评估影响。

此前首轮远端4分片统计据主代理纠正为3201 passed/10 failed/7 skipped；本意见未重读那些完整原始JUnit，不把该合计当作新候选结果。失败历史应保留，最终以新gate同head远端原始结果为准。

固定分母仍305义务/1009场景。真实酒店委托和媒体权利HOLD，Draft不合并、不部署。此意见不替代C14规则审查或人类部署决定。
