from datetime import datetime,timezone
import hashlib,json,uuid
from sqlalchemy import select,bindparam
from sqlalchemy.orm import load_only
from go_hotel.db.session import SessionLocal
from go_hotel.autonomy.durable import transaction
from go_hotel.services.vertical_prebook_contract import rail_tickets
from go_hotel.services import vertical_capacity as capacity
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service
from go_hotel.db.models import (
 OrderSupplierFulfillmentRow as Fulfillment,OrderSupplierFulfillmentEventRow as FEvent,
 OrderRow,FlightOrderRow,RailOrderRow,MobilityRideOrderRow,MobilityRentalOrderRow,AttractionOrderRow,
 ConsumerUnifiedLifecycleRow as Life,ConsumerUnifiedLifecycleEventRow as LifeEvent,
 OmnichannelPaymentIntentRow as Intent,OmnichannelMoneyMovementRow as Movement,
 PaymentOrderRootRow as Root,PaymentOrderFactBindingRow as Binding
)
MODELS={'HOTEL_ORDER':('HOTEL',OrderRow),'FLIGHT_ORDER':('FLIGHT',FlightOrderRow),'RAIL_ORDER':('RAIL',RailOrderRow),'RIDE_ORDER':('RIDE',MobilityRideOrderRow),'RENTAL_ORDER':('RENTAL',MobilityRentalOrderRow),'ATTRACTION_ORDER':('ATTRACTION',AttractionOrderRow)}
# All three rows are unique for a payment intent. An inner join requires the
# complete durable binding before any supplier fact can project money as paid.
_BOUND_PAYMENT = (select(Intent,Root,Binding)
 .options(load_only(Intent.payment_intent_id, Intent.state, Intent.business_type,
   Intent.business_id, Intent.payer_id, Intent.payee_id, Intent.amount_minor, Intent.currency),
  load_only(Root.business_type, Root.business_id, Root.legal_entity_id),
  load_only(Binding.business_type, Binding.business_id, Binding.payer_id,
   Binding.payee_id, Binding.amount_minor, Binding.currency, Binding.legal_entity_id))
 .join(Root,Root.payment_intent_id==Intent.payment_intent_id)
 .join(Binding,Binding.payment_intent_id==Intent.payment_intent_id)
 .where(Intent.payment_intent_id==bindparam('intent_id')))
_BOUND_MOVEMENTS = (select(Movement).options(load_only(
 Movement.money_movement_id, Movement.parent_movement_id, Movement.movement_type,
 Movement.state, Movement.business_type, Movement.business_id, Movement.currency,
 Movement.amount_minor)).where(Movement.root_payment_intent_id==bindparam('intent_id')))
_FULFILLMENT_BY_ID = select(Fulfillment).where(
 Fulfillment.order_supplier_fulfillment_id==bindparam('fulfillment_id')).with_for_update()
_ORDER_LOCKS = {kind:select(model).where(model.order_id==bindparam('order_id')).with_for_update()
 for kind,(_,model) in MODELS.items()}
_EXISTING_LIFE = select(Life).where(Life.vertical==bindparam('vertical'),Life.order_id==bindparam('order_id'))
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}

