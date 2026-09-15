# 37处幂等 callback 静态分类

任务：V70-R2-C11-02。37处调用 / 34个operation / 9个路由文件。

这是静态分类与候选设计，不是运行验收。每个事务提交都存在“服务端已提交、调用方未收到确认”的边界；不能把 ValueError、HTTP 4xx 或本地回滚等同于“没有发生过副作用”。具体审阅文件指纹见 SOURCE_SHA256.json。

## C11-CALL-16 — FLIGHT_CHECKOUT / checkout

- 调用位置：`application/src/go_hotel/api/routes/flight.py:74`；模式：SYNC；优先级：P0。
- 提交前失败：production_truth_required and owned order lookup precede first mutation; safe retry only if validation failed before mutation/bridge and rollback is positively known.
- 提交后或结果不明：checkout commits PAYMENT_AUTHORIZED/payment_method before bridge. Source decision, intent, authorization and capture have their own commits. Later projection or bridge errors may follow money effects.
- 现有持久键：Known order_id; payment business root FLIGHT_ORDER/order_id; flight-checkout:{order_id}, flight-auth:{order_id}, flight-cap:{order_id}.
- 最小恢复接点：Read payment root and confirmed money receipts; resume the same checkout_contract only for known states. UNKNOWN_EXTERNAL_STATE stays fenced. Project existing capture into order and complete HTTP claim after verified outcome.

## C11-CALL-17 — FLIGHT_EXECUTE_CHANGE / execute_change

- 调用位置：`application/src/go_hotel/api/routes/flight.py:85`；模式：SYNC；优先级：P0。
- 提交前失败：Owned order/quote, checked plan, explicit consent, status and expiry validations before first authorization-requested commit. Existing resumed state is not evidence of a fresh no-effect invocation.
- 提交后或结果不明：First commit freezes AUTHORIZATION_PENDING/UNKNOWN_EXTERNAL_STATE and supersedes other quotes. prepare_adjustment can commit intent/auth; subsequent released/conflict ValueError occurs after this boundary. Second commit sets PENDING_SUPPLIER.
- 现有持久键：order_id+quote_id and frozen change plan; FLIGHT_CHANGE/quote_id; flight-change-intent:{quote_id}, flight-change-auth:{quote_id}, flight-change-cap:{quote_id}, flight-change-release:{quote_id}; resolution row keyed quote_id.
- 最小恢复接点：Use quote and payment root to resume authorization preparation; never create new quote/root for retry. Keep pending supplier state. Capture/release only via reviewed flight_change_resolution.reconcile with supplier evidence, not as generic exception compensation.

## C11-CALL-09 — CONSUMER_EXPLICIT_CHECKOUT / checkout

- 调用位置：`application/src/go_hotel/api/routes/consumer_checkout.py:111`；模式：ASYNC；优先级：P0。
- 提交前失败：Environment/vertical/owner/expected amount/currency/payable status checked before outer claim. In callback, existing fulfillment unknown-state checks may refer to prior side effects.
- 提交后或结果不明：Hotel authorization/book/capture or vertical root/movements/supplier fulfillment each have durable steps. Late fulfillment/projection or HTTPException may follow capture.
- 现有持久键：order_id; hotel ExternalOperation operation_id fences; other vertical fixed checkout/auth/cap keys, payment root and supplier_fulfillment_id.
- 最小恢复接点：Resolve per-vertical canonical payment+supplier outcome via existing recovery hooks; replay verified final response or pending state without new payment, source choice or booking.

## C11-CALL-10 — CONSUMER_HOTEL_CREATE / create_consumer_order

- 调用位置：`application/src/go_hotel/api/routes/consumer_identity.py:115`；模式：ASYNC；优先级：P0。
- 提交前失败：Fare consent preflight before vault release; booking consistency/fare snapshot validated in order transaction, but disclosure may already be durable.
- 提交后或结果不明：Order/event/fare-snapshot commit before separate vault-evidence and response; random order_id not atomically bound to HTTP claim in reviewed path.
- 现有持久键：HTTP operation/key/hash; generated order_id, prebook_id and immutable fare snapshot. Reviewed create_order_with_event has no claim binding.
- 最小恢复接点：Reserve exact creation resource identity and atomically bind to claim/order event; recover same order/snapshot, append missing evidence once. Do not match by price/name.

