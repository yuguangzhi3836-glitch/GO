import ast,hashlib,json,datetime
from pathlib import Path
root=Path(__file__).resolve().parents[4]
base=root/'application/src/go_hotel'
out=root/'evidence/v70-round2-20260914/c11/followup'
S={}
def spec(names,category,pre,post,keys,recovery,sources,priority='P1'):
 for name in names.split('|'):
  S[name]={'classification':category,'precommit_failure_boundary':pre,'postcommit_or_uncertain_boundary':post,'available_durable_keys':keys,'minimal_recovery_hook':recovery,'review_sources':sources.split('|'),'priority':priority}
spec('FLIGHT_CHECKOUT','MULTI_TRANSACTION_PAYMENT',
 'production_truth_required and owned order lookup precede first mutation; safe retry only if validation failed before mutation/bridge and rollback is positively known.',
 'checkout commits PAYMENT_AUTHORIZED/payment_method before bridge. Source decision, intent, authorization and capture have their own commits. Later projection or bridge errors may follow money effects.',
 'Known order_id; payment business root FLIGHT_ORDER/order_id; flight-checkout:{order_id}, flight-auth:{order_id}, flight-cap:{order_id}.',
 'Read payment root and confirmed money receipts; resume the same checkout_contract only for known states. UNKNOWN_EXTERNAL_STATE stays fenced. Project existing capture into order and complete HTTP claim after verified outcome.',
 'flight/service.py|services/vertical_transaction_bridge.py|services/omnichannel_payment.py|services/unified_money_movement.py','P0')
spec('FLIGHT_EXECUTE_CHANGE','MULTI_TRANSACTION_ADJUSTMENT',
 'Owned order/quote, checked plan, explicit consent, status and expiry validations before first authorization-requested commit. Existing resumed state is not evidence of a fresh no-effect invocation.',
 'First commit freezes AUTHORIZATION_PENDING/UNKNOWN_EXTERNAL_STATE and supersedes other quotes. prepare_adjustment can commit intent/auth; subsequent released/conflict ValueError occurs after this boundary. Second commit sets PENDING_SUPPLIER.',
 'order_id+quote_id and frozen change plan; FLIGHT_CHANGE/quote_id; flight-change-intent:{quote_id}, flight-change-auth:{quote_id}, flight-change-cap:{quote_id}, flight-change-release:{quote_id}; resolution row keyed quote_id.',
 'Use quote and payment root to resume authorization preparation; never create new quote/root for retry. Keep pending supplier state. Capture/release only via reviewed flight_change_resolution.reconcile with supplier evidence, not as generic exception compensation.',
 'flight/service.py|flight/changes.py|services/vertical_money_bridge.py|services/flight_change_resolution.py','P0')
spec('FLIGHT_CREATE_ORDER','CREATE_UNBOUND_PLUS_VAULT',
 'Duplicate traveler/raw reference and prebook/passenger validations can precede order commit, but earlier travelers may already have durable vault releases. HTTP/ValueError alone proves no rollback.',
 'Vault release(s), order commit and route vault-evidence commit are separate. New random order_id is not bound atomically to HTTP claim; post-commit response/audit failure can re-enter creation.',
 'HTTP operation/key+payload hash exists; generated order_id and prebook_id are searchable evidence, but no atomic HTTP-claim-to-order mapping was found in reviewed creation path.',
 'Introduce a durable creation-operation/resource binding before or atomically with creation; recover order by that exact binding. Deduplicate subsequent vault-evidence write. Do not infer a unique prior order from similar payload.',
 'flight/service.py|services/booking_data_release.py|api/routes/flight.py','P0')
spec('FLIGHT_REFUND|FLIGHT_REFUND_CONFIRMED','FROZEN_REFUND_MULTI_STAGE',
 'Order ownership/status, fare policy and frozen consent checks before initial refund commit. Existing pending refund must be resumed, not classified safe by exception.',
 'REFUND_PENDING+consent+refund row commit before money. Money can confirm before later consent/state/projection error; a ValueError is potentially post-effect.',
 'Order/refund row and frozen consent; flight-refund:{order_id} plus deterministic component keys across original/change captures.',
 'Resume the same pending refund and existing money roots; verify confirmed amount/currency/root receipts, then finalize row/projection and HTTP replay. Never create a new refund key.',
 'flight/service.py|services/flight_refund_consent.py|services/vertical_money_bridge.py')
