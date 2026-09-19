from datetime import datetime,timezone,timedelta
import hashlib,json,uuid
from sqlalchemy import select,text
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
 OmnichannelPaymentIntentRow as Intent,OmnichannelMoneyMovementRow as Movement,
 OmnichannelLedgerEntryRow as Ledger,OmnichannelReconciliationRow as Recon,
 FinanceCloseBatchRow as LegacyClose,FinanceCloseLineRow as LegacyLine,SubscriptionInvoiceRow,
 FinanceScopedCloseBatchRow as Close,FinanceScopedCloseLineRow as Line,PaymentOrderFactBindingRow as FactBinding,PaymentOrderRootRow as OrderRoot,
 OrderSupplierFulfillmentRow as Fulfillment,OrderSupplierFulfillmentEventRow as FulfillmentEvent
)
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}
class UnifiedMoneyMovementService:
 def create(self,intent_id,b,key,actor):
  with SessionLocal() as s:
   if s.bind.dialect.name=='sqlite':s.execute(text('BEGIN IMMEDIATE'))
   result=self.create_in_session(s,intent_id,b,key,actor)
   s.commit();return result
 def create_in_session(self,s,intent_id,b,key,actor):
  """Caller owns the transaction; lock order/payment before updating business facts."""
  typ=b['movement_type']
  if typ not in {'AUTHORIZATION','CAPTURE','REFUND','COMPENSATION','PAYOUT','RELEASE'}:raise ValueError('INVALID_MONEY_MOVEMENT_TYPE')
  i=s.scalar(select(Intent).where(Intent.payment_intent_id==intent_id).with_for_update())
  if not i:raise ValueError('ROOT_PAYMENT_INTENT_REQUIRED')
  amount=b.get('amount_minor',i.amount_minor)
  if type(amount) is not int:raise ValueError('INTEGER_MOVEMENT_AMOUNT_REQUIRED')
  old=s.scalar(select(Movement).where(Movement.idempotency_key==key).with_for_update())
  if old:
   if (old.root_payment_intent_id,old.movement_type,old.amount_minor,old.parent_movement_id)!=(intent_id,typ,amount,b.get('parent_movement_id')):
    raise ValueError('MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT')
   return out(old)
  from go_hotel.services.catalog_supplier_remedy import assert_money_action
  assert_money_action(s,i,typ,amount,b.get('parent_movement_id'),key)
  from go_hotel.services.catalog_credit_value import assert_money_action as assert_credit_money_action
  assert_credit_money_action(s,i,typ,amount,b.get('parent_movement_id'),key)
  from go_hotel.services.catalog_cash_fare import money_action as assert_cash_fare_money_action
  assert_cash_fare_money_action(s,i,typ,amount,b.get('parent_movement_id'),key)
  if i.state!='SUCCEEDED':raise ValueError('ROOT_PAYMENT_SUCCESS_REQUIRED')
  if amount<=0:raise ValueError('POSITIVE_MOVEMENT_AMOUNT_REQUIRED')
  movements=s.scalars(select(Movement).where(Movement.root_payment_intent_id==intent_id).with_for_update()).all()
  auth=sum(x.amount_minor for x in movements if x.movement_type=='AUTHORIZATION' and x.state=='CONFIRMED')
  captured=sum(x.amount_minor for x in movements if x.movement_type=='CAPTURE' and x.state=='CONFIRMED')
  released=sum(x.amount_minor for x in movements if x.movement_type=='RELEASE' and x.state=='CONFIRMED')
  refunded=sum(x.amount_minor for x in movements if x.movement_type in {'REFUND','COMPENSATION'} and x.state=='CONFIRMED')
  payouts=sum(x.amount_minor for x in movements if x.movement_type=='PAYOUT' and x.state=='CONFIRMED')
  if typ=='AUTHORIZATION' and auth+amount>i.amount_minor:raise ValueError('CUMULATIVE_AUTHORIZATION_EXCEEDS_ROOT_INTENT')
  if typ=='CAPTURE' and captured+amount>auth:raise ValueError('CUMULATIVE_CAPTURE_EXCEEDS_AUTHORIZATION')
  if typ=='CAPTURE' and captured+released+amount>auth:raise ValueError('CAPTURE_EXCEEDS_UNRELEASED_AUTHORIZATION')
  if typ=='RELEASE' and captured+released+amount>auth:raise ValueError('RELEASE_EXCEEDS_REMAINING_AUTHORIZATION')
  if typ in {'REFUND','COMPENSATION'} and refunded+amount>captured:raise ValueError('CUMULATIVE_REFUND_COMPENSATION_EXCEEDS_CAPTURE')
  if typ=='PAYOUT' and payouts+amount>captured-refunded:raise ValueError('CUMULATIVE_PAYOUT_EXCEEDS_NET_CAPTURE')
  parent_id=b.get('parent_movement_id')
  if parent_id:
   parent=next((x for x in movements if x.money_movement_id==parent_id),None)
   if not parent:raise ValueError('PARENT_MOVEMENT_MUST_SHARE_ROOT')
   from go_hotel.services.hosted_fare_value import is_forfeiture
   if typ in {'REFUND','COMPENSATION'} and is_forfeiture(parent):raise ValueError('HOSTED_CHANGE_FORFEITURE_NOT_REFUNDABLE')
   allowed={'CAPTURE':{'AUTHORIZATION'},'REFUND':{'CAPTURE'},'COMPENSATION':{'CAPTURE'},'PAYOUT':{'CAPTURE'},'RELEASE':{'AUTHORIZATION'}}
   if typ in allowed and parent.movement_type not in allowed[typ]:raise ValueError('INVALID_MONEY_MOVEMENT_PARENT_TYPE')
   if typ in allowed and parent.state!='CONFIRMED':raise ValueError('CONFIRMED_PARENT_MOVEMENT_REQUIRED')
   children=[x for x in movements if x.parent_movement_id==parent_id and x.state=='CONFIRMED']
   if typ in {'CAPTURE','RELEASE'} and sum(x.amount_minor for x in children if x.movement_type in {'CAPTURE','RELEASE'})+amount>parent.amount_minor:raise ValueError('PARENT_AUTHORIZATION_BUDGET_EXCEEDED')
   if typ in {'REFUND','COMPENSATION'} and sum(x.amount_minor for x in children if x.movement_type in {'REFUND','COMPENSATION'})+amount>parent.amount_minor:raise ValueError('PARENT_CAPTURE_REFUND_BUDGET_EXCEEDED')
  evidence=b.get('evidence',[])
  if not evidence:raise ValueError('MONEY_MOVEMENT_EVIDENCE_REQUIRED')
  mode=b.get('mode');
  if mode=='EXTERNAL_CERTIFIED_FACT' and (not b.get('external_reference') or not evidence):raise ValueError('CERTIFIED_EXTERNAL_MOVEMENT_EVIDENCE_REQUIRED')
  state='CONFIRMED' if mode in {'CONTRACT_SIMULATOR','EXTERNAL_CERTIFIED_FACT'} else 'EXTERNAL_EXECUTOR_REQUIRED'
  r=Movement(money_movement_id=ident('omm'),root_payment_intent_id=intent_id,parent_movement_id=parent_id,movement_type=typ,business_type=i.business_type,business_id=i.business_id,amount_minor=amount,currency=i.currency,state=state,idempotency_key=key,external_reference=b.get('external_reference'),evidence_json=evidence,created_at=now(),updated_at=now());s.add(r)
  if state=='CONFIRMED' and typ not in {'AUTHORIZATION','RELEASE'}:self._post(s,i,r)
  if typ=='CAPTURE' and state=='CONFIRMED' and captured+amount==i.amount_minor:
   f=s.scalar(select(Fulfillment).where(Fulfillment.payment_intent_id==intent_id).with_for_update())
   if f and f.state=='PAYMENT_CONFIRMED_AWAITING_MONEY_GRAPH':
    f.state='CAPTURE_CONFIRMED_READY_FOR_SUPPLIER';f.updated_at=now();s.add(FulfillmentEvent(order_supplier_fulfillment_event_id=ident('osfe'),order_supplier_fulfillment_id=f.order_supplier_fulfillment_id,event_type='MONEY_GRAPH_CAPTURE_CONFIRMED',state=f.state,evidence_reference=(evidence[0] if isinstance(evidence[0],str) else evidence[0].get('reference','money://capture')),payload_hash=digest({'movement':r.money_movement_id,'captured_total':captured+amount}),occurred_at=now()))
  if i.business_type=='SUBSCRIPTION_INVOICE' and typ=='CAPTURE' and state=='CONFIRMED':
   inv=s.get(SubscriptionInvoiceRow,i.business_id)
   if inv:inv.state='PAID'
  s.flush();return out(r)
 def _scope(self,s,legal_entity_id,currency,period_start,period_end,cutoff):
  start_at=datetime.fromisoformat(period_start+'T00:00:00+00:00')
  end_at=datetime.fromisoformat(period_end+'T00:00:00+00:00')+timedelta(days=1)
  roots=s.scalars(select(OrderRoot).where(OrderRoot.legal_entity_id==legal_entity_id)).all();root_ids={x.payment_intent_id for x in roots}
  movements=s.scalars(select(Movement).where(Movement.root_payment_intent_id.in_(root_ids),Movement.currency==currency,Movement.created_at>=start_at,Movement.created_at<end_at,Movement.created_at<=cutoff)).all() if root_ids else []
  intent_ids={x.root_payment_intent_id for x in movements}
  ledger=s.scalars(select(Ledger).where(Ledger.payment_intent_id.in_(intent_ids),Ledger.currency==currency,Ledger.created_at>=start_at,Ledger.created_at<end_at,Ledger.created_at<=cutoff)).all() if intent_ids else []
  recs=s.scalars(select(Recon).where(Recon.payment_intent_id.in_(intent_ids))).all() if intent_ids else []
  return movements,ledger,recs
 def _recon_blockers(self,recs,movements):
  captured_ids={x.root_payment_intent_id for x in movements if x.movement_type=='CAPTURE' and x.state=='CONFIRMED'}
  latest={}
  for r in recs:
   if r.payment_intent_id not in latest or r.reconciled_at>latest[r.payment_intent_id].reconciled_at:latest[r.payment_intent_id]=r
  return [f'RECON_MISSING:{iid}' for iid in captured_ids if iid not in latest]+[f'RECON:{latest[iid].reconciliation_id}' for iid in captured_ids if iid in latest and latest[iid].state!='MATCHED']
 def prepare_close(self,b,actor):
  required=('legal_entity_id','currency','period_start','period_end','cutoff_at')
  if any(not b.get(x) for x in required):raise ValueError('SCOPED_CLOSE_FIELDS_REQUIRED')
  cutoff=datetime.fromisoformat(b['cutoff_at'].replace('Z','+00:00'))
  scope={'legal_entity_id':b['legal_entity_id'],'currency':b['currency'],'period_start':b['period_start'],'period_end':b['period_end'],'cutoff_at':cutoff.isoformat()};scope_hash=digest(scope)
  with SessionLocal() as s:
   old=s.scalar(select(Close).where(Close.scope_hash==scope_hash))
   if old:return out(old)
   movements,ledger,recs=self._scope(s,b['legal_entity_id'],b['currency'],b['period_start'],b['period_end'],cutoff)
   debit=sum(x.amount_minor for x in ledger if x.direction=='DEBIT');credit=sum(x.amount_minor for x in ledger if x.direction=='CREDIT')
   block=[f'MOVEMENT:{x.money_movement_id}' for x in movements if x.state in {'UNKNOWN_EXTERNAL_STATE','EXTERNAL_EXECUTOR_REQUIRED'}]+self._recon_blockers(recs,movements)
   try:
    from go_hotel.services.production_connector_runtime import production_connector_runtime_service
    roots_by_intent={x.payment_intent_id:x.business_id for x in s.scalars(select(OrderRoot).where(OrderRoot.payment_intent_id.in_({m.root_payment_intent_id for m in movements}))).all()} if movements else {}
    block+=production_connector_runtime_service.unresolved_incident_blockers(set(roots_by_intent.values()))
   except Exception:
    # The incident authority is part of close admissibility. A failed lookup
    # cannot be interpreted as "no incidents".
    block.append('FINANCE_INCIDENT_CHECK_UNAVAILABLE')
   payload=scope|{'movements':[x.money_movement_id for x in movements],'debit':debit,'credit':credit,'blockers':block}
   r=Close(finance_scoped_close_batch_id=ident('fscb'),legal_entity_id=b['legal_entity_id'],currency=b['currency'],period_start=b['period_start'],period_end=b['period_end'],cutoff_at=cutoff,state='BLOCKED' if block or debit!=credit else 'PENDING_APPROVAL',movement_count=len(movements),debit_minor=debit,credit_minor=credit,difference_minor=debit-credit,blockers_json=block,scope_hash=scope_hash,evidence_hash=digest(payload),requested_by=actor,created_at=now());s.add(r);s.flush()
   for x in movements:s.add(Line(finance_scoped_close_line_id=ident('fscl'),finance_scoped_close_batch_id=r.finance_scoped_close_batch_id,source_type='MONEY_MOVEMENT',source_id=x.money_movement_id,state=x.state,amount_minor=x.amount_minor,evidence_hash=digest(out(x))))
   s.commit();return out(r)
 def approve_close(self,cid,actor):
  with SessionLocal() as s:
   r=s.scalar(select(Close).where(Close.finance_scoped_close_batch_id==cid).with_for_update())
   if not r:raise ValueError('FINANCE_CLOSE_NOT_FOUND')
   if r.requested_by==actor:raise ValueError('MAKER_CHECKER_REQUIRED')
   movements,ledger,recs=self._scope(s,r.legal_entity_id,r.currency,r.period_start,r.period_end,r.cutoff_at)
   debit=sum(x.amount_minor for x in ledger if x.direction=='DEBIT');credit=sum(x.amount_minor for x in ledger if x.direction=='CREDIT')
   block=[f'MOVEMENT:{x.money_movement_id}' for x in movements if x.state in {'UNKNOWN_EXTERNAL_STATE','EXTERNAL_EXECUTOR_REQUIRED'}]+self._recon_blockers(recs,movements)
   try:
    from go_hotel.services.production_connector_runtime import production_connector_runtime_service
    roots_by_intent={x.payment_intent_id:x.business_id for x in s.scalars(select(OrderRoot).where(OrderRoot.payment_intent_id.in_({m.root_payment_intent_id for m in movements}))).all()} if movements else {}
    block+=production_connector_runtime_service.unresolved_incident_blockers(set(roots_by_intent.values()))
   except Exception:
    # The incident authority is part of close admissibility. A failed lookup
    # cannot be interpreted as "no incidents".
    block.append('FINANCE_INCIDENT_CHECK_UNAVAILABLE')
   if block or debit!=credit or len(movements)!=r.movement_count or debit!=r.debit_minor or credit!=r.credit_minor:raise ValueError('FINANCE_CLOSE_SCOPE_CHANGED_REPREPARE_REQUIRED')
   if r.state!='PENDING_APPROVAL':raise ValueError('FINANCE_CLOSE_NOT_PENDING_APPROVAL')
   r.state='CLOSED';r.approved_by=actor;r.closed_at=now();s.commit();return out(r)
 def status(self):
  with SessionLocal() as s:return {'movements':[out(x) for x in s.scalars(select(Movement).order_by(Movement.created_at.desc())).all()],'scoped_closes':[out(x) for x in s.scalars(select(Close).order_by(Close.created_at.desc())).all()],'legacy_close_disabled':True,'principle':'SERVER_ORDER_FACT_TO_PAYMENT_TO_MONEY_MOVEMENT_TO_SCOPED_CLOSE'}
 def _post(self,s,i,m):
  tx=m.money_movement_id;reverse=m.movement_type in {'REFUND','COMPENSATION','PAYOUT','RELEASE'};pairs=[(f'PAYMENT_CLEARING:{i.selected_channel}','DEBIT'),(f'BUSINESS:{i.business_type}:{i.business_id}','CREDIT')]
  if reverse:pairs=[(a,'CREDIT' if d=='DEBIT' else 'DEBIT') for a,d in pairs]
  for account,direction in pairs:s.add(Ledger(ledger_entry_id=ident('ole'),transaction_id=tx,payment_intent_id=i.payment_intent_id,account_code=account,direction=direction,amount_minor=m.amount_minor,currency=m.currency,entry_type=m.movement_type,evidence_hash=digest({'movement':m.money_movement_id}),created_at=now()))
unified_money_movement_service=UnifiedMoneyMovementService()