## C11-CALL-15 — FLIGHT_CREATE_ORDER / create_order

- 调用位置：`application/src/go_hotel/api/routes/flight.py:70`；模式：SYNC；优先级：P0。
- 提交前失败：Duplicate traveler/raw reference and prebook/passenger validations can precede order commit, but earlier travelers may already have durable vault releases. HTTP/ValueError alone proves no rollback.
- 提交后或结果不明：Vault release(s), order commit and route vault-evidence commit are separate. New random order_id is not bound atomically to HTTP claim; post-commit response/audit failure can re-enter creation.
- 现有持久键：HTTP operation/key+payload hash exists; generated order_id and prebook_id are searchable evidence, but no atomic HTTP-claim-to-order mapping was found in reviewed creation path.
- 最小恢复接点：Introduce a durable creation-operation/resource binding before or atomically with creation; recover order by that exact binding. Deduplicate subsequent vault-evidence write. Do not infer a unique prior order from similar payload.

## C11-CALL-24 — RIDE_CREATE_ORDER / rb

- 调用位置：`application/src/go_hotel/api/routes/mobility.py:43`；模式：SYNC；优先级：P0。
- 提交前失败：Offer/date/client-policy validation precedes order transaction, but route vault release may already have durable side effects.
- 提交后或结果不明：Random order row/policy/reservation commits before source-runtime decision and separate vault-evidence transaction. No atomic outer-claim resource mapping found.
- 现有持久键：HTTP operation/key+payload hash; generated order_id and reservation/policy records. Same offer/time/account is not a unique operation key.
- 最小恢复接点：Add explicit claim->planned resource binding at order creation, then replay that row and complete missing source/evidence writes. No duplicate order creation from a new random ID.

## C11-CALL-25 — RENTAL_CREATE_ORDER / cb

- 调用位置：`application/src/go_hotel/api/routes/mobility.py:59`；模式：SYNC；优先级：P0。
- 提交前失败：Offer/date/client-policy validation precedes order transaction, but route vault release may already have durable side effects.
- 提交后或结果不明：Random order row/policy/reservation commits before source-runtime decision and separate vault-evidence transaction. No atomic outer-claim resource mapping found.
- 现有持久键：HTTP operation/key+payload hash; generated order_id and reservation/policy records. Same offer/time/account is not a unique operation key.
- 最小恢复接点：Add explicit claim->planned resource binding at order creation, then replay that row and complete missing source/evidence writes. No duplicate order creation from a new random ID.

## C11-CALL-01 — ATTRACTION_PREBOOK / prebook

- 调用位置：`application/src/go_hotel/api/routes/attractions.py:34`；模式：SYNC；优先级：P1。
- 提交前失败：Party/catalog/date/session/currency and capacity validation before issue_in transaction commit.
- 提交后或结果不明：Prebook contract commit acknowledgement loss may issue a second contract when outer claim is released; no inventory reservation at this stage.
- 现有持久键：Generated VerticalPrebookContractRow.prebook_id and terms hash; no reviewed outer claim->prebook mapping.
- 最小恢复接点：Persist resource binding and recover the existing exact contract rather than issue another. Do not treat availability observation as reserved inventory.

## C11-CALL-02 — ATTRACTION_CREATE_ORDER / book

- 调用位置：`application/src/go_hotel/api/routes/attractions.py:44`；模式：SYNC；优先级：P1。
- 提交前失败：Prebook/owner/request/party/product/stock validations inside order transaction; earlier vault releases are separate.
- 提交后或结果不明：Order+capacity+consumed contract commit before source-runtime decision and route vault-evidence write.
- 现有持久键：Consumed prebook_id -> order_id with request hash/owner; source decision for order; vault release_ids.
- 最小恢复接点：Recover via exact consumed contract; fill missing source/evidence without creating order or reserving stock again.

## C11-CALL-03 — ATTRACTION_EXECUTE_CHANGE / ec

- 调用位置：`application/src/go_hotel/api/routes/attractions.py:53`；模式：SYNC；优先级：P1。
- 提交前失败：Owned confirmed order, QUOTED+unexpired quote and target capacity checks before atomic commit.
- 提交后或结果不明：Prepared capacity+quote PENDING_SUPPLIER+order UNKNOWN commit may survive acknowledgement loss; direct retry currently expects QUOTED and can conflict.
- 现有持久键：order_id+quote_id and prepared capacity claim; pending quote; outer HTTP key.
- 最小恢复接点：Recover same pending quote and capacity reservation; await supplier fact. Do not create new quote or claim; complete/release capacity only on definitive supplier decision.

