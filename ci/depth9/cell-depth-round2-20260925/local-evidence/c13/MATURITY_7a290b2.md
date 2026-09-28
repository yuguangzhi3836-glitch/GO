> 历史草案：此表采用初始五维，已被同目录 INTERNAL_WEIGHTED_7a290b2.md 主评分取代；不得引用以下数值为本轮主评分。保留源码/测试定位供审计。

# C13独立证据成熟度评价：14模块

基线仅为PR246 `7a290b2b17baaa778820f6d8e23ad22ba97e1449`；产品`d0be4c409ffa0a8de2148b258b191c8058527421`，application tree `b2641edf2d5cbf65a2447c804111a0bb50ae83cb`。正在开发的押金/用车政策不计入本表。评分日期2026-09-25。

## 量尺及审查建议

五维依次为F职责功能闭环、A权限与权威事实、R异常恢复、U跨端可用性、O持续运营证据。每维0无可采证据、1仅设计/零散、2部分实现和局部验证、3该维核心范围实际验证、4冻结约定范围逐项完整闭环。总分=五维之和×5，名称必须为**证据成熟度/100，绝不是完成百分比**。相差5分只表示一个离散证据等级，不表示5%的功能工作量。

建议保留这个量尺，但增加三项约束：①4分必须有冻结验收义务清单、逐项可追溯原始证据与关闭例外，不能用测试总数替代；②每维单独判定，低运营分不能被单项大量单测掩盖；③未知是证据缺口，区别于确认代码缺陷，不能凭低分推断必须重写。业务维度的3分只涉及本轮内部工程核心，不暗示供应商/PSP已接入。O考察该模块自身持续值守、告警、复核/恢复记录；通用CI存在不等于所有业务团队已常设运行。

C13/C14分别按自己的审查交付、版本/权限、失败恢复、任务跨端可达、持续审核衡量。下面分数包括已交付的技术审查/规则防护，但**PR247仅设计；本轮未取得14团队持续在线执行的完整证据；现有临时子agent技术review不等于Lite独立fresh execution正式意见**。不得把本表自评转换成组织上线PASS。

## 评分与定位

路径均相对`application/`，除注明仓库根路径或本地review证据。F/A/R/U/O见上文。