spec('FLIGHT_ADMIN_EXTERNAL_STATE','SUPPLIER_RESOLUTION_WITH_MONEY',
 'Actor/evidence, owned order/quote, tickets and decision checks; only pre-effect validated rejection can release.',
 'Managed resolution persists decision/lease before capture or release, then state commit. Legacy branch may call capture/release before final transaction validations.',
 'Managed FlightChangeResolutionRow/quote_id+request hash; FLIGHT_CHANGE root; fixed change-cap/change-release keys. Legacy order_id/evidence has weaker resolution identity.',
 'Prefer explicit quote_id managed reconcile; recover same frozen decision and receipts. Conflicting decisions reject; never reverse a confirmed capture merely because HTTP response failed.',
 'flight/service.py|services/flight_change_resolution.py|services/vertical_money_bridge.py')
spec('RAIL_PREBOOK','LOCAL_PREBOOK_GENERATION',
 'Party count, offer expiry/currency and capacity observation validated within transaction before issue_in; rollback-known local error can be safe.',
 'Contract/prebook commit acknowledgement can be lost. Subsequent key release can issue another prebook; current prebook does not reserve inventory.',
 'Generated prebook_id/VerticalPrebookContractRow and terms hash; no reviewed atomic outer HTTP key->prebook_id binding.',
 'Persist generated prebook resource binding in claim transaction or add exact request-operation record; recover same prebook without issuing again.',
 'rail/service.py|services/vertical_prebook_contract.py|services/vertical_capacity.py')
spec('RAIL_CREATE_ORDER','CONSUMED_PREBOOK_PLUS_VAULT',
 'Prebook owner/request/terms/passenger validations inside order transaction; vault releases can already have committed outside it.',
 'Order+capacity+consumed contract commit precedes route vault-evidence commit. Late evidence error leaves a real order even if HTTP claim is released.',
 'Consumed VerticalPrebookContractRow prebook_id -> order_id plus owner/consumed request hash; outer HTTP claim key; vault release_ids.',
 'Recover exact consumed contract and replay its order; retry only missing evidence using durable release identities. Do not repeat disclosure or reserve capacity.',
 'rail/service.py|services/vertical_prebook_contract.py|services/booking_data_release.py')
spec('RAIL_CHECKOUT','MULTI_TRANSACTION_PAYMENT',
 'Owned order and reservation payment guard before payment-method transaction; persistent reservation state must be inspected for retry.',
 'Payment method/reservation guard transaction commits before bridge; capture may be durable before final order state commit.',
 'RAIL_ORDER/order_id; rail-checkout:{order_id}, rail-auth:{order_id}, rail-cap:{order_id}; reservation expiry row.',
 'Recover same payment root and reservation state; verify receipts then project order. Do not re-reserve or revive an expired reservation.',
 'rail/service.py|services/vertical_transaction_bridge.py|services/vertical_reservation_expiry.py')
spec('RAIL_EXECUTE_CHANGE','RESERVED_CAPACITY_AND_ADJUSTMENT',
 'Order/quote/expiry/target capacity validation precedes preparing transaction commit.',
 'Capacity preparation+PREPARING/CHANGE_PENDING commit before adjustment; second transaction validation can fail after auth.',
 'quote_id, prepared capacity claim, RAIL_CHANGE/quote_id, rail-change-intent/auth/cap/release:{quote_id}.',
 'Resume same PREPARING quote and target capacity; use rail_change_resolution for eventual supplier-confirmed capture/release and capacity completion.',
 'rail/service.py|services/vertical_capacity.py|services/vertical_money_bridge.py|services/rail_change_resolution.py')