## C11-CALL-04 — ATTRACTION_REFUND / refund

- 调用位置：`application/src/go_hotel/api/routes/attractions.py:58`；模式：SYNC；优先级：P1。
- 提交前失败：Owned order, consumed terms, accepted quote and positive refund validations before frozen operation/lease commit.
- 提交后或结果不明：REFUND_PENDING operation/lease commit before refund; lost receipt/lease/finalize error can be post-money.
- 现有持久键：VerticalRefundOperation(ATTRACTION,order_id), request hash/lease; attraction-refund:{order_id}.
- 最小恢复接点：Use same operation/lease and fixed money key, verify durable receipts, finalize order/capacity and replay HTTP outcome.

## C11-CALL-05 — ATTRACTION_REDEEM / redeem

- 调用位置：`application/src/go_hotel/api/routes/attractions.py:61`；模式：SYNC；优先级：P1。
- 提交前失败：Evidence, ownership and CONFIRMED source state validated before transaction commit.
- 提交后或结果不明：FULFILLED+VOUCHER_REDEEMED event/lifecycle commit may survive ack loss; retry no longer sees CONFIRMED.
- 现有持久键：order_id+evidence_reference and stored voucher/supplier reference in event; outer HTTP key.
- 最小恢复接点：Replay only if exact redemption evidence matches committed transition; do not re-redeem or infer voucher success from order status alone.

## C11-CALL-06 — ATTRACTION_ADMIN_EXTERNAL_STATE / external_state

- 调用位置：`application/src/go_hotel/api/routes/attractions.py:64`；模式：SYNC；优先级：P1。
- 提交前失败：Actor/evidence/state and pending supplier/voucher reference checks before local commit.
- 提交后或结果不明：Capacity complete/release and pending quote/order transition are committed atomically; ack loss can leave definitive state before route error.
- 现有持久键：order_id+pending quote_id (not explicit API argument)+evidence_reference; capacity claim. A newer pending quote can make historical response ambiguous.
- 最小恢复接点：Bind explicit resolution identity to quote/evidence before replay; inspect persisted decision and voucher. Never apply an old response to a newer pending quote.

## C11-CALL-07 — ATTRACTION_REFUND_CONFIRMED / refund_confirmed

- 调用位置：`application/src/go_hotel/api/routes/attractions.py:73`；模式：SYNC；优先级：P1。
- 提交前失败：Owned order, consumed terms, accepted quote and positive refund validations before frozen operation/lease commit.
- 提交后或结果不明：REFUND_PENDING operation/lease commit before refund; lost receipt/lease/finalize error can be post-money.
- 现有持久键：VerticalRefundOperation(ATTRACTION,order_id), request hash/lease; attraction-refund:{order_id}.
- 最小恢复接点：Use same operation/lease and fixed money key, verify durable receipts, finalize order/capacity and replay HTTP outcome.

## C11-CALL-08 — supplier_unable_to_fulfill / unable_to_fulfill

- 调用位置：`application/src/go_hotel/api/routes/compensation.py:48`；模式：ASYNC；优先级：P1。
- 提交前失败：Supplier ownership before wrapper; reason/evidence validation and exact request checks before case/plan commit.
- 提交后或结果不明：Case/plan/event commit before route audit_service.append. Audit failure can follow a successfully registered cancellation request; no money is executed by this request function.
- 现有持久键：SupplierFaultCase.order_id -> case_id; CatalogSupplierRemedy request_hash binds supplier/cause/evidence/requester.
- 最小恢复接点：Recover same case by exact request hash, append missing request audit idempotently; do not call remedy.execute or refund merely to repair an HTTP response.

## C11-CALL-11 — cancel / cancel

