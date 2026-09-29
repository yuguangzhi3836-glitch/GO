# C13 18组逐项节点映射

基线产品d838f05d、gate c7c3bfd；后续六文件增量待新冻结。当前HOLD_FULL_SCOPE：已发现的内部实现/精确断言缺口均已补齐并有局部SQLite复验；尚需新冻结候选PG与全量原始JUnit逐节点绑定。18组分母不变；真实酒店资料和外部接入是明确未完成的独立边界，不等同内部隔离验收。

## R8-01 五池六价/日历

- `tests/test_c13_aoluguya_independent_day.py::test_confirmed_six_prices_share_only_two_of_five_physical_pools`
- `tests/test_c01_aoluguya_business_day.py::test_missing_pool_calendar_blocks_whole_day`

真实未确认价格/原图仍HOLD；当前候选CI结果待绑定。

## R8-02 maker/checker开卖

- `tests/test_c01_hosted_operating_journey.py::test_gate_blocks_every_sale_entry_then_independent_review_opens_full_journey`
- `tests/test_c01_hosted_operating_journey.py::test_approved_version_invalidates_across_public_page_availability_and_reservation`
- `tests/test_c01_hosted_operating_journey.py::test_media_submitter_cannot_self_review_or_claim_another_identity`

参数覆盖拒绝、content、bytes、reviewer_revoked、fare_changed；不等于199张原图已确认。

## R8-03 四操作×权限拒绝

- `tests/test_c01_money_authority_matrix.py::test_executable_operation_rejects_invalid_authority_without_business_writes`

新增16节点已由C13独立SQLite复跑；4操作×readonly/other_hotel/revoked_grant/revoked_session，22表逐字段不变，每例随后合法角色成功。新冻结/CI待绑定。

## R8-04 50间消耗后跨餐别最后1间

- `tests/test_c01_room_registry_journey.py::test_fifty_room_pool_is_consumed_by_orders_before_cross_rate_last_room_race`
- `tests/test_depth07_hosted_money.py::test_cancel_reject_expiry_release_graph_and_nightly_inventory_without_cash_refund`
- `tests/test_depth07_hosted_money.py::test_release_and_inventory_rollback_if_projection_fails_then_retry_once`

49真实订单后两个餐别并发200/409、另一池不变已有独立SQLite实跑；PG待新候选。

## R8-05 页面/电话及同key

- `tests/test_hosted_direct_reservation_operations.py::test_go_page_and_phone_orders_share_inbox_notifications_and_audit_chain`
- `tests/test_c01_aoluguya_business_day.py::test_complete_business_day_with_cancel_refund_difference_repair_and_replay`
- `tests/test_c13_currency_day_scope.py::test_availability_truthful_currency_and_unsupported_sale_is_zero_write`
- `tests/test_c01_booking_replay_matrix.py::test_same_booking_key_replays_without_new_nights_events_or_notifications_and_changed_body_fails`

四入口真实HTTP各自原请求重放结果相同，22类业务表逐字段不变；同key改guest及日期分别409且零写入。新增4节点独立SQLitePASS；新冻结与PG/全量CI待绑定。

## R8-06 明确金额/授权非收入

- `tests/test_depth06_direct_checkout.py::test_checkout_binds_owner_amount_currency_and_requires_explicit_mode`
- `tests/test_depth07_hosted_money.py::test_authorization_binds_selected_room_owner_hotel_and_has_no_cash_posting`
- `tests/test_depth06_direct_checkout.py::test_simultaneous_checkout_retries_have_one_authorization`

CNY顾客产品边界保留；客户USD不能下单或checkout。

## R8-07 取消秒边界/冻结规则

- `tests/test_hotel_cancellation_clock.py::CancellationClockTests::test_confirmed_anchor_29_30_31_minutes`
- `tests/test_hotel_cancellation_clock.py::CancellationClockTests::test_exact_local_deadline_second_boundary`
- `tests/test_hotel_cancellation_clock.py::CancellationClockTests::test_exact_cutoff_quote_expiry_is_not_ten_minutes_late`
- `tests/test_c01_aoluguya_business_day.py::test_confirmed_cooling_period_survives_nominal_checkin_boundary`
- `tests/test_c01_cancellation_second_boundary.py::test_confirmed_anchor_second_boundaries_display_quote_execution`
- `tests/test_c01_cancellation_second_boundary.py::test_quote_from_last_free_second_expires_at_exact_confirmed_cutoff`

