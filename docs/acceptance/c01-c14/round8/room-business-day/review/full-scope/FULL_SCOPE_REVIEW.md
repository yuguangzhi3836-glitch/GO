# C13 接外部支付前完整范围独立审核

结论：**HOLD_FULL_SCOPE，不满足完整范围100%验收**。V2审计修复仍为PASS_SCOPED；存在明确实现缺口R8-10，以及当前候选证据尚未完成绑定/执行的项目。不得把35项审计测试或全部workflow绿灯直接替代18组业务断言。

## 固定身份与方法

源码读取gate为c7ea23535831ac37bb50bbc17594d4823aeceabc；产品提交90f228e105b7fd0d8d6c4e9810eccd84534c31a1。随后只读核查新gate 7c006399aa41a4a4ba8486100ca25b26a402d625的application树仍为517c1aadc3b2bb624c79717ad1a2dc5817b37697，故本报告应用源码结论仍适用。19个选定源文件逐个按Git blob SHA重新验证，见verified-source-manifest.json与source/；models.py和rooms.json另于新gate只读检查。未重新运行无关模块，未改实现、写GitHub或调用真实支付。当前CI结果与完整工件核查由主执行者负责，本报告不代签。

原c13-preparation-ACCEPTANCE_MATRIX.json有18组、executed_tests=0、全部NOT_RUN_WAIT_FROZEN_CANDIDATE；这是准备清单，不是已完成报告。payment-preexternal-audit/README.md明确要求完整隔离回归、PG、营业日及独立范围审核，且真实外部默认关闭。

## 可核查范围表

下面路径以application/tests/为根；“待当前证据”表示已检查测试/实现存在，未把历史PASS移植到本候选。测试名只映射其实际断言，不能由文件名推定全覆盖。

| 范围 | 已检查的实现/测试依据 | 仍需满足的当前证据或缺口 |
|---|---|---|
| R8-01 配置/日历/五池六价 | test_c01_aoluguya_business_day.py业务fixture建立5×50与两池0/1/2餐698/798/898；旧独立day的test_confirmed_six_prices_share_only_two_of_five_physical_pools实际查询 | 当前候选重跑独立六价/共享池查询；保留另三池未知价格和素材授权HOLD |
| R8-02 maker/checker开卖 | test_c01_hosted_operating_journey.py::test_gate_blocks_every_sale_entry_then_independent_review_opens_full_journey；approved_version_invalidates参数覆盖拒绝、内容、bytes、reviewer、fare | 当前PG增量JUnit及HTTP原始失败/正向结果 |
| R8-03 持久JWT/零写入 | operating_journey的unauthorized_equivalent_entries、scope_checks_other_hotel；旧独立day的close_denies_readonly_and_cross_hotel_principals | 当前节点覆盖矩阵须分别列入住/扣款/退款/日结，不能将预约接口零写入外推资金接口；补跑独立日结授权检查 |
| R8-04 最后一间跨餐别并发 | test_hosted_direct_inventory_matrix.py证明顺序共享池；test_hosted_direct_reservation_operations.py::test_atomic_daily_inventory_prevents_oversell_and_prices_each_night把容量直接设1且顺序下单 | 已读文件不足证明“从50真实订单消耗到1，再跨餐并发仅一成功”；需定位并提交确切当前节点或补齐该隔离案例，不能把顺序测试当并发 |
| R8-05 页面/电话/同key | reservation_operations的go_page_and_phone_orders_share_inbox_notifications_and_audit_chain；operating_journey与business_day真实HTTP重放 | 当前JUnit；同key换内容、通知数/夜数不增须逐项对应，不能只验证返回同reservation_id |
| R8-06 显式金额checkout/授权非收入 | test_depth07_hosted_money.py::test_authorization_binds_selected_room_owner_hotel_and_has_no_cash_posting；test_c11_consumer_payment_source_boundary.py | 当前全量相关节点+PG payment-junit；根、binding、intent、movement及零现金分录查询 |
| R8-07 取消边界 | test_hotel_cancellation_clock.py覆盖confirmed anchor/重复确认/缺确认/精确截止；business_day的confirmed_cooling_period_survives_nominal_checkin_boundary | 当前节点结果；HOTEL_CONFIRMED仍是明确隔离配置，不能称实店已确认起点 |
| R8-08 拒绝/超时/免费退出 | depth07的cancel_reject_expiry_release_graph、release_and_inventory_rollback；operating_journey confirmed_uncharged_request及UNKNOWN/IN_HOUSE拒绝 | 当前全量/PG增量；RELEASE与REFUND分开核对 |
| R8-09 改期/审批故障 | operating_journey::test_approval_failure_and_retry_are_truthful_atomic_and_idempotent三故障；depth08 hosted change相关实现继承 | 当前审批状态及旧新日库存证据；资金generation需对应专门资金变更节点，未从无checkout改期例外推 |
| R8-10 身份/到店/分房/入住 | guest_stay_fulfillment锁住酒店并检测同房重叠；business_day真实HTTP身份/14点/同房重叠 | **实现缺口：无room_reference→hotel→pool登记校验，错误房池/未知房号仍可赋值。须补齐后独立复验** |
| R8-11 正常/提前离店 | business_day完整短住/跨夜；depth07::test_capture_only_dual_confirmed_fulfillment_and_release_unused_amount；pending_hotel_has_no_guest_stay_and_graph_extension_cannot_fake_inventory | 当前节点结果及冻结履约金额检查；真实提前离店计价/延住政策未知仍HOLD |
| R8-12 履约/捕获/对账 | depth07::test_fulfillment_cannot_bypass_stay_or_change_proof_and_dispute_rechecks_at_capture；capture_ledger_fault_rolls_back_cash_release_and_order_then_retries；simultaneous_capture_retries_post_once | 当前资金JUnit、账本故障恢复与原始SQL；PG是必须单独核查的后端证据 |
| R8-13 部分退款/独立裁决 | depth07的partial_refund_is_durable_original_capture、parallel_refund_approvals、approval_checks_independent_actor_actual_cash_full_amount_and_closed_case | 当前相关节点；确认refund→原capture、本订单/币种/预算与并发不超退 |
| R8-14 退款故障/第二周期 | depth07的partial_refund_is_durable_original_capture包含ledger故障；two_partial_refunds_start_distinct_cycles_without_resetting_trip_completion | 当前原始PENDING/恢复/周期行证据；不能用其他行业depth21 refund测试替代酒店分支 |
| R8-15 UNKNOWN/跨日 | test_v70_r4_c01_unknown_episode.py的episode_digest_fences_resolution、unknown_without_open_episode、audit_write_rollback；business_day注入/解锁/阻断 | 当前新代旧证据拒绝、未知不计收入、未决异常清单；存在代码并不等于CI当前已运行 |
| R8-16 日结时间/酒店/币种 | business_day local_midnight/overnight；hosted_business_day按hotel/date/currency；旧独立day economic_date_uses_movement_across_midnight和ledger币种反例 | 补跑独立day；另酒店/无关旧订单隔离和多币种正向需具体节点，当前已读测试不能证明全部对照 |
| R8-17 封账/重放/晚到 | business_day concurrent_day_close_has_one_durable_result、archived_order_mutation、overnight；hosted_business_day事务快照/唯一日结/源hash验证 | 当前PG并发结果+归档后源改动反例；新源码要重新绑定，不借用旧候选5失败后的修复口头结论 |
| R8-18 前台/Trips/通知/联合SQL | business_day的资金总额、双分录差额、凭证和250库存；depth07退款Trips；旧独立day graph()原始行采集 | 当前独立day原始记录与应用结果对照；QUEUED仅排队，真实送达不在本轮证明范围 |

