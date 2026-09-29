# C13 迁移修复候选差异绑定意见

新产品提交：`f8126454999e51d4eb1a68e5e638e804df4bbbfa`。
新 application tree：`e7483f86abea4eed3cf3009890fcb0ba569a2bfb`。

结论：**本次迁移差异的限定本地用例通过；完整迁移链和真实PostgreSQL结果仍待新候选远端CI。** 先前业务79项保留为旧SHA上的未受影响实现证据，不能宣称这79项在新SHA重新执行。

## 独立差异核验

C13直接通过GitHub连接器读取新旧提交完整递归tree（未截断），验证application差异精确只有：

1. `application/alembic/versions/0139_hosted_publication_review.py`
2. `application/tests/test_depth25_migration_history.py`

真实业务服务、路由、模型及先前79项所用旅程/拒绝/恢复测试均未改变。新候选局部检出130文件逐一对照GitHub blob和本地SHA256，零不符。远端核验材料：`INDEPENDENT_REPAIR_REMOTE_BINDING.json`；本地清单：`CANDIDATE_f8126454.json`。

## 新SHA上的实际独立执行

C13在 `candidate-f8126454/` 固定快照重新执行8项迁移专项：**8 PASS、0失败/错误/跳过**。未执行的7项完整历史/其他迁移用例按 `-k hosted_publication` 排除，不能称全链通过。

- 6项真实SQLite隔离DDL用例：无media表不补造；历史行保留且来源字段NULL；空证据可降级；有媒体来源/发布审核记录拒绝降级；current metadata提前存在匹配schema可接受；错误列类型拒绝。
- 2项PostgreSQL反射类型兼容用例：含时区TIMESTAMP接受；无时区TIMESTAMP拒绝。它们测试PG类型检查函数，**不等于在PG数据库执行迁移**。

证据：`repair-f8126454-junit.xml`、`repair-f8126454-test.log`。

## 对先前业务结论的有限影响评估

旧产品 `8f66ebfc…` 的79项独立HTTP/SQLite业务结果、原始JUnit、预审FAIL和最终限定报告全部保留。远端树差异证实本次未修改其业务实现，因此这些证据仍支持“授权、门禁、执行恢复、补偿逻辑未在迁移修复中再次变动”。

迁移本身决定真实数据库能否进入这些业务前提，旧业务测试使用metadata建表，不能证明修复后全链升级正确。因此当前不给新候选整体C13 PASS；待同候选fresh/history完整迁移及PG CI实际结果后，才可补齐这一层。没有把79与8相加后宣称87项同SHA通过，没有转移C14/真实权利/部署结论。

固定清单仍为305义务/1009场景。真实酒店/媒体权利保持HOLD，Draft不合并、不部署。AI独立意见无需额外真人/密码学签名。