- 调用位置：`application/src/go_hotel/api/routes/fare.py:43`；模式：ASYNC；优先级：P1。
- 提交前失败：Isolation, ownership, quote hash/consent/expiry/current facts and change-window checks before operation commit; existing operation returns persisted public state.
- 提交后或结果不明：Operation+order claim and pending order commit before advance; supplier or authorization may succeed before local finalization. HTTP/domain validation error may follow those commits.
- 现有持久键：CatalogCashFareOperation.quote_id -> operation_id; CatalogCashFareClaim.order_id; frozen plan hash; downstream operation-prefixed money keys.
- 最小恢复接点：Lookup operation by exact quote/actor/payload; use existing catalog_cash_fare_execution.reconcile/retry_payment APIs as appropriate. Never start a new cancellation/change quote for transport retry.

## C11-CALL-12 — change / change

- 调用位置：`application/src/go_hotel/api/routes/fare.py:52`；模式：ASYNC；优先级：P1。
- 提交前失败：Isolation, ownership, quote hash/consent/expiry/current facts and change-window checks before operation commit; existing operation returns persisted public state.
- 提交后或结果不明：Operation+order claim and pending order commit before advance; supplier or authorization may succeed before local finalization. HTTP/domain validation error may follow those commits.
- 现有持久键：CatalogCashFareOperation.quote_id -> operation_id; CatalogCashFareClaim.order_id; frozen plan hash; downstream operation-prefixed money keys.
- 最小恢复接点：Lookup operation by exact quote/actor/payload; use existing catalog_cash_fare_execution.reconcile/retry_payment APIs as appropriate. Never start a new cancellation/change quote for transport retry.

## C11-CALL-13 — stay_credit_convert / convert_to_stay_credit

- 调用位置：`application/src/go_hotel/api/routes/fare.py:75`；模式：ASYNC；优先级：P1。
- 提交前失败：Quote/consent/order/current value/window checks before Credit/Contract/source reservation commit.
- 提交后或结果不明：Credit CANCEL_PENDING/source funds reserved before supplier cancel. Cancellation can succeed before activate reports changed source order; pending/UNKNOWN_CANCEL remains durable.
- 现有持久键：StayCredit.original_order_id -> stay_credit_id; credit contract quote_id+accepted_by+contract_hash.
- 最小恢复接点：Read existing credit and reconcile_conversion using supplier status; activate exact reserved source only with proof. Never issue a second credit or cancel again due solely to HTTP failure.

## C11-CALL-14 — stay_credit_redeem / redeem

- 调用位置：`application/src/go_hotel/api/routes/fare.py:86`；模式：ASYNC；优先级：P1。
- 提交前失败：Traveler consent check may precede release, but release_traveler commits disclosure before later quote/value validation. Do not certify callback-wide no effects merely from stale quote.
- 提交后或结果不明：Allocation+credit value reservation commit before supplier prebook and booking; later funding/book/finalization may fail independently.
- 现有持久键：Allocation.quote_id -> order_id; request_hash; credit-prebook:{order_id}, credit-book:{order_id}; profile release_id.
- 最小恢复接点：Recover same allocation and use reconcile_redemption/resume_redemption; verify existing prebook/book outcome and journal. Restore value only via existing definitive-failure path, never on timeout alone.

## C11-CALL-18 — FLIGHT_REFUND / refund

- 调用位置：`application/src/go_hotel/api/routes/flight.py:91`；模式：SYNC；优先级：P1。
- 提交前失败：Order ownership/status, fare policy and frozen consent checks before initial refund commit. Existing pending refund must be resumed, not classified safe by exception.
- 提交后或结果不明：REFUND_PENDING+consent+refund row commit before money. Money can confirm before later consent/state/projection error; a ValueError is potentially post-effect.
- 现有持久键：Order/refund row and frozen consent; flight-refund:{order_id} plus deterministic component keys across original/change captures.
- 最小恢复接点：Resume the same pending refund and existing money roots; verify confirmed amount/currency/root receipts, then finalize row/projection and HTTP replay. Never create a new refund key.

## C11-CALL-19 — FLIGHT_ADMIN_EXTERNAL_STATE / admin_external_state

- 调用位置：`application/src/go_hotel/api/routes/flight.py:96`；模式：SYNC；优先级：P1。
- 提交前失败：Actor/evidence, owned order/quote, tickets and decision checks; only pre-effect validated rejection can release.
- 提交后或结果不明：Managed resolution persists decision/lease before capture or release, then state commit. Legacy branch may call capture/release before final transaction validations.
- 现有持久键：Managed FlightChangeResolutionRow/quote_id+request hash; FLIGHT_CHANGE root; fixed change-cap/change-release keys. Legacy order_id/evidence has weaker resolution identity.
- 最小恢复接点：Prefer explicit quote_id managed reconcile; recover same frozen decision and receipts. Conflicting decisions reject; never reverse a confirmed capture merely because HTTP response failed.