spec('RAIL_REFUND|RAIL_REFUND_CONFIRMED','LEASED_FROZEN_REFUND',
 'Owned order, frozen quote/consent, amount checks before operation/lease commit; already-processing error means existing effect scope.',
 'Operation/order REFUND_PENDING+lease commit before money; failed money or lost lease can follow committed refund. Error path releases only domain lease, not frozen operation.',
 'VerticalRefundOperation(vertical=RAIL,order_id), request_hash+lease_token; rail-refund:{order_id} and component money keys.',
 'Reconcile fixed money keys; reacquire expired domain lease; verify durable receipts and finalize existing operation, then resolve HTTP claim.',
 'services/vertical_refund_recovery.py|services/vertical_money_bridge.py|rail/service.py')
spec('RAIL_ADMIN_EXTERNAL_STATE','LEASED_SUPPLIER_RESOLUTION',
 'Actor/evidence, quote_id, frozen request and supplier-reference/ticket validation before resolution lease commit.',
 'Resolution decision/lease commits before capture/release; local finalize/lease conflict may follow money.',
 'RailChangeResolutionRow keyed quote_id with request_hash+lease_token; RAIL_CHANGE root and fixed cap/release keys.',
 'Resume same frozen resolution by quote_id; reject conflicting late reply; verify money receipt then complete capacity/order projection.',
 'services/rail_change_resolution.py|services/vertical_money_bridge.py|services/vertical_capacity.py')
spec('cancel|change','HOTEL_CASH_FARE_OPERATION',
 'Isolation, ownership, quote hash/consent/expiry/current facts and change-window checks before operation commit; existing operation returns persisted public state.',
 'Operation+order claim and pending order commit before advance; supplier or authorization may succeed before local finalization. HTTP/domain validation error may follow those commits.',
 'CatalogCashFareOperation.quote_id -> operation_id; CatalogCashFareClaim.order_id; frozen plan hash; downstream operation-prefixed money keys.',
 'Lookup operation by exact quote/actor/payload; use existing catalog_cash_fare_execution.reconcile/retry_payment APIs as appropriate. Never start a new cancellation/change quote for transport retry.',
 'fare/service.py|services/catalog_cash_fare_execution.py|services/catalog_cash_fare.py')
spec('stay_credit_convert','CREDIT_CONVERSION_AND_SUPPLIER_CANCEL',
 'Quote/consent/order/current value/window checks before Credit/Contract/source reservation commit.',
 'Credit CANCEL_PENDING/source funds reserved before supplier cancel. Cancellation can succeed before activate reports changed source order; pending/UNKNOWN_CANCEL remains durable.',
 'StayCredit.original_order_id -> stay_credit_id; credit contract quote_id+accepted_by+contract_hash.',
 'Read existing credit and reconcile_conversion using supplier status; activate exact reserved source only with proof. Never issue a second credit or cancel again due solely to HTTP failure.',
 'services/catalog_stay_credit.py|fare/service.py')
spec('stay_credit_redeem','CREDIT_ALLOCATION_PLUS_VAULT',
 'Traveler consent check may precede release, but release_traveler commits disclosure before later quote/value validation. Do not certify callback-wide no effects merely from stale quote.',
 'Allocation+credit value reservation commit before supplier prebook and booking; later funding/book/finalization may fail independently.',
 'Allocation.quote_id -> order_id; request_hash; credit-prebook:{order_id}, credit-book:{order_id}; profile release_id.',
 'Recover same allocation and use reconcile_redemption/resume_redemption; verify existing prebook/book outcome and journal. Restore value only via existing definitive-failure path, never on timeout alone.',
 'services/catalog_stay_credit.py|services/catalog_credit_value.py|api/routes/fare.py')
spec('RIDE_CREATE_ORDER|RENTAL_CREATE_ORDER','CREATE_UNBOUND_PLUS_SOURCE_AND_VAULT',
 'Offer/date/client-policy validation precedes order transaction, but route vault release may already have durable side effects.',
 'Random order row/policy/reservation commits before source-runtime decision and separate vault-evidence transaction. No atomic outer-claim resource mapping found.',
 'HTTP operation/key+payload hash; generated order_id and reservation/policy records. Same offer/time/account is not a unique operation key.',
 'Add explicit claim->planned resource binding at order creation, then replay that row and complete missing source/evidence writes. No duplicate order creation from a new random ID.',
 'mobility/ride/service.py|mobility/rental/service.py|services/booking_data_release.py|services/vertical_source_runtime.py','P0')