| 模块 | F | A | R | U | O | 证据成熟度/100 | 源码/测试/原始证据与扣分理由 |
|---|---:|---:|---:|---:|---:|---:|---|
| C01 酒店 | 3 | 3 | 3 | 2 | 1 | 60 | `src/go_hotel/services/hosted_money.py`、`hosted_fare_change.py`；`tests/test_v70_r4_c01_unknown_episode.py`、`test_v70_next_c01_authorization_replay.py`。最终browser含酒店变更账本SQL审计。已有核心钱款/未知恢复，尚未逐项证明全部租户/媒体撤销竞态、真机及持续酒店运营闭环。 |
| C02 机票 | 3 | 3 | 3 | 2 | 1 | 60 | `src/go_hotel/flight/changes.py`、`payment_recovery.py`；`tests/flight/test_c02_three_end_change_quote.py`、`tests/payments/test_c11_flight_idempotency_recovery.py`；C11 PG真实12进程场景含checkout/change hard kill及lease恢复。不是航空真实履约/票规认可；全旅客多航段义务、真机及持续处置未逐项封闭。 |
| C03 铁路 | 3 | 3 | 3 | 2 | 1 | 60 | `src/go_hotel/rail/service.py`、`services/rail_change_resolution.py`；`tests/test_next_depth_c03_payment_inventory_races.py`、`test_c03_c06_change_quote_fencing.py`。新增旧报价拒绝在PG七文件89项中真实执行；未穷举所有票务状态与跨端异常/长期并发运营。 |
| C04 租车 | 2 | 2 | 2 | 2 | 1 | 45 | `src/go_hotel/mobility/rental/damage.py`、`api/routes/rental_damage.py`；`tests/test_rental_damage_disputes.py`26项PG PASS及原settlement/receipts。争议/申诉/复核/链校验已测，但supplier证据代录未验证、supplier tenant未直连、押金授权扣取释放未接C11；新争议跨端仍欠闭环，故局部高质量不抬成模块3。 |
| C05 用车 | 2 | 2 | 2 | 2 | 1 | 45 | `src/go_hotel/mobility/ride/service.py`、`refunds.py`、`flight_sync.py`；`tests/test_c05_engineering_currency.py`12项PG PASS，`test_v70_r5_c05_concurrent_unknown.py`。固定币种、并发未知恢复可采；搜索迟取消费与退款零费存在已确认合同不一致，缺预订接受的版本政策/旧单适用性，影响功能/权威/退款恢复三维。 |
| C06 景点 | 3 | 3 | 3 | 2 | 1 | 60 | `src/go_hotel/attractions/service.py`、`validity.py`；`tests/test_c06_internal_policy_registry.py`、`test_next_depth_c06_supplier_validity.py`、`test_c03_c06_change_quote_fencing.py`。独立旧恢复错解首次改签probe已转PASS，PG绑定quote真实执行。真实供应商身份/核销未接，内部全状态义务和跨端异常尚未全映射。 |
| C07 旅客智能 | 3 | 3 | 3 | 1 | 1 | 55 | `src/go_hotel/travel_intelligence/preferences.py`、`service.py`；`tests/test_v70_r4_c07_consent_provenance.py`、`test_round2_c07_process_recovery.py`；PG C07 6场景PASS。目的同意/撤回/恢复核心已证；本次缺完整消费者/后台/移动授权撤回实际旅程，长期同意审计未知。 |
| C08 AI规划执行 | 2 | 3 | 3 | 1 | 1 | 50 | `src/go_hotel/go_ai/planner.py`、`service.py`；`tests/go_ai/test_c08_complete_task_plan.py`、`test_c08_hard_exit_recovery.py`、`test_c08_audit_commit_failure.py`在最终parent执行。审计/lease/checkpoint有实测；用户目标到完整可操作计划及跨端取消/接管/结果回流并未整体闭环，独立PG多进程全矩阵未明。 |
| C09 判断信任 | 3 | 3 | 3 | 1 | 1 | 55 | `src/go_hotel/judgment/service.py`；`tests/judgment/test_next_depth_concurrent_judgment.py`、`test_round2_evidence_authority.py`；PG C09 12场景PASS。当前判断唯一性/封存/回放核心已测；解释、申诉、撤销在各端可达性及持续判断质量/误判纠正记录不足。 |
| C10 行程统一 | 3 | 3 | 3 | 2 | 1 | 60 | `src/go_hotel/services/consumer_unified_lifecycle.py`、`vertical_lifecycle_projection.py`、`order_supplier_fulfillment.py`；`tests/journey/test_c10_current_status_projection.py`、`test_c10_lifecycle_supplier_identity.py`11、`test_c10_unknown_payment_projection.py`7、`test_c10_supplier_money_projection.py`17在PG PASS。browser六品类同订单SQL已证；新异常图全端与真机、历史供应商身份受控修复、持续对账未封闭。 |
| C11 交易财务 | 3 | 3 | 3 | 2 | 1 | 60 | `src/go_hotel/services/omnichannel_payment.py`、`unified_money_movement.py`、`vertical_transaction_bridge.py`；`tests/test_c11_consumer_payment_source_boundary.py`9PG、PG payment47+outbox1+进程12。当前parent绑定、余额、公开创建权限、退款投影已修并复验；租车押金闭环未接、全资金异常/补偿义务清单及持续财务对账未齐，真实PSP未验。 |
| C12 平台安全运营 | 2 | 3 | 2 | 2 | 2 | 55 | `src/go_hotel/services/outbox.py`、`recovery.py`、`src/go_hotel/security/`；`tests/test_outbox_resilience.py`，仓库根`ci/retention/verify_source.py`/`verify_alignment.py`与五项最终CI。固定源码/权限及CI采证已验证；真实事务写压力/浸泡、SLA、备份恢复与常设调度告警尚缺；原生构建非真机。O=2仅已有自动CI/恢复机制证据，非生产值守成立。 |
| C13 质量验收 | 2 | 3 | 2 | 1 | 1 | 45 | 本地`reviews/c13/PR246_7a290b2_CI_REVIEW.md`及4个阻断独立probe/修复复验；仓库根`ci/retention/verify_source.py`、不可变artifact绑定。版本隔离与原始证据核验达到技术核心；但常设审查任务派发/独立fresh runner/失败重试/超时回收/跨端意见回传未有Lite运行链。自评与临时review不代替正式组织独立验收。 |
| C14 规则法务 | 2 | 2 | 2 | 1 | 1 | 40 | `src/go_hotel/autonomy/action_control.py`、`condition_evidence.py`、`types.py`；`tests/autonomy/test_policy_lifecycle_binding.py`34项及current/durable authority、release guards；本地`reviews/c14/RULES_DISPOSITION_FINAL.md`。工程版本/撤销/环境护栏有测，但批准人可信来源与实际政策适用尚未接，C05真实经营仍HOLD；常设规则更新/审查失败恢复/跨端任务流未建，不是完整法律审核。 |

没有任何4分：缺统一冻结逐项义务清单和全部原始证据。不计算14模块平均“完成率”，分数不能相加成项目完成率。

## 当前采证基础及证据边界

详见`reviews/c13/PR246_7a290b2_CI_REVIEW.md`：五个run 36110043970/36110043878/36110043859/36110043844/36110043876固定同一head全成功；全量333文件四分片不重不漏，2969PASS+7PG-only skip、无fail/error；Cell455PASS与parent重叠；PG七新文件89PASS零skip；PG C07 6、C09 12、C11进程12/payment47/outbox1；PG16六race PASS。browser33页面+20旅程、六品类SQL和酒店账本审计；frontend319，compat34。不能按这些重叠计数推得功能覆盖率。七SQLite skips仍是skips，对应PG另执行。

根基7a290b2仅为候选，未部署；本评分未连接香港、供应商或PSP。主观等级受现有可采证据范围约束，低分优先补证/补实际缺口，不重做已接受核心。新代码完成并冻结SHA后按差异重新独立review，不能提前提高分数。

## 下一轮独立审查入口

1. C04/C11：同一money root/intent/movement，决议最新version+state fence，申诉冻结，重复/并发资金动作、原授权余额/币种约束、租户/操作者隔离、崩溃恢复；禁止历史幂等响应当当前可执行金额。真实押金交易仍禁用。
2. C05：预订接受的不可变政策版本，搜索/预订/退款同一版本，时区/边界/修改与旧单适用；未批准真实政策不能写成已批准。工程fixture限定DEV/TEST。
3. 以上待开发冻结manifest后只读审查，不参与被审代码开发，不预签PASS。