def _payment_state(s, f, order):
 """Supplier outcomes never supply money truth; read the bound C11 graph."""
 unknown='UNKNOWN_EXTERNAL_STATE'
 graph=s.execute(_BOUND_PAYMENT,{'intent_id':f.payment_intent_id}).one_or_none()
 expected=(f.business_type,f.business_id,order.account_id,f.supplier_id,order.total_amount_minor,order.currency)
 if not graph:return unknown
 i,root,binding=graph
 if i.state!='SUCCEEDED':return unknown
 if (i.business_type,i.business_id,i.payer_id,i.payee_id,i.amount_minor,i.currency)!=expected:return unknown
 if (binding.business_type,binding.business_id,binding.payer_id,binding.payee_id,binding.amount_minor,binding.currency)!=expected:return unknown
 if (root.business_type,root.business_id,root.legal_entity_id)!=(f.business_type,f.business_id,binding.legal_entity_id):return unknown
 rows=s.scalars(_BOUND_MOVEMENTS,{'intent_id':i.payment_intent_id}).all()
 if any(x.state!='CONFIRMED' for x in rows):return unknown
 if any((x.business_type,x.business_id,x.currency)!=(f.business_type,f.business_id,i.currency)
        or type(x.amount_minor) is not int or x.amount_minor<=0 for x in rows):return unknown
 by_id={x.money_movement_id:x for x in rows}
 parents={'CAPTURE':'AUTHORIZATION','RELEASE':'AUTHORIZATION','REFUND':'CAPTURE','COMPENSATION':'CAPTURE','PAYOUT':'CAPTURE'}
 parent_spent={}
 for movement in rows:
  if movement.movement_type=='AUTHORIZATION':
   if movement.parent_movement_id:return unknown
  else:
   parent=by_id.get(movement.parent_movement_id)
   if movement.movement_type not in parents or not parent or parent.movement_type!=parents[movement.movement_type]:return unknown
   # Each edge contributes once. Parent-type validation above keeps authorization
   # spending and capture refunds distinct; payouts retain their existing rules.
   if movement.movement_type in {'CAPTURE','RELEASE','REFUND','COMPENSATION'}:
    parent_spent[movement.parent_movement_id]=parent_spent.get(movement.parent_movement_id,0)+movement.amount_minor
 for parent in rows:
  if parent.movement_type in {'AUTHORIZATION','CAPTURE'} and parent_spent.get(parent.money_movement_id,0)>parent.amount_minor:return unknown
 auth=sum(x.amount_minor for x in rows if x.movement_type=='AUTHORIZATION')
 captured=sum(x.amount_minor for x in rows if x.movement_type=='CAPTURE')
 released=sum(x.amount_minor for x in rows if x.movement_type=='RELEASE')
 refunded=sum(x.amount_minor for x in rows if x.movement_type in {'REFUND','COMPENSATION'})
 if captured!=i.amount_minor or auth>i.amount_minor or captured+released>auth or refunded>captured:return unknown
 if refunded==captured:return 'REFUNDED'
 return 'PARTIALLY_REFUNDED' if refunded else 'PAID'

def _project_lifecycle(s,f,order,vertical,state,evidence,existing,payment_state):
 life_state='CONFIRMED' if state=='SUPPLIER_CONFIRMED' else ('FAILED' if state=='SUPPLIER_FAILED' else 'UNKNOWN_EXTERNAL_STATE')
 refund_state='REFUND_COMPLETED' if payment_state=='REFUNDED' else existing.refund_state if existing else 'NOT_REQUESTED'
 return consumer_unified_lifecycle_service.project_in_session(s,{'account_id':order.account_id,'vertical':vertical,'order_id':f.business_id,'supplier_id':f.supplier_id,'title':f'{vertical} {f.business_id}','lifecycle_state':life_state,'payment_state':payment_state,'refund_state':refund_state,'change_allowed':False,'cancel_allowed':state=='SUPPLIER_CONFIRMED','facts':{'supplier_confirmation_reference':f.supplier_confirmation_reference,'external_operation_id':f.external_operation_id},'evidence_reference':evidence,'source_updated_at':now(),'event_type':'SUPPLIER_FACT_PROJECTED'})