spec('MOBILITY_MODIFY','LOCAL_SINGLE_TRANSACTION',
 'Owned confirmed order and rental unchanged-duration rule checked in local transaction before commit.',
 'Commit acknowledgement loss can leave new pickup time and event committed. Re-entry may duplicate audit even when scalar value is unchanged.',
 'order_id+accepted new_time and existing event; no reviewed unique modification-operation row. HTTP key is current request fence.',
 'Bind exact operation to projection/event; verify committed new_time and expected prior version before constructing replay. Rollback-known pre-write failure may release.',
 'mobility/ride/service.py|mobility/rental/service.py')
spec('MOBILITY_CANCEL|MOBILITY_REFUND_CONFIRMED','FROZEN_MOBILITY_REFUND',
 'Ownership/status/accepted refund hash and frozen plan checks before first refund commit; existing pending/completed refund has exact consent checks.',
 'Refund row+order pending commit before money. Receipt/state validation can fail after confirmed refund and must retain identity.',
 'RIDE: refund row/order and ride-refund:{order_id}; RENTAL: refund_id with frozen settlement_plan_json and rental-cancel:{refund_id} component keys.',
 'Recover frozen refund and same plan; verify owner/root/currency/amount receipts before finalizing. Keep quote consent fixed; never derive a new amount or refund key on retry.',
 'mobility/ride/refunds.py|mobility/rental/service.py|services/vertical_money_bridge.py|services/mobility_refund_consent.py')
spec('MOBILITY_FULFILLMENT','LOCAL_STATE_TRANSITION',
 'Evidence, ownership and legal source/target transition checked before local commit.',
 'Transition, event and lifecycle commit may precede lost acknowledgement. Retry of START/COMPLETE/PICKUP/RETURN can reject because state already advanced.',
 'order_id+action+evidence_reference; persisted lifecycle/event, but event uniqueness must be verified before claiming replay.',
 'Lookup exact operation/evidence and resulting transition; replay success only with same actor/expected prior state. Do not repeat transition or invent evidence.',
 'mobility/ride/service.py|mobility/rental/service.py')
spec('MOBILITY_ADMIN_EXTERNAL_STATE','LOCAL_SUPPLIER_STATE_TRANSITION',
 'Actor/evidence/state/previous state validation before local mutation.',
 'Restoration/FAILED/UNKNOWN transition and event commit can be acknowledged ambiguously; re-entry may conflict with already restored state.',
 'order_id+decision+evidence_reference; stored previous_status in unknown event; outer HTTP key.',
 'Recover exact decision and prior-state event; idempotent replay requires operation/evidence binding. Do not infer CONFIRMED if preserved prior state was IN_PROGRESS.',
 'mobility/ride/service.py|mobility/rental/service.py')
spec('ATTRACTION_PREBOOK','LOCAL_PREBOOK_GENERATION',
 'Party/catalog/date/session/currency and capacity validation before issue_in transaction commit.',
 'Prebook contract commit acknowledgement loss may issue a second contract when outer claim is released; no inventory reservation at this stage.',
 'Generated VerticalPrebookContractRow.prebook_id and terms hash; no reviewed outer claim->prebook mapping.',
 'Persist resource binding and recover the existing exact contract rather than issue another. Do not treat availability observation as reserved inventory.',
 'attractions/service.py|services/vertical_prebook_contract.py|services/vertical_capacity.py')
spec('ATTRACTION_CREATE_ORDER','CONSUMED_PREBOOK_PLUS_SOURCE_AND_VAULT',
 'Prebook/owner/request/party/product/stock validations inside order transaction; earlier vault releases are separate.',
 'Order+capacity+consumed contract commit before source-runtime decision and route vault-evidence write.',
 'Consumed prebook_id -> order_id with request hash/owner; source decision for order; vault release_ids.',
 'Recover via exact consumed contract; fill missing source/evidence without creating order or reserving stock again.',
 'attractions/service.py|services/vertical_prebook_contract.py|services/vertical_capacity.py|services/booking_data_release.py')
