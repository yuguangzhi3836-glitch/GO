# C13 0139 迁移修复增量预审

范围：开发中两文件的独立复制快照 `migration-precheck/`，摘要见其 `SOURCE_PRECHECK.json`。没有把 `8f66ebfc…` 的79项业务PASS转移到新候选，也未改产品。最终新SHA尚未冻结。

## 已执行证据

C13独立运行新增6个SQLite隔离迁移用例，全部PASS、0失败/错误/跳过；7个无关历史用例被 `-k hosted_publication` 明确排除，不称全迁移链通过。JUnit：`migration-precheck-junit.xml`；日志：`migration-precheck.log`。

覆盖：media表缺失时不补造、已有历史media行保留且新增来源字段为NULL、无证据时可逆降级、存在媒体提交来源或发布审核记录时拒绝降级、既有current metadata匹配schema不重复DDL、错误media列类型被拒。

静态判断：处理既有metadata提前建表/列与真实历史稀疏schema的方向合理；不依赖当前metadata补造历史表；新增来源不伪装旧记录已核验；降级保护历史证据合理。

## 待补一个精确兼容性检查

`compatible()` 只比较类型族、String长度、nullable。PostgreSQL的 `TIMESTAMP(timezone=False)` 属于SQLAlchemy DateTime类，因此会被当作期望 `DateTime(timezone=True)`。

C13直接调用该固定快照的兼容检查，输入PG反射类型 `TIMESTAMP(timezone=False)` 和预期含时区 `decided_at`，结果未抛错。这是兼容函数复现，不是实际PostgreSQL数据库运行。

建议在PostgreSQL方言比较DateTime.timezone，不对SQLite无差别应用（SQLite反射会丢失timezone）；对错误既有review表保持fail-closed。补充测试后随新SHA重新绑定。

## 结论边界

六个用例支持局部迁移修复，不能证明完整Alembic fresh/history链或PostgreSQL链已通过。实际PG及全迁移链由同候选远端CI提供，C13需要实读其原始结果后再出差异绑定意见。原最终报告保留，当前只追加本预审。
