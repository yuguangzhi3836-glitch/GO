from fastapi import APIRouter,Depends,HTTPException,Header
from pydantic import BaseModel,Field
from go_hotel.security.deps import consumer_principal,admin_principal,optional_consumer_principal
from go_hotel.security.service import Principal
from go_hotel.attractions.service import attraction_service as a
from go_hotel.api.idempotency import run_idempotent
from go_hotel.api.refund_confirmation import RefundConfirmation
from go_hotel.services.booking_data_release import release_booking_data
from go_hotel.db.session import SessionLocal
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
router=APIRouter(tags=["sprint3d-attractions"])
def w(fn,*x):
 try:return {"data":fn(*x)}
 except ValueError as e:
  msg=str(e)
  if msg=='REFUND_QUOTE_CHANGED_RECONFIRM_REQUIRED':raise HTTPException(409,detail=msg)
  if msg in {'REFUND_ALREADY_PROCESSING','REFUND_LEASE_LOST','UNPAID_CANCELLATION_NOT_ALLOWED','PAYMENT_ALREADY_STARTED_RECONCILIATION_REQUIRED'}:raise HTTPException(409,detail=msg)
  code=503 if "PROVIDER_TRUTH_REQUIRED" in msg else (422 if any(k in msg for k in ("ILLEGAL_STATE","CHANGEABLE","REFUNDABLE","INVALID","RECONCILIATION","INVENTORY_CHANGED")) else (400 if "NON_REFUNDABLE" in msg else 404))
  raise HTTPException(code,detail=str(e))
class Search(BaseModel):destination:str;visit_date:str;product_type:str|None=None;currency:str="CNY"
class Prebook(BaseModel):offer_id:str;visit_date:str;quantity:int=Field(default=1,ge=1,le=100,strict=True);currency:str="CNY";session_time:str|None=None
class Book(BaseModel):prebook_id:str;offer_id:str;visit_date:str;session_time:str|None=None;quantity:int=Field(default=1,ge=1,le=100,strict=True);currency:str="CNY";attendees:list[dict]=Field(default_factory=list);traveler_ids:list[str]=Field(default_factory=list)
class Change(BaseModel):new_visit_date:str;new_session_time:str|None=None
class Redeem(BaseModel):evidence_reference:str
class ExternalState(BaseModel):state:str;evidence_reference:str;supplier_reference:str|None=None;voucher_code:str|None=None
@router.post("/v1/attractions/search")
def search(b:Search):
 try:items=a.search(**b.model_dump())
 except ValueError as e:
  msg=str(e);raise HTTPException(503 if "PROVIDER_TRUTH_REQUIRED" in msg else 422,detail=msg)
 return {"data":{"items":items,"comparison_basis":["final_price","session","eligibility","inventory","change_refund"]}}
@router.post("/v1/attractions/prebook")
def prebook(b:Prebook,p:Principal|None=Depends(optional_consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
 return run_idempotent('ATTRACTION_PREBOOK',idempotency_key,{'account':p.user_id if p else None,**b.model_dump()},lambda:w(a.prebook,b.offer_id,b.visit_date,b.quantity,b.currency,b.session_time,p.user_id if p else None))
@router.post("/v1/attractions/orders")
def book(b:Book,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):

 def execute():
  body=b.model_dump(); released=release_booking_data(p.user_id,'ATTRACTION',b.traveler_ids,b.attendees,requester_id=p.user_id); body['attendees']=released['items']
  response=w(a.create_order,p.user_id,body)
  if released['release_ids']:
   with SessionLocal.begin() as s: append_vertical_evidence(s,'ATTRACTION',response['data']['order_id'],'VAULT_BOOKING_DATA_RELEASED',response['data']['status'],{'release_ids':released['release_ids'],'minimum_necessary':True})
  return response
 return run_idempotent('ATTRACTION_CREATE_ORDER',idempotency_key,{'user_id':p.user_id,**b.model_dump()},execute)
@router.get("/v1/attractions/orders/{order_id}")
def order(order_id:str,p:Principal=Depends(consumer_principal)):return w(a.get,p.user_id,order_id)
@router.get("/v1/attractions/trips")
def trips(p:Principal=Depends(consumer_principal)):return {"data":{"items":a.trips(p.user_id)}}
@router.post("/v1/attractions/orders/{order_id}/change-quote")
def cq(order_id:str,b:Change,p:Principal=Depends(consumer_principal)):return w(a.change_quote,p.user_id,order_id,b.new_visit_date,b.new_session_time)
@router.post("/v1/attractions/orders/{order_id}/execute-change/{quote_id}")
def ec(order_id:str,quote_id:str,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
 return run_idempotent('ATTRACTION_EXECUTE_CHANGE',idempotency_key,{'user_id':p.user_id,'order_id':order_id,'quote_id':quote_id},lambda:w(a.execute_change,p.user_id,order_id,quote_id))
@router.get("/v1/attractions/orders/{order_id}/refund-quote")
def rq(order_id:str,p:Principal=Depends(consumer_principal)):return w(a.refund_quote,p.user_id,order_id)
@router.post("/v1/attractions/orders/{order_id}/refund")
def refund(order_id:str,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
 return run_idempotent('ATTRACTION_REFUND',idempotency_key,{'user_id':p.user_id,'order_id':order_id},lambda:w(a.refund,p.user_id,order_id))
@router.post("/v1/attractions/orders/{order_id}/redeem")
def redeem(order_id:str,b:Redeem,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
 return run_idempotent('ATTRACTION_REDEEM',idempotency_key,{'user_id':p.user_id,'order_id':order_id,**b.model_dump()},lambda:w(a.redeem,p.user_id,order_id,b.evidence_reference))
@router.post("/internal/v1/admin/attractions/orders/{order_id}/external-state")
def external_state(order_id:str,b:ExternalState,p:Principal=Depends(admin_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
 return run_idempotent('ATTRACTION_ADMIN_EXTERNAL_STATE',idempotency_key,{'actor':p.user_id,'order_id':order_id,**b.model_dump()},lambda:w(a.admin_external_state,order_id,b.state,b.evidence_reference,p.user_id,b.supplier_reference,b.voucher_code))

@router.post('/v1/attractions/orders/{order_id}/cancel-unpaid')
def cancel_unpaid(order_id:str,p:Principal=Depends(consumer_principal)):
 from go_hotel.services.vertical_capacity import cancel_unpaid as cancel
 return w(cancel,'ATTRACTION',p.user_id,order_id,a.out)

@router.post('/v1/attractions/orders/{order_id}/refund-confirmed')
def refund_confirmed(order_id:str,b:RefundConfirmation,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
 return run_idempotent('ATTRACTION_REFUND_CONFIRMED',idempotency_key,
  {'user_id':p.user_id,'order_id':order_id,**b.model_dump()},lambda:w(a.refund,p.user_id,order_id,b.quote_hash))