class OrderSupplierFulfillmentService:
 def get(self,fid):
  with SessionLocal() as s:
   f=s.get(Fulfillment,fid)
   if not f:raise ValueError('SUPPLIER_FULFILLMENT_NOT_FOUND')
   return out(f)
 def record_supplier_fact(self,fid,b):
  state=b.get('state')
  if state not in {'SUPPLIER_CONFIRMED','UNKNOWN_EXTERNAL_STATE','SUPPLIER_FAILED'}:raise ValueError('INVALID_SUPPLIER_FACT_STATE')
  if not b.get('evidence_reference'):raise ValueError('SUPPLIER_FACT_EVIDENCE_REQUIRED')
  if state=='SUPPLIER_CONFIRMED' and not b.get('supplier_confirmation_reference'):raise ValueError('SUPPLIER_CONFIRMATION_REFERENCE_REQUIRED')
  with transaction(SessionLocal) as s:
   f=s.scalar(_FULFILLMENT_BY_ID,{'fulfillment_id':fid})
   if not f:raise ValueError('SUPPLIER_FULFILLMENT_NOT_FOUND')
   if f.state=='SUPPLIER_CONFIRMED' and state!='SUPPLIER_CONFIRMED':raise ValueError('SUPPLIER_CONFIRMATION_IMMUTABLE')
   vertical,model=MODELS[f.business_type];order=s.scalar(_ORDER_LOCKS[f.business_type],{'order_id':f.business_id})
   if not order:raise ValueError('AUTHORITATIVE_ORDER_FACT_REQUIRED')
   terminal_by_vertical={
    'HOTEL':{'CANCELLED','CONVERTED_TO_CREDIT','FAILED'},
    'FLIGHT':{'REFUNDED','FAILED'},
    'RAIL':{'REFUNDED','FAILED','CANCELLED'},
    'RIDE':{'REFUNDED','COMPLETED','FAILED','CANCELLED'},
    'RENTAL':{'REFUNDED','COMPLETED','FAILED'},
    'ATTRACTION':{'REFUNDED','FULFILLED','CLOSED_BY_SUPPLIER','FAILED','CANCELLED'},
   }
   if str(order.status) in terminal_by_vertical.get(vertical,set()):raise ValueError('TERMINAL_ORDER_SUPPLIER_FACT_REJECTED')
   if vertical in {'FLIGHT','RAIL'} and f.state=='SUPPLIER_CONFIRMED' and order.status!='TICKETED':
    # A delayed initial issuance receipt cannot settle a later change/refund
    # episode or refresh its read model back to an apparent success.
    raise ValueError('TICKET_OPERATION_RECONCILIATION_REQUIRED')
   existing_life=s.scalar(_EXISTING_LIFE,{'vertical':vertical,'order_id':f.business_id})
   projected_life='CONFIRMED' if state=='SUPPLIER_CONFIRMED' else ('FAILED' if state=='SUPPLIER_FAILED' else 'UNKNOWN_EXTERNAL_STATE')
   if existing_life and existing_life.lifecycle_state in {'COMPLETED','CANCELLED','FAILED'} and projected_life!=existing_life.lifecycle_state:
    raise ValueError('TERMINAL_LIFECYCLE_SUPPLIER_FACT_REJECTED')
   if vertical=='RAIL' and state=='SUPPLIER_CONFIRMED':
    tickets=rail_tickets(b.get('ticket_numbers'),len(order.passengers or []))
    if f.state=='SUPPLIER_CONFIRMED' and (f.supplier_confirmation_reference!=b.get('supplier_confirmation_reference') or tickets!=order.ticket_numbers or (b.get('external_operation_id') and b['external_operation_id']!=f.external_operation_id)):
     raise ValueError('RAIL_CONFIRMED_TICKET_IDENTITY_IMMUTABLE')
   if vertical=='FLIGHT' and state=='SUPPLIER_CONFIRMED':
    from go_hotel.services.flight_change_resolution import _tickets, _printable_token
    count=len(order.passengers or [])*len(order.current_itinerary or [])
    if not count:raise ValueError('FLIGHT_REISSUED_TICKETS_INVALID')
    tickets=_tickets(b.get('ticket_numbers'),count)
    _printable_token(b.get('supplier_confirmation_reference'),16,'FLIGHT_SUPPLIER_REFERENCE_INVALID')
    if f.state=='SUPPLIER_CONFIRMED' and (f.supplier_confirmation_reference!=b.get('supplier_confirmation_reference') or tickets!=order.ticket_numbers or (b.get('external_operation_id') and b['external_operation_id']!=f.external_operation_id)):
     raise ValueError('FLIGHT_CONFIRMED_TICKET_IDENTITY_IMMUTABLE')
   same_external=(not b.get('external_operation_id') or b.get('external_operation_id')==f.external_operation_id)
   same_confirmation=(state!='SUPPLIER_CONFIRMED' or b.get('supplier_confirmation_reference')==f.supplier_confirmation_reference)
   payment_state=_payment_state(s,f,order)
   if f.state==state and same_external and same_confirmation:
    # Idempotent supplier delivery does not make an old money projection fresh.
    # Refresh only the read model; never replay the supplier mutation/event.
    expected_refund='REFUND_COMPLETED' if payment_state=='REFUNDED' else existing_life.refund_state if existing_life else 'NOT_REQUESTED'
    if not existing_life or existing_life.payment_state!=payment_state or existing_life.refund_state!=expected_refund:
     life=_project_lifecycle(s,f,order,vertical,state,b['evidence_reference'],existing_life,payment_state)
     s.commit()
    else:life=out(existing_life)
    return {'fulfillment':out(f),'unified_lifecycle':life,'replayed':True}
   if state=='SUPPLIER_CONFIRMED':
    if payment_state!='PAID' or f.state not in {'CAPTURE_CONFIRMED_READY_FOR_SUPPLIER','SUPPLIER_MUTATION_SENT','UNKNOWN_EXTERNAL_STATE'}:raise ValueError('FULL_CAPTURED_MONEY_GRAPH_REQUIRED_BEFORE_SUPPLIER_CONFIRMATION')
   f.state=state;f.external_operation_id=b.get('external_operation_id') or f.external_operation_id;f.supplier_confirmation_reference=b.get('supplier_confirmation_reference') or f.supplier_confirmation_reference;f.evidence_reference=b['evidence_reference'];f.updated_at=now()
   s.add(FEvent(order_supplier_fulfillment_event_id=ident('osfe'),order_supplier_fulfillment_id=f.order_supplier_fulfillment_id,event_type='SUPPLIER_FACT_RECORDED',state=state,evidence_reference=b['evidence_reference'],payload_hash=digest(b),occurred_at=now()))
   if state=='SUPPLIER_CONFIRMED':
    order.status='TICKETED' if vertical in {'FLIGHT','RAIL'} else 'CONFIRMED';order.updated_at=now()
    if hasattr(order,'supplier_confirmation_no'):order.supplier_confirmation_no=f.supplier_confirmation_reference
    if hasattr(order,'pnr') and not getattr(order,'pnr',None):order.pnr=f.supplier_confirmation_reference
    if hasattr(order,'booking_reference') and not getattr(order,'booking_reference',None):order.booking_reference=f.supplier_confirmation_reference
    if hasattr(order,'ticket_numbers') and b.get('ticket_numbers'):order.ticket_numbers=list(b.get('ticket_numbers'))
    if hasattr(order,'supplier_reference'):order.supplier_reference=f.supplier_confirmation_reference
    if vertical=='ATTRACTION' and hasattr(order,'voucher_code') and not getattr(order,'voucher_code',None):order.voucher_code=b.get('voucher_code') or f.supplier_confirmation_reference
    if vertical=='FLIGHT':
     from go_hotel.flight.coupons import issue_in
     issue_in(s,order)
    append_vertical_evidence(s,vertical,f.business_id,'SUPPLIER_CONFIRMED',order.status,{'supplier_confirmation_reference':f.supplier_confirmation_reference,'external_operation_id':f.external_operation_id,'evidence_reference':b['evidence_reference'],'actor_id':b.get('actor_id')})
   elif state=='SUPPLIER_FAILED':
    if vertical in {'RAIL','ATTRACTION'}:capacity.release_all_in(s,vertical,f.business_id)
    order.status='FAILED';order.updated_at=now();append_vertical_evidence(s,vertical,f.business_id,'SUPPLIER_FAILED',order.status,{'external_operation_id':f.external_operation_id,'evidence_reference':b['evidence_reference']})
   else:
    order.status='UNKNOWN_EXTERNAL_STATE';order.updated_at=now();append_vertical_evidence(s,vertical,f.business_id,'EXTERNAL_STATE_UNKNOWN',order.status,{'external_operation_id':f.external_operation_id,'evidence_reference':b['evidence_reference']})
   life=_project_lifecycle(s,f,order,vertical,state,b['evidence_reference'],existing_life,payment_state)
   s.commit();return {'fulfillment':out(f),'unified_lifecycle':life}
order_supplier_fulfillment_service=OrderSupplierFulfillmentService()