## C11-CALL-20 — FLIGHT_REFUND_CONFIRMED / refund_confirmed

- 调用位置：`application/src/go_hotel/api/routes/flight.py:101`；模式：SYNC；优先级：P1。
- 提交前失败：Order ownership/status, fare policy and frozen consent checks before initial refund commit. Existing pending refund must be resumed, not classified safe by exception.
- 提交后或结果不明：REFUND_PENDING+consent+refund row commit before money. Money can confirm before later consent/state/projection error; a ValueError is potentially post-effect.
- 现有持久键：Order/refund row and frozen consent; flight-refund:{order_id} plus deterministic component keys across original/change captures.
- 最小恢复接点：Resume the same pending refund and existing money roots; verify confirmed amount/currency/root receipts, then finalize row/projection and HTTP replay. Never create a new refund key.

## C11-CALL-21 — cancel / mobile_cancel

- 调用位置：`application/src/go_hotel/api/routes/mobile.py:110`；模式：ASYNC；优先级：P1。
- 提交前失败：Isolation, ownership, quote hash/consent/expiry/current facts and change-window checks before operation commit; existing operation returns persisted public state.
- 提交后或结果不明：Operation+order claim and pending order commit before advance; supplier or authorization may succeed before local finalization. HTTP/domain validation error may follow those commits.
- 现有持久键：CatalogCashFareOperation.quote_id -> operation_id; CatalogCashFareClaim.order_id; frozen plan hash; downstream operation-prefixed money keys.
- 最小恢复接点：Lookup operation by exact quote/actor/payload; use existing catalog_cash_fare_execution.reconcile/retry_payment APIs as appropriate. Never start a new cancellation/change quote for transport retry.

## C11-CALL-22 — change / mobile_change

- 调用位置：`application/src/go_hotel/api/routes/mobile.py:128`；模式：ASYNC；优先级：P1。
- 提交前失败：Isolation, ownership, quote hash/consent/expiry/current facts and change-window checks before operation commit; existing operation returns persisted public state.
- 提交后或结果不明：Operation+order claim and pending order commit before advance; supplier or authorization may succeed before local finalization. HTTP/domain validation error may follow those commits.
- 现有持久键：CatalogCashFareOperation.quote_id -> operation_id; CatalogCashFareClaim.order_id; frozen plan hash; downstream operation-prefixed money keys.
- 最小恢复接点：Lookup operation by exact quote/actor/payload; use existing catalog_cash_fare_execution.reconcile/retry_payment APIs as appropriate. Never start a new cancellation/change quote for transport retry.

## C11-CALL-23 — stay_credit_convert / mobile_convert_stay_credit

- 调用位置：`application/src/go_hotel/api/routes/mobile.py:158`；模式：ASYNC；优先级：P1。
- 提交前失败：Quote/consent/order/current value/window checks before Credit/Contract/source reservation commit.
- 提交后或结果不明：Credit CANCEL_PENDING/source funds reserved before supplier cancel. Cancellation can succeed before activate reports changed source order; pending/UNKNOWN_CANCEL remains durable.
- 现有持久键：StayCredit.original_order_id -> stay_credit_id; credit contract quote_id+accepted_by+contract_hash.
- 最小恢复接点：Read existing credit and reconcile_conversion using supplier status; activate exact reserved source only with proof. Never issue a second credit or cancel again due solely to HTTP failure.

## C11-CALL-26 — MOBILITY_MODIFY / modify

- 调用位置：`application/src/go_hotel/api/routes/mobility.py:66`；模式：SYNC；优先级：P1。
- 提交前失败：Owned confirmed order and rental unchanged-duration rule checked in local transaction before commit.
- 提交后或结果不明：Commit acknowledgement loss can leave new pickup time and event committed. Re-entry may duplicate audit even when scalar value is unchanged.
- 现有持久键：order_id+accepted new_time and existing event; no reviewed unique modification-operation row. HTTP key is current request fence.
- 最小恢复接点：Bind exact operation to projection/event; verify committed new_time and expected prior version before constructing replay. Rollback-known pre-write failure may release.

