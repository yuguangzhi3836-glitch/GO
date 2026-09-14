# V70-R2-C11-03：两条机票操作的持久恢复

状态：EVIDENCE_READY，4/6 阶段（缺口→任务→测试→Evidence 已具备）；C14、C13 待独立签收。
唯一源码锚点 fef9c748adb77d37ba5d4dc4fa4662eb668303a1。继承候选 a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b，application tree 740d026e3723f5da015342ead3394969629541df。

本轮只启用携带 Idempotency-Key 的 FLIGHT_CHECKOUT 与 FLIGHT_EXECUTE_CHANGE API。通用同步/异步 wrapper、其他 35 个 callback、无 key 的原开发行为保持原合同；它们的提交后异常缺口仍 HOLD，不能由这里的绿色结果抵销。

## 实现

- 请求 claim 先绑定固定 order/quote，再运行服务。claim 中的完整 payload hash 包含 owner、order、payment method 或 quote/confirmation。
- 同一表增加 `RESOURCE:<operation>` / resource ID 的持久资源栅栏，不增加表或迁移。资源栅栏也绑定完整 payload hash，避免不同 HTTP key 同时调用现有支付 bridge。固定锁顺序为请求行→资源行，两行在同事务中使用相同 execution token。
- RUNNING 不按时间自动夺权；明确退出的失败调用转 RECOVERY_REQUIRED，可由相同完整请求恢复。新 key 竞争活动资源进入 WAITING_RESOURCE。完成、失败记录、安全释放全部校验 token；迟到旧执行者不能覆盖新执行者。
- 服务只对已识别的纯验证区域标记 PROVEN_NO_EFFECT。首个订单/报价写提交之前即标记 effects_possible。ValueError 转 HTTPException 不会清除这个边界；查询、完成或失败记录出错均保留持久栅栏。
- 恢复以同 order/quote 查同 payment root，核实 payer/amount/currency、事实绑定、intent/attempt 状态、CONFIRMED 授权/扣款/释放、固定业务 key、父回执。已有本地 simulator pending attempt 只恢复同 attempt；UNKNOWN、external_invoked、错误事实或回执不调用 bridge，不新增 execute、不退款。
- checkout 确认 capture 后只补 PAYMENT_CONFIRMED_AWAITING_SUPPLIER 投影；改签确认授权后只补 PENDING_SUPPLIER / UNKNOWN_EXTERNAL_STATE。没有供应商事实不自动出票；已 release 的改签授权不被新 key 复活。
- 历史已完成 claim 的 resource_id=None：仅在完整原 payload hash 与存储响应中的 order_id 可以证明身份时原样重放，不执行业务。新路径仅把 response_code=200 视为完成；其他持久码为待核查冲突。
- 改签过期比较在该新恢复 helper 内统一 UTC aware/naive 表示，以兼容 PostgreSQL DateTime。未改费用、报价计算、供应商决议或共享 models。

## 原始证据与分母

| 证据 | 实际结果 | 范围/限制 |
| --- | --- | --- |
| red.log / red.xml | 2/2 FAIL | 最初真实支付提交后 callback 抛错导致 claim 丢失；原件保留 |
| red-parent-reverified.* | 2/2 FAIL，exit 1 | 使用只读 PR73 parent 源码重新执行同一原始 probe，独立 SQLite，确认真实基线缺口 |
| green-freeze.* | 100/100 PASS，exit 0 | 40 个新 C11 验收 + 16 个 completion guard + 2 个既有幂等 + 42 个机票业务回归；最终源码 |
| sqlite-process/results.json / junit.xml | 10/10 PASS | 两操作各 5 项正常子进程：同 key、不同 key、提交后恢复、首提交后 SIGKILL、资金提交后 SIGKILL；独立 SQL 读回保留 root/movement/claim |
| postgres-local-gate/execution.json | HOLD，exit 2 | 本地未提供专用 PostgreSQL URL；没有伪装成 PostgreSQL 通过 |

进程 smoke 运行指纹保存在 sqlite-process/execution.json；它先于 C14 最后一项未知 response_code 加固（仅 200 重放）。最终该加固由 green-freeze 100 项覆盖。不能把此 SQLite 进程结果声称为最终源码 PostgreSQL 证明。CI 应对冻结候选运行下述入口并回读其自身源码指纹。

`green-freeze.command.json` / `result.json` 保存完整命令、cwd、独立数据库环境、UTC 时间与退出码；`SOURCE_SHA256.json` 锁定最终 9 个源码/测试/driver 文件。`red_probe_source.py` 保存原始 probe。`setup-error.*` 是早期测试路径错误，0 tests，明确不计入任何验收。

## C11-A01–A20 合同范围

| 项 | 结论 |
| --- | --- |
| A01 | PASS：不存在/非 owner 安全校验，claim 释放，无付款 root |
| A02 | PARTIAL：过期报价安全释放与既有改签合同回归通过；没有宣称每种损坏 plan 的故障注入全部完成 |
| A03–A04 | PASS：绑定前/后提交错误不执行 callback；完整 payload/owner/resource 冲突阻断 |
| A05 | HOLD：写事务失败即便可能回滚也保守保留，未实施“证明数据库回滚后自动安全释放” |
| A06–A07 | PASS：首订单提交、intent、attempt、simulator result、AUTH、CAP 的提交后错误均恢复同身份 |
| A08–A09 | PASS scoped：UNKNOWN/错误付款身份/金额/币种/绑定/回执/父项/外部 attempt 阻断；确认 capture 后只补投影；没有 live provider 证明 |
| A10–A13 | PASS scoped：真实改签授权提交后异常恢复，同 quote/root/key；pending 重放；release 后同/新 key 均不复活 |
| A14 | HOLD：供应商确认/拒绝后的 resolution 提交中断不在本次两 API 修复内 |
| A15 | PASS：complete 提交前失败、提交确认丢失均不重复资金副作用 |
| A16 | SQLite scoped PASS；PostgreSQL HOLD，等待 root 已安排的独立 CI |
| A17 | PARTIAL：两操作两个真实提交边界 SIGKILL 后重启请求均阻断重复；RUNNING 自动恢复仍 HOLD |
| A18 | PASS scoped：分类/资金核验/完成/失败记录异常不释放；失败记录不可用时保持 RUNNING |
| A19 | PASS scoped：完整 payload 与 owner 隔离、旧已完成 claim 回放、不同 key 资源竞争；未执行 Web/mobile 实机 |
| A20 | PASS scoped：原 16 项回归通过；原两个 red 在两 opt-in 下转 green；其他 35 callbacks 仍 HOLD |

## 交给 root 的 PG 入口

文件：application/ci/next_depth/c11_postgres.py；actor：application/ci/next_depth/c11_process_actor.py。

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python ci/next_depth/c11_postgres.py --evidence-dir <artifact-directory>
```

环境变量：GO_C11_RUNTIME_DATABASE_URL（PostgreSQL、loopback、数据库名必须精确 go_c11_isolated）、GO_C11_SOURCE_COMMIT。无 URL/错误目标直接 HOLD；随机 c11_* schema，仅创建/删除自身 schema。独立进程不导入 tests/conftest.py。输入 offer/prebook/order 为显式合成测试行，未通过无关的旧 prebook 日期逻辑，也没有 mock 新 helper 的时间或资金提交。

root 已派的下一执行动作是冻结候选 PG CI → 回读真实日志/源码指纹 → C14 → C13。未完成自动恢复、供应商 resolution 中断、其他 35 callbacks 属后续候选工作，不标成 DONE，也不自签 gates。