新增4节点独立SQLitePASS：下单等1小时再确认，确认后29:59/30:00/30:01跨14点，GET冻结规则/hash与quote/execute一致；旧FREE quote精确截止409且22表不变，release非refund；三个执行分支均重放不写入。规则显式隔离合成，不冒认真实酒店政策。

## R8-08 拒绝/超时/未收费退出

- `tests/test_depth07_hosted_money.py::test_cancel_reject_expiry_release_graph_and_nightly_inventory_without_cash_refund`
- `tests/test_depth06_direct_checkout.py::test_unknown_funds_keep_inventory_and_block_cancel_and_timeout`
- `tests/test_c01_hosted_operating_journey.py::test_confirmed_uncharged_request_can_withdraw_and_updates_trips`
- `tests/test_c01_hosted_operating_journey.py::test_uncharged_exit_does_not_bypass_unknown_or_fulfilled_stay`

UNKNOWN与IN_HOUSE反例存在；受保护资金/库存重试不重复仍须当前相关JUnit。

## R8-09 改期审批/故障恢复

- `tests/test_c01_hosted_operating_journey.py::test_approval_failure_and_retry_are_truthful_atomic_and_idempotent`
- `tests/test_depth08_hosted_change.py::test_change_high_supplement_low_no_refund_and_immutable_original_authorization`
- `tests/test_depth08_hosted_change.py::test_stale_quote_price_change_last_night_sold_out_and_ledger_fault_keep_old_stay`
- `tests/test_depth08_hosted_change.py::test_multiple_changes_keep_prior_roots_and_refund_final_original_capture`
- `tests/test_depth08_hosted_change.py::test_parallel_changes_owner_and_currency_never_double_release`

三审批故障及价格/售罄/ledger故障、旧新root/原授权/并发变更有确切节点；当前候选全量JUnit须绑定这些节点。

## R8-10 身份/分房/入住

- `tests/test_c01_aoluguya_business_day.py::test_same_hotel_room_cannot_be_assigned_to_two_overlapping_stays`
- `tests/test_c01_room_registry_journey.py::test_wrong_pool_room_rejected_without_assignment_or_event`
- `tests/test_c01_room_registry_journey.py::test_room_registry_revocation_between_assignment_and_checkin_blocks_entry`
- `tests/test_c13_room_registry_authority.py::test_occupied_room_registry_rejection_has_zero_business_writes`
- `tests/test_c01_room_registry_journey.py::test_equivalent_registry_spelling_cannot_assign_an_occupied_room`

房池绑定缺口已修并有真实HTTP反例；真实房号来源不冒认。跨酒店同编号/登记CAS实际PG待当前门禁。

## R8-11 离店/部分履约

- `tests/test_c01_aoluguya_business_day.py::test_overnight_checkout_next_day_preserves_prior_close_and_opening_balance`
- `tests/test_depth07_hosted_money.py::test_capture_only_dual_confirmed_fulfillment_and_release_unused_amount`
- `tests/test_depth07_hosted_money.py::test_pending_hotel_has_no_guest_stay_and_graph_extension_cannot_fake_inventory`

同住客双证据/金额上限与延住阻断存在；早离真实商业计价未获确认。

## R8-12 履约/捕获/对账

- `tests/test_depth07_hosted_money.py::test_fulfillment_cannot_bypass_stay_or_change_proof_and_dispute_rechecks_at_capture`
- `tests/test_depth07_hosted_money.py::test_capture_ledger_fault_rolls_back_cash_release_and_order_then_retries`
- `tests/test_depth07_hosted_money.py::test_simultaneous_capture_retries_post_once`

共享资金图、原授权父子和事务回滚，不以沙箱配置当银行实收。

## R8-13 部分退款/独立裁决

- `tests/test_depth07_hosted_money.py::test_partial_refund_is_durable_original_capture_and_only_closes_its_case`
- `tests/test_depth07_hosted_money.py::test_parallel_refund_approvals_cannot_overcommit_actual_capture`
- `tests/test_depth07_hosted_money.py::test_approval_checks_independent_actor_actual_cash_full_amount_and_closed_case`
- `tests/test_depth07_hosted_money.py::test_owner_after_sales_api_idempotency_and_refund_permissions`