spec('ATTRACTION_EXECUTE_CHANGE','LOCAL_CAPACITY_STATE_TRANSITION',
 'Owned confirmed order, QUOTED+unexpired quote and target capacity checks before atomic commit.',
 'Prepared capacity+quote PENDING_SUPPLIER+order UNKNOWN commit may survive acknowledgement loss; direct retry currently expects QUOTED and can conflict.',
 'order_id+quote_id and prepared capacity claim; pending quote; outer HTTP key.',
 'Recover same pending quote and capacity reservation; await supplier fact. Do not create new quote or claim; complete/release capacity only on definitive supplier decision.',
 'attractions/service.py|services/vertical_capacity.py')
spec('ATTRACTION_REFUND|ATTRACTION_REFUND_CONFIRMED','LEASED_FROZEN_REFUND',
 'Owned order, consumed terms, accepted quote and positive refund validations before frozen operation/lease commit.',
 'REFUND_PENDING operation/lease commit before refund; lost receipt/lease/finalize error can be post-money.',
 'VerticalRefundOperation(ATTRACTION,order_id), request hash/lease; attraction-refund:{order_id}.',
 'Use same operation/lease and fixed money key, verify durable receipts, finalize order/capacity and replay HTTP outcome.',
 'services/vertical_refund_recovery.py|attractions/service.py|services/vertical_money_bridge.py')
spec('ATTRACTION_REDEEM','LOCAL_VOUCHER_STATE_TRANSITION',
 'Evidence, ownership and CONFIRMED source state validated before transaction commit.',
 'FULFILLED+VOUCHER_REDEEMED event/lifecycle commit may survive ack loss; retry no longer sees CONFIRMED.',
 'order_id+evidence_reference and stored voucher/supplier reference in event; outer HTTP key.',
 'Replay only if exact redemption evidence matches committed transition; do not re-redeem or infer voucher success from order status alone.',
 'attractions/service.py')
spec('ATTRACTION_ADMIN_EXTERNAL_STATE','LOCAL_SUPPLIER_CAPACITY_RESOLUTION',
 'Actor/evidence/state and pending supplier/voucher reference checks before local commit.',
 'Capacity complete/release and pending quote/order transition are committed atomically; ack loss can leave definitive state before route error.',
 'order_id+pending quote_id (not explicit API argument)+evidence_reference; capacity claim. A newer pending quote can make historical response ambiguous.',
 'Bind explicit resolution identity to quote/evidence before replay; inspect persisted decision and voucher. Never apply an old response to a newer pending quote.',
 'attractions/service.py|services/vertical_capacity.py')
spec('CONSUMER_HOTEL_CREATE','CREATE_UNBOUND_PLUS_VAULT',
 'Fare consent preflight before vault release; booking consistency/fare snapshot validated in order transaction, but disclosure may already be durable.',
 'Order/event/fare-snapshot commit before separate vault-evidence and response; random order_id not atomically bound to HTTP claim in reviewed path.',
 'HTTP operation/key/hash; generated order_id, prebook_id and immutable fare snapshot. Reviewed create_order_with_event has no claim binding.',
 'Reserve exact creation resource identity and atomically bind to claim/order event; recover same order/snapshot, append missing evidence once. Do not match by price/name.',
 'api/routes/consumer_identity.py|services/booking.py|repositories/sql.py|services/booking_data_release.py','P0')
spec('CONSUMER_EXPLICIT_CHECKOUT','SIX_VERTICAL_MULTI_STAGE_PAYMENT',
 'Environment/vertical/owner/expected amount/currency/payable status checked before outer claim. In callback, existing fulfillment unknown-state checks may refer to prior side effects.',
 'Hotel authorization/book/capture or vertical root/movements/supplier fulfillment each have durable steps. Late fulfillment/projection or HTTPException may follow capture.',
 'order_id; hotel ExternalOperation operation_id fences; other vertical fixed checkout/auth/cap keys, payment root and supplier_fulfillment_id.',
 'Resolve per-vertical canonical payment+supplier outcome via existing recovery hooks; replay verified final response or pending state without new payment, source choice or booking.',
 'api/routes/consumer_checkout.py|services/booking.py|services/vertical_transaction_bridge.py|services/order_supplier_fulfillment.py','P0')
