from datetime import datetime,timezone
import hashlib,json,uuid
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service
from go_hotel.db.models import (
 OrderSupplierFulfillmentRow as Fulfillment,OrderSupplierFulfillmentEventRow as FEvent,
 OrderRow,FlightOrderRow,RailOrderRow,MobilityRideOrderRow,MobilityRentalOrderRow,AttractionOrderRow,
 ConsumerUnifiedLifecycleRow as Life,ConsumerUnifiedLifecycleEventRow as LifeEvent,
 OmnichannelPaymentIntentRow as Intent,OmnichannelMoneyMovementRow as Movement
)
MODELS={'HOTEL_ORDER':('HOTEL',OrderRow),'FLIGHT_ORDER':('FLIGHT',FlightOrderRow),'RAIL_ORDER':('RAIL',RailOrderRow),'RIDE_ORDER':('RIDE',MobilityRideOrderRow),'RENTAL_ORDER':('RENTAL',MobilityRentalOrderRow),'ATTRACTION_ORDER':('ATTRACTION',AttractionOrderRow)}
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}
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
  with SessionLocal() as s:
   f=s.scalar(select(Fulfillment).where(Fulfillment.order_supplier_fulfillment_id==fid).with_for_update())
   if not f:raise ValueError('SUPPLIER_FULFILLMENT_NOT_FOUND')
   if f.state=='SUPPLIER_CONFIRMED' and state!='SUPPLIER_CONFIRMED':raise ValueError('SUPPLIER_CONFIRMATION_IMMUTABLE')
   vertical,model=MODELS[f.business_type];order=s.scalar(select(model).where(model.order_id==f.business_id).with_for_update())
   if not order:raise ValueError('AUTHORITATIVE_ORDER_FACT_REQUIRED')
   terminal_by_vertical={
    'HOTEL':{'CANCELLED','CONVERTED_TO_CREDIT','FAILED'},
    'FLIGHT':{'REFUNDED','FAILED'},
    'RAIL':{'REFUNDED','FAILED'},
    'RIDE':{'REFUNDED','COMPLETED','FAILED'},
    'RENTAL':{'REFUNDED','COMPLETED','FAILED'},
    'ATTRACTION':{'REFUNDED','FULFILLED','CLOSED_BY_SUPPLIER','FAILED'},
   }
   if str(order.status) in terminal_by_vertical.get(vertical,set()):raise ValueError('TERMINAL_ORDER_SUPPLIER_FACT_REJECTED')
   existing_life=s.scalar(select(Life).where(Life.vertical==vertical,Life.order_id==f.business_id))
   projected_life='CONFIRMED' if state=='SUPPLIER_CONFIRMED' else ('FAILED' if state=='SUPPLIER_FAILED' else 'UNKNOWN_EXTERNAL_STATE')
   if existing_life and existing_life.lifecycle_state in {'COMPLETED','CANCELLED','FAILED'} and projected_life!=existing_life.lifecycle_state:
    raise ValueError('TERMINAL_LIFECYCLE_SUPPLIER_FACT_REJECTED')
   same_external=(not b.get('external_operation_id') or b.get('external_operation_id')==f.external_operation_id)
   same_confirmation=(state!='SUPPLIER_CONFIRMED' or b.get('supplier_confirmation_reference')==f.supplier_confirmation_reference)
   if f.state==state and same_external and same_confirmation:
    life=out(existing_life) if existing_life else None
    return {'fulfillment':out(f),'unified_lifecycle':life,'replayed':True}
   if state=='SUPPLIER_CONFIRMED':
    i=s.get(Intent,f.payment_intent_id);captured=sum(x.amount_minor for x in s.scalars(select(Movement).where(Movement.root_payment_intent_id==f.payment_intent_id,Movement.movement_type=='CAPTURE',Movement.state=='CONFIRMED')).all())
    if not i or captured!=i.amount_minor or f.state not in {'CAPTURE_CONFIRMED_READY_FOR_SUPPLIER','SUPPLIER_MUTATION_SENT','UNKNOWN_EXTERNAL_STATE'}:raise ValueError('FULL_CAPTURED_MONEY_GRAPH_REQUIRED_BEFORE_SUPPLIER_CONFIRMATION')
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
    append_vertical_evidence(s,vertical,f.business_id,'SUPPLIER_CONFIRMED',order.status,{'supplier_confirmation_reference':f.supplier_confirmation_reference,'external_operation_id':f.external_operation_id,'evidence_reference':b['evidence_reference']})
   elif state=='SUPPLIER_FAILED':
    order.status='FAILED';order.updated_at=now();append_vertical_evidence(s,vertical,f.business_id,'SUPPLIER_FAILED',order.status,{'external_operation_id':f.external_operation_id,'evidence_reference':b['evidence_reference']})
   else:
    order.status='UNKNOWN_EXTERNAL_STATE';order.updated_at=now();append_vertical_evidence(s,vertical,f.business_id,'EXTERNAL_STATE_UNKNOWN',order.status,{'external_operation_id':f.external_operation_id,'evidence_reference':b['evidence_reference']})
   life_state='CONFIRMED' if state=='SUPPLIER_CONFIRMED' else ('FAILED' if state=='SUPPLIER_FAILED' else 'UNKNOWN_EXTERNAL_STATE')
   life=consumer_unified_lifecycle_service.project_in_session(s,{'account_id':order.account_id,'vertical':vertical,'order_id':f.business_id,'supplier_id':f.supplier_id,'title':f'{vertical} {f.business_id}','lifecycle_state':life_state,'payment_state':'PAID','refund_state':'NOT_REQUESTED','change_allowed':False,'cancel_allowed':state=='SUPPLIER_CONFIRMED','facts':{'supplier_confirmation_reference':f.supplier_confirmation_reference,'external_operation_id':f.external_operation_id},'evidence_reference':b['evidence_reference'],'source_updated_at':now(),'event_type':'SUPPLIER_FACT_PROJECTED'})
   s.commit();return {'fulfillment':out(f),'unified_lifecycle':life}
order_supplier_fulfillment_service=OrderSupplierFulfillmentService()