授权/原capture/本订单/预算及owner边界节点存在；当前全量结果待绑定。

## R8-14 退款故障/第二周期

- `tests/test_depth07_hosted_money.py::test_partial_refund_is_durable_original_capture_and_only_closes_its_case`
- `tests/test_depth07_hosted_money.py::test_two_partial_refunds_start_distinct_cycles_without_resetting_trip_completion`

真实本地ledger故障注入与不同退款周期，不能用其他行业退款套件替代。

## R8-15 UNKNOWN与跨日

- `tests/test_v70_r4_c01_unknown_episode.py::test_episode_digest_fences_resolution_and_mixed_settlement`
- `tests/test_v70_r4_c01_unknown_episode.py::test_unknown_movement_without_open_episode_fails_closed_without_writes`
- `tests/test_v70_r4_c01_unknown_episode.py::test_episode_and_movement_rollback_when_audit_write_fails`
- `tests/test_c01_aoluguya_business_day.py::test_complete_business_day_with_cancel_refund_difference_repair_and_replay`

新旧generation证据隔离/异常留存；当前门禁仍须实际collect/execute。

## R8-16 日期/酒店/币种

- `tests/test_c13_aoluguya_independent_day.py::test_economic_date_uses_movement_across_midnight`
- `tests/test_c01_aoluguya_business_day.py::test_overnight_checkout_next_day_preserves_prior_close_and_opening_balance`
- `tests/test_c13_currency_day_scope.py::test_daily_close_separates_currency_foreign_hotel_and_old_order`
- `tests/test_c13_currency_day_scope.py::test_today_booking_for_future_stay_moves_only_future_inventory`
- `tests/test_c13_currency_day_scope.py::test_prior_day_capture_refunded_today_keeps_prior_close_and_opening_balance`

新增4项已独立SQLitePASS（含币种守卫）：CNY顾客HTTP；USD/外酒店为明确内部历史obligation并经ensure_authorization形成规范资金图；旧订单opening保留且排除当日计数；未来入住仅减未来库存；旧capture次日refund9800双分录、opening69800/closing60000、昨日replay不变。顾客CNY/首试点边界未扩大。待新候选PG。

## R8-17 日结封账/并发/晚到

- `tests/test_c01_aoluguya_business_day.py::test_concurrent_day_close_has_one_durable_result`
- `tests/test_c13_aoluguya_independent_day.py::test_archived_order_source_tamper_rejected`
- `tests/test_c13_aoluguya_independent_day.py::test_archive_payload_hash_is_rechecked`
- `tests/test_c13_aoluguya_independent_day.py::test_independent_normal_overnight_funds_inventory_replay`

旧成功源变更拒绝、正常次日行为不破坏前日；PG当前候选结果待绑定。

## R8-18 交班/Trips/通知/联合SQL

- `tests/test_c13_aoluguya_independent_day.py::test_independent_short_stay_refund_and_free_cancel`
- `tests/test_c13_aoluguya_independent_day.py::test_captured_arrival_voucher_truthful`
- `tests/test_depth07_hosted_money.py::test_owner_after_sales_api_idempotency_and_refund_permissions`
- `tests/test_hosted_direct_reservation_operations.py::test_go_page_and_phone_orders_share_inbox_notifications_and_audit_chain`
- `tests/test_hosted_frontdesk_uat_daily_close.py::test_shift_handover_captures_unresolved_inbox`
- `tests/test_hosted_frontdesk_uat_daily_close.py::test_guest_data_is_masked_and_unmask_is_manager_audited`

独立day原始graph/ledger/inventory/close记录可核；交班和PII审计确切源节点已补。QUEUED只证明排队，实际通知送达仍属外部边界。

最终增量冻结：product `55ea39cd41d39e50abc221e73812ab01fec1c5ce`，application tree `c98e58256d29062a1026bc5ff64f22c99dbac92b`。6份本地源码SHA256及Git blob均独立重算匹配closure-meta.json，独立币种测试与tests副本逐字节相同。完整1556文件tree摘要由执行者提供，未由本审核重下载复算。最终状态 **PENDING_CURRENT_CI**；局部独立28项PASS，等待此候选PG/全量工件，不继承父候选结果。
