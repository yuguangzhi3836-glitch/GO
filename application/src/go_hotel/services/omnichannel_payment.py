from go_hotel.services import vertical_reservation_expiry as reservation_expiry
from datetime import datetime,timezone,timedelta
import hashlib,hmac,json,uuid,os
from sqlalchemy import select,func,bindparam
from go_hotel.db.session import SessionLocal
from go_hotel.autonomy.durable import transaction
from go_hotel.db.models import (
 OmnichannelMerchantBindingRow as Merchant,OmnichannelPaymentIntentRow as Intent,
 OmnichannelPaymentAttemptRow as Attempt,OmnichannelWebhookReceiptRow as Receipt,
 OmnichannelLedgerEntryRow as Ledger,OmnichannelReconciliationRow as Recon,
 OmnichannelPayoutRow as Payout,SubscriptionInvoiceRow,PaymentOrderFactBindingRow as FactBinding,
 VerticalSourceDecisionRow as SourceDecision,OrderRow,FlightOrderRow,RailOrderRow,
 MobilityRideOrderRow,MobilityRentalOrderRow,AttractionOrderRow,PaymentOrderRootRow as OrderRoot,
 PspSettlementLineRow as PspLine,BankStatementLineRow as BankLine,OrderSupplierFulfillmentRow as Fulfillment,
 OrderSupplierFulfillmentEventRow as FulfillmentEvent,OmnichannelMoneyMovementRow as Movement
)
CHANNELS={'ALIPAY','WECHAT_PAY','UNIONPAY_QUICKPASS','VISA','MASTERCARD','AMEX','JCB','UNIONPAY_CARD','APPLE_PAY','GOOGLE_PAY','CORPORATE_EBANK','BANK_TRANSFER','CORPORATE_CREDIT','MONTHLY_BILLING','LOCAL_MARKET'}
OPERATIONS={'PAY','AUTHORIZE','CAPTURE','REFUND','PAYOUT','RENEWAL'}
ORDER_TYPES={
 'HOTEL_ORDER':('HOTEL',OrderRow),'FLIGHT_ORDER':('FLIGHT',FlightOrderRow),'RAIL_ORDER':('RAIL',RailOrderRow),
 'RIDE_ORDER':('RIDE',MobilityRideOrderRow),'RENTAL_ORDER':('RENTAL',MobilityRentalOrderRow),'ATTRACTION_ORDER':('ATTRACTION',AttractionOrderRow),
}
TERMINAL={'SUCCEEDED','FAILED'}
# These are immutable statement shapes, not cached payment facts. The caller
# still holds the original attempt and intent locks when each read executes.
_SUCCESS_CONFLICTS = select(
 select(Attempt.payment_attempt_id).where(
  Attempt.payment_intent_id==bindparam('intent_id'), Attempt.state=='SUCCEEDED',
  Attempt.payment_attempt_id!=bindparam('attempt_id')).exists(),
 select(Intent.payment_intent_id).where(
  Intent.business_type==bindparam('business_type'), Intent.business_id==bindparam('business_id'),
  Intent.state=='SUCCEEDED', Intent.payment_intent_id!=bindparam('intent_id')).exists(),
)
_SUCCESS_FULFILLMENT = (select(FactBinding.payment_order_fact_binding_id,
 FactBinding.evidence_reference, Fulfillment.order_supplier_fulfillment_id)
 .select_from(Intent)
 .outerjoin(FactBinding,FactBinding.payment_intent_id==Intent.payment_intent_id)
 .outerjoin(Fulfillment,Fulfillment.payment_intent_id==Intent.payment_intent_id)
 .where(Intent.payment_intent_id==bindparam('intent_id')))