## 明确实现缺口：物理房间与房池绑定

`src/go_hotel/services/guest_stay_fulfillment.py::assign_room`接受任意非空字符串，按酒店+相同字符串查重叠后直接写assigned_room_reference。它没有查询HostedDirectRateVariantRow或HostedDirectInventoryPoolRow，也没有验证该房号属于预订池。模型仅有pool(room_details_json)、variant(offer→pool)、GuestStayLifecycleRow自由引用；RoomExternalIdentityRow是connector外部房型身份映射，不具备hosted_hotel/pool物理房号归属。data/aoluguya/rooms.json是官网房型目录，不是实店房号注册表。

最小设计可以复用pool.room_details_json定义严格版本化房间登记，按reservation.offer→variant→pool查允许房号及active/source状态，拒绝未知、错误池、重复跨池配置。保留现有酒店事务锁及重叠校验，在入住前重验绑定，防登记变更绕过。隔离fixture应显式创建合成房间登记，不将其伪装为实店确认；更长期可使用独立房间表与唯一约束。测试至少覆盖正确池、错误池、未知/停用房号、同酒店重叠、跨酒店相同编号以及并发。该方向是建议，未在本审核中修改实现。

## 当前CI需要交付的确切证据

1. 新gate的source/alignment原始结果，application tree与文件数/hash一致；不能把上一个gate绑定清单错误的失败当产品失败，也不能绕过校验。
2. C11 payment-audit-junit.xml：35 tests、0失败/错误/跳过；锁代码必须在实际PG18.4运行。SQLite35通过不能替代。
3. C11 cell-depth-increment-junit.xml与log：business_day、operating_journey、列宽/资金来源/权限等实际节点结果，零跳过；payment-junit.xml、outbox-junit.xml与C11 process recovery results/execution/原始SQL；C12 capacity结果保持其有限负载定义。
4. 当前application全量回归、parent/source兼容、mobile/browser及原有gate工件。跳过项须逐项确认与本范围关系，父候选138e24d7的PASS不能迁移。
5. 独立day当前执行：`docs/acceptance/c01-c14/round8/first-candidate-c13/test_independent_day.py`有20项独立反例，但当前PG工作流没有收集它，application全量pytest也不会自然覆盖docs路径。原样加入会因SOURCE硬编码candidate-9a298cb3/application而失败；需将来源断言绑定当前checkout，ART改到当前运行工件目录，保留业务断言。依赖来自tests.test_c01_aoluguya_business_day和tests.hosted_review_support。旧5失败集中于授权额1例、归档订单字段3例、凭证1例；应用测试已加入相应回归，但独立其余反例仍需本候选重跑或明确等价替代。
6. R8-04等尚无确切节点的原断言需明确定位/补证，不以任意缩小分母标100%；R8-10实现缺口修复后的新固定候选需重新审查。

## 边界

本轮仅可验收内部隔离合同与安全关闭行为；真实商户资格、真实预授权产品接口/签名、凭证、正式通道联调与受限真实资金另行验证。未确认取消起点、真实物理房号、未知价格和原图权利必须保持真实状态。未发现其他确定实现缺口不代表对未读源码作正确性保证；上述覆盖表清楚区分已读证据、未证断言与实际缺陷。