spec('supplier_unable_to_fulfill','DURABLE_CASE_PLUS_LATE_AUDIT',
 'Supplier ownership before wrapper; reason/evidence validation and exact request checks before case/plan commit.',
 'Case/plan/event commit before route audit_service.append. Audit failure can follow a successfully registered cancellation request; no money is executed by this request function.',
 'SupplierFaultCase.order_id -> case_id; CatalogSupplierRemedy request_hash binds supplier/cause/evidence/requester.',
 'Recover same case by exact request hash, append missing request audit idempotently; do not call remedy.execute or refund merely to repair an HTTP response.',
 'api/routes/compensation.py|compensation/service.py|services/catalog_supplier_remedy.py')
rows=[]
for file in sorted((base/'api/routes').glob('*.py')):
 text=file.read_text();tree=ast.parse(text)
 for fn in tree.body:
  if not isinstance(fn,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
  for call in ast.walk(fn):
   if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Name) or call.func.id not in {'run_idempotent','run_idempotent_async'}:continue
   op=ast.literal_eval(call.args[0]);assert op in S,op
   route=[]
   for d in fn.decorator_list:
    if isinstance(d,ast.Call) and d.args and isinstance(d.args[0],ast.Constant):route.append(d.args[0].value)
   rows.append({'id':f'C11-CALL-{len(rows)+1:02d}','operation':op,'mode':'ASYNC' if call.func.id.endswith('_async') else 'SYNC','route_file':str(file.relative_to(root)),'function':fn.name,'call_line':call.lineno,'route':route,'callback':ast.get_source_segment(text,call.args[3]),**S[op]})
assert len(rows)==37,len(rows)
review_files={row['route_file'] for row in rows}
for row in rows:
 for ref in row['review_sources']:
  p=base/ref;assert p.exists(),p
  review_files.add(str(p.relative_to(root)))
review_files.update('application/src/go_hotel/'+s for s in ['api/idempotency.py','db/models.py','services/vertical_transaction_bridge.py','services/vertical_money_bridge.py','services/flight_change_resolution.py','services/rail_change_resolution.py'])
sources={path:hashlib.sha256((root/path).read_bytes()).hexdigest() for path in sorted(review_files)}
record={'task_id':'V70-R2-C11-02','source_anchor':'fef9c748adb77d37ba5d4dc4fa4662eb668303a1','source_basis':'Frozen round-two local candidate derived from anchor; actual reviewed bytes bound by manifest. Not a claim of pristine main bytes.','mode':'STATIC_REVIEW_ONLY','callsite_count':len(rows),'distinct_operations':len(set(r['operation'] for r in rows)),'route_file_count':len(set(r['route_file'] for r in rows)),'rows':rows}
(out/'CALLBACK_INVENTORY.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
(out/'SOURCE_SHA256.json').write_text(json.dumps(sources,indent=2)+'\n')
md=['# 37处幂等 callback 静态分类','',f'任务：V70-R2-C11-02。{len(rows)}处调用 / {record["distinct_operations"]}个operation / {record["route_file_count"]}个路由文件。','', '这是静态分类与候选设计，不是运行验收。每个事务提交都存在“服务端已提交、调用方未收到确认”的边界；不能把 ValueError、HTTP 4xx 或本地回滚等同于“没有发生过副作用”。具体审阅文件指纹见 SOURCE_SHA256.json。','']
for row in sorted(rows,key=lambda r:(r['priority'],0 if r['operation'] in ['FLIGHT_CHECKOUT','FLIGHT_EXECUTE_CHANGE'] else 1,r['id'])):
 md += [f'## {row["id"]} — {row["operation"]} / {row["function"]}', '',f'- 调用位置：`{row["route_file"]}:{row["call_line"]}`；模式：{row["mode"]}；优先级：{row["priority"]}。',f'- 提交前失败：{row["precommit_failure_boundary"]}',f'- 提交后或结果不明：{row["postcommit_or_uncertain_boundary"]}',f'- 现有持久键：{row["available_durable_keys"]}',f'- 最小恢复接点：{row["minimal_recovery_hook"]}','']
(out/'CALLBACK_REVIEW.md').write_text('\n'.join(md))
print(json.dumps({k:record[k] for k in ['task_id','callsite_count','distinct_operations','route_file_count']}))