def now():return datetime.now(timezone.utc)
def utc(v):return v.replace(tzinfo=timezone.utc) if v and v.tzinfo is None else v
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}
def legal_entity(currency):return 'GO_CN' if currency=='CNY' else 'GO_GLOBAL'
class OmnichannelPaymentService:
 def create_consumer_intent(self,b,key,payer):
  # Consumer requests select an existing business obligation, never its payee,
  # amount, currency or type of money authority. Other obligations are internal.
  if b.get('business_type') not in ORDER_TYPES:raise ValueError('CONSUMER_PAYMENT_SOURCE_FACT_REQUIRED')
  return self.create_intent(b,key,payer)
 def bind(self,b):
  if b['channel'] not in CHANNELS:raise ValueError('UNSUPPORTED_PAYMENT_CHANNEL')
  refs=[b.get('credential_reference'),b.get('webhook_key_reference')]
  if not all(refs) or any(not x.startswith(('kms://','vault://','cert://')) for x in refs):raise ValueError('EXTERNAL_CREDENTIAL_REFERENCES_REQUIRED')
  with SessionLocal() as s:
   r=Merchant(merchant_binding_id=ident('omb'),owner_type=b['owner_type'],owner_id=b['owner_id'],channel=b['channel'],market=b.get('market','CN'),merchant_reference=b['merchant_reference'],credential_reference=refs[0],webhook_key_reference=refs[1],capabilities_json=b.get('capabilities',[]),state='REFERENCE_BOUND_NOT_CERTIFIED',updated_at=now());s.add(r);s.commit();return out(r)
 def _resolve_order_fact(self,s,b,payer):
  business_type=b['business_type'];business_id=b['business_id']
  vertical,model=ORDER_TYPES[business_type]
  order=s.scalar(select(model).where(model.order_id==business_id).with_for_update())
  if not order:raise ValueError('AUTHORITATIVE_ORDER_FACT_REQUIRED')
  if order.account_id!=payer:raise ValueError('PAYMENT_PAYER_ORDER_MISMATCH')
  if vertical=='RIDE':
   from go_hotel.mobility.ride.cancellation_policy import accepted_in
   accepted_in(s,order)
  if vertical in {'RAIL','ATTRACTION'}:
   if order.status=='CANCELLED':raise ValueError('CANCELLED_ORDER_NOT_PAYABLE')
   reservation_expiry.guard_payment_in(s,vertical,order)
  decision=s.scalar(select(SourceDecision).where(SourceDecision.vertical==vertical,SourceDecision.business_id==business_id,SourceDecision.route!='UNAVAILABLE').order_by(SourceDecision.created_at.desc()))
  if not decision or not decision.selected_source_id or not decision.evidence_reference:raise ValueError('AUTHORIZED_VERTICAL_SOURCE_DECISION_REQUIRED')
  fact={'business_type':business_type,'business_id':business_id,'payer_id':payer,'payee_id':decision.selected_source_id,'amount_minor':int(order.total_amount_minor),'currency':order.currency,'order_status':order.status,'source_decision_id':decision.vertical_source_decision_id,'source_decision_hash':decision.decision_hash}
  return fact,decision
 def create_intent(self,b,key,payer):
  channels=b.get('channel_priority',[])
  if not channels or any(x not in CHANNELS for x in channels):raise ValueError('VALID_CHANNEL_PRIORITY_REQUIRED')
  with transaction(SessionLocal) as s:
   old=s.scalar(select(Intent).where(Intent.idempotency_key==key).with_for_update())
   if b['business_type'] in ORDER_TYPES:
    fact,decision=self._resolve_order_fact(s,b,payer);operation='PAY'
    fp=digest({'fact':fact,'operation':operation,'channels':channels,'automatic_fallback_allowed':bool(b.get('automatic_fallback_allowed',False))})
    if old:
     binding=s.scalar(select(FactBinding).where(FactBinding.payment_intent_id==old.payment_intent_id))
     if not binding or binding.request_fingerprint!=fp:raise ValueError('IDEMPOTENCY_KEY_REQUEST_FINGERPRINT_MISMATCH')
     return out(old)
    existing_root=s.scalar(select(OrderRoot).where(OrderRoot.business_type==fact['business_type'],OrderRoot.business_id==fact['business_id']).with_for_update())
    if existing_root:
     existing=s.get(Intent,existing_root.payment_intent_id)
     if existing:raise ValueError('ORDER_PAYMENT_ROOT_ALREADY_EXISTS')
    r=Intent(payment_intent_id=ident('opi'),business_type=fact['business_type'],business_id=fact['business_id'],payer_id=fact['payer_id'],payee_id=fact['payee_id'],operation=operation,amount_minor=fact['amount_minor'],currency=fact['currency'],channel_priority_json=channels,selected_channel=None,state='REQUIRES_CHANNEL_SELECTION',idempotency_key=key,automatic_fallback_allowed=bool(b.get('automatic_fallback_allowed',False)),created_at=now(),updated_at=now());s.add(r);s.flush()
    reservation_expiry.payment_started_in(s,ORDER_TYPES[b['business_type']][0],fact['business_id'])
    entity=legal_entity(fact['currency'])
    s.add(OrderRoot(payment_order_root_id=ident('por'),business_type=fact['business_type'],business_id=fact['business_id'],payment_intent_id=r.payment_intent_id,legal_entity_id=entity,state='ACTIVE',root_hash=digest({'business_type':fact['business_type'],'business_id':fact['business_id'],'payment_intent_id':r.payment_intent_id,'legal_entity_id':entity}),created_at=now()))
    s.add(FactBinding(payment_order_fact_binding_id=ident('pofb'),payment_intent_id=r.payment_intent_id,business_type=fact['business_type'],business_id=fact['business_id'],payer_id=fact['payer_id'],payee_id=fact['payee_id'],amount_minor=fact['amount_minor'],currency=fact['currency'],legal_entity_id=entity,source_decision_id=decision.vertical_source_decision_id,request_fingerprint=fp,order_fact_hash=digest(fact),evidence_reference=decision.evidence_reference,created_at=now()));s.commit();return out(r)
   # Non-consumer obligations (for example subscription invoices) remain server/admin-created.
   if b.get('operation') not in OPERATIONS or int(b.get('amount_minor',0))<=0:raise ValueError('VALID_PAYMENT_OPERATION_AND_AMOUNT_REQUIRED')
   if old:return out(old)
   r=Intent(payment_intent_id=ident('opi'),business_type=b['business_type'],business_id=b['business_id'],payer_id=payer,payee_id=b['payee_id'],operation=b['operation'],amount_minor=int(b['amount_minor']),currency=b.get('currency','CNY'),channel_priority_json=channels,selected_channel=None,state='REQUIRES_CHANNEL_SELECTION',idempotency_key=key,automatic_fallback_allowed=bool(b.get('automatic_fallback_allowed',False)),created_at=now(),updated_at=now());s.add(r);s.commit();return out(r)
 def select_channel(self,iid,channel,actor,consent=True):
  with SessionLocal() as s:
   i=s.scalar(select(Intent).where(Intent.payment_intent_id==iid).with_for_update())
   if i and i.payer_id!=actor:raise ValueError('PAYMENT_INTENT_ACCESS_DENIED')
   if not i or channel not in i.channel_priority_json:raise ValueError('CHANNEL_NOT_ALLOWED_FOR_INTENT')
   if i.state not in {'REQUIRES_CHANNEL_SELECTION','READY','FAILED'}:raise ValueError('CHANNEL_SWITCH_BLOCKED_BY_PAYMENT_STATE')
   i.selected_channel=channel;i.user_channel_consent_at=now() if consent else None;i.state='READY';i.updated_at=now();s.commit();return out(i)
 def checkout_readiness(self,iid,actor):
  with SessionLocal() as s:
   i=s.get(Intent,iid)
   if not i or i.payer_id!=actor:raise ValueError('PAYMENT_INTENT_ACCESS_DENIED')
   binding=s.scalar(select(Merchant).where(Merchant.channel==i.selected_channel,Merchant.state=='ACTIVE_CERTIFIED'))
   return {'payment_intent_id':iid,'channel':i.selected_channel,'state':'READY_FOR_EXTERNAL_EXECUTOR' if binding else 'BLOCKED','blockers':[] if binding else ['CERTIFIED_CHANNEL_MERCHANT_BINDING_REQUIRED','EXTERNAL_PAYMENT_EXECUTOR_NOT_CONFIGURED'],'payment_completed':i.state=='SUCCEEDED','booking_confirmed':False,'external_live':False}
 def execute(self,iid,mode='CONTRACT_SIMULATOR'):
  with SessionLocal() as s:
   i=s.scalar(select(Intent).where(Intent.payment_intent_id==iid).with_for_update())
   if not i or i.state!='READY':raise ValueError('PAYMENT_INTENT_NOT_READY')
   active=s.scalar(select(Attempt).where(Attempt.payment_intent_id==iid,Attempt.state.in_(['PROCESSING','UNKNOWN_EXTERNAL_STATE'])).with_for_update())
   if active:raise ValueError('ACTIVE_OR_UNKNOWN_ATTEMPT_BLOCKS_RESEND')
   n=(s.scalar(select(func.max(Attempt.attempt_no)).where(Attempt.payment_intent_id==iid)) or 0)+1
   if mode!='CONTRACT_SIMULATOR':raise ValueError('EXTERNAL_PAYMENT_EXECUTOR_NOT_CONFIGURED')
   a=Attempt(payment_attempt_id=ident('opa'),payment_intent_id=iid,channel=i.selected_channel,attempt_no=n,external_operation_id=None,channel_idempotency_key=f'{i.idempotency_key}:{n}',state='CONTRACT_READY_NOT_EXTERNAL',external_invoked=False,created_at=now(),updated_at=now());s.add(a);i.state='CONTRACT_READY_NOT_EXTERNAL';i.updated_at=now();s.commit();return out(a)
 def _transition(self,s,a,i,mapped,external_operation_id=None):
  if i.state in TERMINAL:
   if i.state==mapped:return
   raise ValueError('PAYMENT_TERMINAL_STATE_IMMUTABLE')
  if mapped=='SUCCEEDED':
   attempt_conflict,intent_conflict=s.execute(_SUCCESS_CONFLICTS,{'intent_id':i.payment_intent_id,
    'attempt_id':a.payment_attempt_id,'business_type':i.business_type,'business_id':i.business_id}).one()
   if attempt_conflict:raise ValueError('DUPLICATE_ROOT_PAYMENT_SUCCESS_BLOCKED')
   if intent_conflict:raise ValueError('ORDER_ALREADY_HAS_SUCCESSFUL_PAYMENT')
  a.external_operation_id=external_operation_id or a.external_operation_id;a.state=mapped;a.updated_at=now();i.state=mapped;i.updated_at=now()
  if mapped=='SUCCEEDED' and i.business_type in ORDER_TYPES:
   binding_id,evidence_reference,existing=s.execute(_SUCCESS_FULFILLMENT,{'intent_id':i.payment_intent_id}).one()
   if existing is None:
    f=Fulfillment(order_supplier_fulfillment_id=ident('osf'),payment_intent_id=i.payment_intent_id,business_type=i.business_type,business_id=i.business_id,supplier_id=i.payee_id,supplier_idempotency_key=f'{i.business_type}:{i.business_id}:SUPPLIER_MUTATION',state='PAYMENT_CONFIRMED_AWAITING_MONEY_GRAPH',external_operation_id=None,supplier_confirmation_reference=None,evidence_reference=evidence_reference if binding_id is not None else 'payment://confirmed',created_at=now(),updated_at=now());s.add(f);s.flush();s.add(FulfillmentEvent(order_supplier_fulfillment_event_id=ident('osfe'),order_supplier_fulfillment_id=f.order_supplier_fulfillment_id,event_type='PAYMENT_CONFIRMED',state=f.state,evidence_reference=f.evidence_reference,payload_hash=digest({'payment_intent_id':i.payment_intent_id,'state':f.state}),occurred_at=now()))
 def simulate_result(self,aid,result):
  if result not in {'SUCCEEDED','FAILED','TIMEOUT'}:raise ValueError('INVALID_SIMULATOR_RESULT')
  with SessionLocal() as s:
   a=s.scalar(select(Attempt).where(Attempt.payment_attempt_id==aid).with_for_update());i=s.scalar(select(Intent).where(Intent.payment_intent_id==a.payment_intent_id).with_for_update()) if a else None
   if not a or a.external_invoked:raise ValueError('SIMULATOR_ATTEMPT_REQUIRED')
   mapped='UNKNOWN_EXTERNAL_STATE' if result=='TIMEOUT' else result;self._transition(s,a,i,mapped);s.commit();return {'intent':out(i),'attempt':out(a)}
 def fallback(self,iid,channel,actor):
  with SessionLocal() as s:
   i=s.scalar(select(Intent).where(Intent.payment_intent_id==iid).with_for_update())
   if not i:raise ValueError('PAYMENT_INTENT_NOT_FOUND')
   if i.payer_id!=actor:raise ValueError('PAYMENT_INTENT_ACCESS_DENIED')
   if i.state=='UNKNOWN_EXTERNAL_STATE':raise ValueError('RECONCILE_BEFORE_CHANNEL_FALLBACK')
   if i.state not in {'FAILED','REQUIRES_CHANNEL_SELECTION'}:raise ValueError('CHANNEL_FALLBACK_NOT_ALLOWED')
   if channel not in i.channel_priority_json:raise ValueError('CHANNEL_NOT_ALLOWED_FOR_INTENT')
   i.selected_channel=channel;i.user_channel_consent_at=now();i.state='READY';i.updated_at=now();s.commit();return out(i)
 def ingest_psp_line_in_session(self,s,iid,b):
  required=('external_transaction_id','amount_minor','currency','evidence_reference','occurred_at')
  if any(b.get(x) in (None,'') for x in required):raise ValueError('PSP_SETTLEMENT_FACT_REQUIRED')
  i=s.get(Intent,iid);root=s.scalar(select(OrderRoot).where(OrderRoot.payment_intent_id==iid))
  if not i or not root:raise ValueError('PAYMENT_ORDER_ROOT_REQUIRED')
  if b['currency']!=i.currency:raise ValueError('PSP_SETTLEMENT_PAYMENT_FACT_MISMATCH')
  occurred_at=datetime.fromisoformat(b['occurred_at'].replace('Z','+00:00'))
  old=s.scalar(select(PspLine).where(PspLine.external_transaction_id==b['external_transaction_id']).with_for_update())
  if old:
   prior=(old.payment_intent_id,old.legal_entity_id,old.amount_minor,old.currency,old.evidence_reference,utc(old.occurred_at))
   incoming=(iid,root.legal_entity_id,int(b['amount_minor']),b['currency'],b['evidence_reference'],utc(occurred_at))
   if prior!=incoming:raise ValueError('PSP_SETTLEMENT_TRANSACTION_FACT_CONFLICT')
   return out(old)
  # A partial capture is an authoritative money fact too. Reconciliation below
  # still requires the PSP, bank and balanced capture ledger to agree. Checking
  # immutable receipt replay first keeps a valid prior line replayable after a
  # later capture without accepting edits to that receipt.
  captured=sum(x.amount_minor for x in s.scalars(select(Movement).where(
   Movement.root_payment_intent_id==iid,Movement.movement_type=='CAPTURE',
   Movement.state=='CONFIRMED',Movement.currency==i.currency)))
  if int(b['amount_minor']) not in {i.amount_minor,captured} or int(b['amount_minor'])<=0:
   raise ValueError('PSP_SETTLEMENT_PAYMENT_FACT_MISMATCH')
  r=PspLine(psp_settlement_line_id=ident('psp'),payment_intent_id=iid,external_transaction_id=b['external_transaction_id'],channel=i.selected_channel or 'UNSELECTED',legal_entity_id=root.legal_entity_id,amount_minor=int(b['amount_minor']),currency=b['currency'],evidence_reference=b['evidence_reference'],occurred_at=occurred_at);s.add(r);s.flush();return out(r)
 def ingest_psp_line(self,iid,b):
  with SessionLocal() as s:
   r=self.ingest_psp_line_in_session(s,iid,b);s.commit();return r
 def ingest_bank_line_in_session(self,s,b):
  required=('bank_line_identity','legal_entity_id','amount_minor','currency','payment_reference','evidence_reference','booked_at')
  if any(b.get(x) in (None,'') for x in required):raise ValueError('BANK_STATEMENT_FACT_REQUIRED')
  booked_at=datetime.fromisoformat(b['booked_at'].replace('Z','+00:00'))
  old=s.scalar(select(BankLine).where(BankLine.bank_line_identity==b['bank_line_identity']).with_for_update())
  if old:
   prior=(old.legal_entity_id,old.amount_minor,old.currency,old.payment_reference,old.evidence_reference,utc(old.booked_at))
   incoming=(b['legal_entity_id'],int(b['amount_minor']),b['currency'],b['payment_reference'],b['evidence_reference'],utc(booked_at))
   if prior!=incoming:raise ValueError('BANK_STATEMENT_LINE_FACT_CONFLICT')
   return out(old)
  r=BankLine(bank_statement_line_id=ident('bsl'),bank_line_identity=b['bank_line_identity'],legal_entity_id=b['legal_entity_id'],amount_minor=int(b['amount_minor']),currency=b['currency'],payment_reference=b['payment_reference'],evidence_reference=b['evidence_reference'],booked_at=booked_at);s.add(r);s.flush();return out(r)
 def ingest_bank_line(self,b):
  with SessionLocal() as s:
   r=self.ingest_bank_line_in_session(s,b);s.commit();return r
 def reconcile(self,iid,b):
  with SessionLocal() as s:
   i=s.scalar(select(Intent).where(Intent.payment_intent_id==iid).with_for_update());root=s.scalar(select(OrderRoot).where(OrderRoot.payment_intent_id==iid))
   if not i or not root:raise ValueError('PAYMENT_ORDER_ROOT_REQUIRED')
   psp=s.scalar(select(PspLine).where(PspLine.payment_intent_id==iid,PspLine.external_transaction_id==b.get('external_transaction_id')))
   bank=s.scalar(select(BankLine).where(BankLine.payment_reference==b.get('external_transaction_id'),BankLine.legal_entity_id==root.legal_entity_id)) if psp else None
   capture=sum(x.amount_minor for x in s.scalars(select(Movement).where(Movement.root_payment_intent_id==iid,Movement.movement_type=='CAPTURE',Movement.state=='CONFIRMED')).all())
   ledger=s.scalars(select(Ledger).where(Ledger.payment_intent_id==iid,Ledger.entry_type=='CAPTURE')).all();debit=sum(x.amount_minor for x in ledger if x.direction=='DEBIT');credit=sum(x.amount_minor for x in ledger if x.direction=='CREDIT')
   complete=bool(psp and bank and capture>0 and debit==capture and credit==capture and psp.amount_minor==capture and bank.amount_minor==capture and psp.currency==i.currency==bank.currency)
   diff=0 if complete else max([abs((psp.amount_minor if psp else 0)-capture),abs((bank.amount_minor if bank else 0)-capture),abs(debit-capture),abs(credit-capture)])
   state='MATCHED' if complete else 'PENDING_EXTERNAL_FACT' if not psp or not bank else 'DIFFERENCE'
   r=Recon(reconciliation_id=ident('orec'),payment_intent_id=iid,channel=i.selected_channel or 'UNSELECTED',channel_amount_minor=psp.amount_minor if psp else None,bank_amount_minor=bank.amount_minor if bank else None,ledger_amount_minor=capture,fee_minor=0,tax_minor=0,fx_minor=0,state=state,difference_minor=diff,evidence_json=[x for x in [psp.evidence_reference if psp else None,bank.evidence_reference if bank else None] if x],reconciled_at=now());s.add(r);s.commit();return out(r)
 def status(self,payer=None):
  with SessionLocal() as s:
   intents=s.scalars(select(Intent).where(*([] if payer is None else [Intent.payer_id==payer])).order_by(Intent.created_at.desc())).all();ids=[x.payment_intent_id for x in intents];ats=s.scalars(select(Attempt).where(Attempt.payment_intent_id.in_(ids))).all() if ids else [];recs=s.scalars(select(Recon).where(Recon.payment_intent_id.in_(ids))).all() if ids else [];return {'supported_channels':sorted(CHANNELS),'intents':[out(x) for x in intents],'attempts':[out(x) for x in ats],'reconciliations':[out(x) for x in recs],'external_live':False}
 def webhook(self,channel,b,signature):
  if channel not in CHANNELS:raise ValueError('UNSUPPORTED_PAYMENT_CHANNEL')
  key=os.getenv(f'GO_PAYMENT_WEBHOOK_KEY_{channel}')
  if not key:raise ValueError('PAYMENT_WEBHOOK_KEY_NOT_CONFIGURED')
  required=('external_event_id','payment_attempt_id','external_operation_id','state','operation','amount_minor','currency','occurred_at')
  if any(b.get(x) in (None,'') for x in required):raise ValueError('PAYMENT_CALLBACK_FACTS_REQUIRED')
  raw=json.dumps(b,sort_keys=True,separators=(',',':'));expected=hmac.new(key.encode(),raw.encode(),hashlib.sha256).hexdigest()
  if not hmac.compare_digest(expected,signature):raise ValueError('PAYMENT_WEBHOOK_SIGNATURE_INVALID')
  occurred=b.get('occurred_at')
  event_at=datetime.fromisoformat(occurred.replace('Z','+00:00'))
  if event_at<now()-timedelta(hours=24) or event_at>now()+timedelta(minutes=5):raise ValueError('PAYMENT_CALLBACK_OUTSIDE_REPLAY_WINDOW')
  payload_hash=digest(b)
  with SessionLocal() as s:
   old=s.scalar(select(Receipt).where(Receipt.channel==channel,Receipt.external_event_id==b['external_event_id']).with_for_update())
   if old:
    if old.payload_hash!=payload_hash:raise ValueError('PAYMENT_CALLBACK_EVENT_PAYLOAD_CONFLICT')
    return {'duplicate':True,'receipt':out(old)}
   a=s.scalar(select(Attempt).where(Attempt.payment_attempt_id==b['payment_attempt_id']).with_for_update());i=s.scalar(select(Intent).where(Intent.payment_intent_id==a.payment_intent_id).with_for_update()) if a else None
   if not a or a.channel!=channel:raise ValueError('PAYMENT_ATTEMPT_CHANNEL_MISMATCH')
   # Generic HMAC is only the contract-simulator receipt boundary. A real PSP
   # callback must be verified by the provider-specific adapter before ingress.
   if a.external_invoked:raise ValueError('REAL_PSP_WEBHOOK_VERIFIER_NOT_INSTALLED')
   if str(b['operation'])!=i.operation:raise ValueError('PAYMENT_CALLBACK_OPERATION_MISMATCH')
   if int(b['amount_minor'])!=i.amount_minor:raise ValueError('PAYMENT_CALLBACK_AMOUNT_MISMATCH')
   if str(b['currency'])!=i.currency:raise ValueError('PAYMENT_CALLBACK_CURRENCY_MISMATCH')
   if a.external_operation_id and b['external_operation_id']!=a.external_operation_id:raise ValueError('PAYMENT_CALLBACK_EXTERNAL_OPERATION_MISMATCH')
   mapped={'SUCCEEDED':'SUCCEEDED','FAILED':'FAILED','PENDING':'UNKNOWN_EXTERNAL_STATE'}.get(b['state'])
   if not mapped:raise ValueError('INVALID_EXTERNAL_PAYMENT_STATE')
   r=Receipt(webhook_receipt_id=ident('owr'),channel=channel,external_event_id=b['external_event_id'],payment_attempt_id=a.payment_attempt_id,signature_verified=True,payload_hash=payload_hash,received_at=now());s.add(r);self._transition(s,a,i,mapped,b['external_operation_id']);s.commit();return {'duplicate':False,'receipt':out(r),'intent':out(i)}
 def _ledger(self,s,i):
  raise ValueError('PAYMENT_SUCCESS_DOES_NOT_POST_GL_USE_CAPTURE_MOVEMENT')
 def _legacy_ledger_disabled(self,s,i):
  tx=ident('txn');payload={'intent':i.payment_intent_id,'amount':i.amount_minor,'currency':i.currency}
  for account,direction in [(f'RECEIVABLE:{i.payee_id}','DEBIT'),(f'PAYMENT_CLEARING:{i.selected_channel}','CREDIT')]:s.add(Ledger(ledger_entry_id=ident('ole'),transaction_id=tx,payment_intent_id=i.payment_intent_id,account_code=account,direction=direction,amount_minor=i.amount_minor,currency=i.currency,entry_type=i.operation,evidence_hash=digest(payload),created_at=now()))
omnichannel_payment_service=OmnichannelPaymentService()
