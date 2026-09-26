# C13 第七轮最终独立复验与 PostgreSQL CI 证据审核

**限定范围通过；本次审查范围没有剩余 FAIL。** C13 在新产品上独立执行的数量保持 **37 PASS**，真实 PostgreSQL 结果是 C13 独立读取、校验和审核的远端 CI 证据，不能写成 C13 自行执行 PostgreSQL。

固定产品 `afc142e16c050c0000da5a11a312620387be8f79`；实测 Gate `b2d9f9744dd7d994636caa805e4dc954e278aab9`；application tree `ac23b75a75325091c5a95434238473a5592468a7`。本报告不修改实现、测试配置或 Gate。

## 独立实跑与远端原证据

本地新 SHA 的 37 项：18 项真实 JWT/HTTP 酒店完整工程旅程、授权拒绝、媒体审核、取消/改期故障恢复与租车资金差额；15 项迁移检查；3 项库存矩阵；1 项独立编写的真实模型唯一约束/索引/历史保留检查。数据库为 SQLite，其中 2 项仅检验 PG 反射类型。详细范围及原始 JUnit 见 `WIDTH_afc142e1_REVIEW.md`；不累计旧轮 29/79 等数字。

下表均来自相同 Gate 的原始 CI artifact/JUnit，全部 **0 failure、0 error、0 skip**，各套件不作为去重后的总场景数相加。

| 原始 CI 范围 | 结果 | 证据性质 |
|---|---:|---|
| depth48，job 108339566528 | 空库历史迁移至 0139；6 PASS | PostgreSQL 16.4，完整升级日志及实际并发测试 |
| C09，job 108339566463 | 12 PASS | PostgreSQL 18.4，服务事务、并发、异常退出回滚 |
| C11 宽度迁移 | 7 PASS | PostgreSQL 18.4，5 列历史升级、数据/索引保留、拒绝有损降级 |
| C11 当前业务增量 | 324 PASS | 原 324 个测试节点全部保留 |
| C11 资金集成 | 47 PASS | 独立 PostgreSQL 中的资金测试 |
| C11 outbox | 1 PASS | 两 worker 竞争同一行的真实行锁检查 |
| C11 跨进程恢复 | 12 PASS | checkout/change × 6 场景，原始进程日志和 SQL 对照 |
| C12 有限容量 | 1 PASS，52 笔交易成功 | 并发 1/4/8，分别执行 4/16/32 笔合成 RIDE 事务 |

C11/C12 位于 job `108339566594`，PG run `36218642882` 已完成 SUCCESS；depth48 run 为 `36218642881`。本审核没有把其他工作流的绿灯当作其业务范围的独立验收。

## 旧失败和环境跳过逐项闭合

旧 Gate 的 PostgreSQL 324 项中，7 个失败准确对应：完整发布/预订旅程；审批失败恢复的 missing_ari、after_approval、before_commit 三分支；未收费确认申请取消；UNKNOWN 和 IN_HOUSE 两个禁止无保护退出分支。新 JUnit 中相同 classname/name 全部 PASS，324 节点集合未变。其所在 `test_c01_hosted_operating_journey.py` 新旧文件 SHA256 完全相同，未通过修改这些断言取绿。逐节点证据见 `ci-final/OLD_FAILURE_NODE_MAPPING.json`。

parent 原始结果仍保留 **7 skip**。C13 直接读取三个相关分片的 JUnit：5 个 `test_p0_0101_postgres_race_matrix` 节点，加上 `test_p0_0100_postgres_concurrency::test_order_payment_root_unique_under_postgres_race`，均与 depth48 的 6 个实际 PASS 节点逐一对应；`test_outbox_resilience::test_postgresql_two_workers_claim_one_row_once` 与 C11 outbox 实际 PASS 对应。class/name 及测试源码哈希均一致。这里只说明这 7 个环境跳过节点在另一个真实 PG 套件中已经执行，**不改写 parent 原有统计**。完整映射见 `ci-final/PG_SKIPPED_NODE_MAPPING.json`。

## 恢复和容量原始观察复核

C13 重新核对 12 场景原始 before/after SQL、首次请求/重放/竞争请求输出。四个硬杀场景均记录 `exit=-9`，实际 recovery worker 恢复后 resource claim 成功，提交前故障只产生一次资金根，已提交资金行在恢复前后保持相同。两个存活超租约场景保留同一 execution token，heartbeat 超过旧 lease 边界，竞争恢复 worker 的 recovered/failed 均为 0。

必须准确描述：C11 硬杀后会主动将持久租约设为过期，再运行真实恢复 worker；该证据没有建立自然超时后的生产恢复时延。C11 actor 直接调用 route 函数并使用工程 Principal，不是 HTTP/JWT 入口。C09 名为 process_exit 的用例注入 `SystemExit(91)` 检验事务回滚，不是 OS 硬杀。真实 JWT/HTTP 入口由 C13 本地 18 项工程旅程另行支撑。

C13 对 52 条原始容量交易和 52 条 SQL 观察逐行核验：52 个不同订单及资金根，全部成功；每单一次支付尝试、两条资金行，扣款/借方/贷方均为 16800 CNY，订单与 Trips 均 COMPLETED。该负载使用 CONTRACT_SIMULATOR 与合成供货事实；没有测试真实 PSP、真实供货或 HTTP 认证，也没有建立生产 SLA。

## 来源及归档边界

C13 直接读取 GitHub Gate/app tree、作业与 artifact 元数据；下载 ZIP 与 GitHub SHA256 digest 一致。depth48、C09、C11 以及 parent 三个含 skip 分片的 1542 文件 fingerprint 完全一致；其中 136 个已物化应用文件又与 C13 冻结来源逐一比对。C09 的 8 个、C11 的 106 个 artifact 内部绑定文件全部通过 SHA256 校验。跨进程/容量 harness 源文件也按固定 Gate 独立下载并比对。

`ci-final/CI_SOURCE_BINDING.json` 保存来源、artifact digest 和单份完整 fingerprint 位置。永久归档以 `CI_FINAL_SHA256.json` 为准：保留最终结论、逐节点映射、关键原始结果和过程观察；不重复装入 ZIP、旧失败/parent 原包或多份完整 fingerprint。工作区原始材料未删除，旧 FAIL 证据继续保留。

本结论限于上述完整工程旅程与限定用例。隔离 fixture 的工程权限不代表真实酒店经营或媒体权利；不授全部 305 义务/1009 场景、C14 商业授权、生产、物理真机或完整三端体验 PASS。未部署、未合并、未连接真实 PSP；AI 独立意见不新增真人签名要求。