## C11-CALL-27 — MOBILITY_REFUND_CONFIRMED / refund_confirmed

- 调用位置：`application/src/go_hotel/api/routes/mobility.py:72`；模式：SYNC；优先级：P1。
- 提交前失败：Ownership/status/accepted refund hash and frozen plan checks before first refund commit; existing pending/completed refund has exact consent checks.
- 提交后或结果不明：Refund row+order pending commit before money. Receipt/state validation can fail after confirmed refund and must retain identity.
- 现有持久键：RIDE: refund row/order and ride-refund:{order_id}; RENTAL: refund_id with frozen settlement_plan_json and rental-cancel:{refund_id} component keys.
- 最小恢复接点：Recover frozen refund and same plan; verify owner/root/currency/amount receipts before finalizing. Keep quote consent fixed; never derive a new amount or refund key on retry.

## C11-CALL-28 — MOBILITY_CANCEL / cancel

- 调用位置：`application/src/go_hotel/api/routes/mobility.py:75`；模式：SYNC；优先级：P1。
- 提交前失败：Ownership/status/accepted refund hash and frozen plan checks before first refund commit; existing pending/completed refund has exact consent checks.
- 提交后或结果不明：Refund row+order pending commit before money. Receipt/state validation can fail after confirmed refund and must retain identity.
- 现有持久键：RIDE: refund row/order and ride-refund:{order_id}; RENTAL: refund_id with frozen settlement_plan_json and rental-cancel:{refund_id} component keys.
- 最小恢复接点：Recover frozen refund and same plan; verify owner/root/currency/amount receipts before finalizing. Keep quote consent fixed; never derive a new amount or refund key on retry.

## C11-CALL-29 — MOBILITY_FULFILLMENT / fulfill

- 调用位置：`application/src/go_hotel/api/routes/mobility.py:78`；模式：SYNC；优先级：P1。
- 提交前失败：Evidence, ownership and legal source/target transition checked before local commit.
- 提交后或结果不明：Transition, event and lifecycle commit may precede lost acknowledgement. Retry of START/COMPLETE/PICKUP/RETURN can reject because state already advanced.
- 现有持久键：order_id+action+evidence_reference; persisted lifecycle/event, but event uniqueness must be verified before claiming replay.
- 最小恢复接点：Lookup exact operation/evidence and resulting transition; replay success only with same actor/expected prior state. Do not repeat transition or invent evidence.

## C11-CALL-30 — MOBILITY_ADMIN_EXTERNAL_STATE / external_state

- 调用位置：`application/src/go_hotel/api/routes/mobility.py:81`；模式：SYNC；优先级：P1。
- 提交前失败：Actor/evidence/state/previous state validation before local mutation.
- 提交后或结果不明：Restoration/FAILED/UNKNOWN transition and event commit can be acknowledged ambiguously; re-entry may conflict with already restored state.
- 现有持久键：order_id+decision+evidence_reference; stored previous_status in unknown event; outer HTTP key.
- 最小恢复接点：Recover exact decision and prior-state event; idempotent replay requires operation/evidence binding. Do not infer CONFIRMED if preserved prior state was IN_PROGRESS.

## C11-CALL-31 — RAIL_PREBOOK / prebook

- 调用位置：`application/src/go_hotel/api/routes/rail.py:45`；模式：SYNC；优先级：P1。
- 提交前失败：Party count, offer expiry/currency and capacity observation validated within transaction before issue_in; rollback-known local error can be safe.
- 提交后或结果不明：Contract/prebook commit acknowledgement can be lost. Subsequent key release can issue another prebook; current prebook does not reserve inventory.
- 现有持久键：Generated prebook_id/VerticalPrebookContractRow and terms hash; no reviewed atomic outer HTTP key->prebook_id binding.
- 最小恢复接点：Persist generated prebook resource binding in claim transaction or add exact request-operation record; recover same prebook without issuing again.

## C11-CALL-32 — RAIL_CREATE_ORDER / create_order

- 调用位置：`application/src/go_hotel/api/routes/rail.py:56`；模式：SYNC；优先级：P1。
- 提交前失败：Prebook owner/request/terms/passenger validations inside order transaction; vault releases can already have committed outside it.
- 提交后或结果不明：Order+capacity+consumed contract commit precedes route vault-evidence commit. Late evidence error leaves a real order even if HTTP claim is released.
- 现有持久键：Consumed VerticalPrebookContractRow prebook_id -> order_id plus owner/consumed request hash; outer HTTP claim key; vault release_ids.
- 最小恢复接点：Recover exact consumed contract and replay its order; retry only missing evidence using durable release identities. Do not repeat disclosure or reserve capacity.

## C11-CALL-33 — RAIL_CHECKOUT / checkout

- 调用位置：`application/src/go_hotel/api/routes/rail.py:60`；模式：SYNC；优先级：P1。
- 提交前失败：Owned order and reservation payment guard before payment-method transaction; persistent reservation state must be inspected for retry.
- 提交后或结果不明：Payment method/reservation guard transaction commits before bridge; capture may be durable before final order state commit.
- 现有持久键：RAIL_ORDER/order_id; rail-checkout:{order_id}, rail-auth:{order_id}, rail-cap:{order_id}; reservation expiry row.
- 最小恢复接点：Recover same payment root and reservation state; verify receipts then project order. Do not re-reserve or revive an expired reservation.

## C11-CALL-34 — RAIL_EXECUTE_CHANGE / execute_change

- 调用位置：`application/src/go_hotel/api/routes/rail.py:70`；模式：SYNC；优先级：P1。
- 提交前失败：Order/quote/expiry/target capacity validation precedes preparing transaction commit.
- 提交后或结果不明：Capacity preparation+PREPARING/CHANGE_PENDING commit before adjustment; second transaction validation can fail after auth.
- 现有持久键：quote_id, prepared capacity claim, RAIL_CHANGE/quote_id, rail-change-intent/auth/cap/release:{quote_id}.
- 最小恢复接点：Resume same PREPARING quote and target capacity; use rail_change_resolution for eventual supplier-confirmed capture/release and capacity completion.

## C11-CALL-35 — RAIL_REFUND / refund

- 调用位置：`application/src/go_hotel/api/routes/rail.py:76`；模式：SYNC；优先级：P1。
- 提交前失败：Owned order, frozen quote/consent, amount checks before operation/lease commit; already-processing error means existing effect scope.
- 提交后或结果不明：Operation/order REFUND_PENDING+lease commit before money; failed money or lost lease can follow committed refund. Error path releases only domain lease, not frozen operation.
- 现有持久键：VerticalRefundOperation(vertical=RAIL,order_id), request_hash+lease_token; rail-refund:{order_id} and component money keys.
- 最小恢复接点：Reconcile fixed money keys; reacquire expired domain lease; verify durable receipts and finalize existing operation, then resolve HTTP claim.

## C11-CALL-36 — RAIL_ADMIN_EXTERNAL_STATE / admin_external_state

- 调用位置：`application/src/go_hotel/api/routes/rail.py:81`；模式：SYNC；优先级：P1。
- 提交前失败：Actor/evidence, quote_id, frozen request and supplier-reference/ticket validation before resolution lease commit.
- 提交后或结果不明：Resolution decision/lease commits before capture/release; local finalize/lease conflict may follow money.
- 现有持久键：RailChangeResolutionRow keyed quote_id with request_hash+lease_token; RAIL_CHANGE root and fixed cap/release keys.
- 最小恢复接点：Resume same frozen resolution by quote_id; reject conflicting late reply; verify money receipt then complete capacity/order projection.

## C11-CALL-37 — RAIL_REFUND_CONFIRMED / refund_confirmed

- 调用位置：`application/src/go_hotel/api/routes/rail.py:86`；模式：SYNC；优先级：P1。
- 提交前失败：Owned order, frozen quote/consent, amount checks before operation/lease commit; already-processing error means existing effect scope.
- 提交后或结果不明：Operation/order REFUND_PENDING+lease commit before money; failed money or lost lease can follow committed refund. Error path releases only domain lease, not frozen operation.
- 现有持久键：VerticalRefundOperation(vertical=RAIL,order_id), request_hash+lease_token; rail-refund:{order_id} and component money keys.
- 最小恢复接点：Reconcile fixed money keys; reacquire expired domain lease; verify durable receipts and finalize existing operation, then resolve HTTP claim.
