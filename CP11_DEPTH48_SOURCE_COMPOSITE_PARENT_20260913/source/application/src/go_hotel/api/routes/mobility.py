from fastapi import APIRouter,Depends,HTTPException,Header
from pydantic import BaseModel,Field,ConfigDict
from typing import Literal
from go_hotel.security.deps import consumer_principal,admin_principal
from go_hotel.security.service import Principal
from go_hotel.mobility.service import mobility_service as m
from go_hotel.api.idempotency import run_idempotent
from go_hotel.api.refund_confirmation import RefundConfirmation
from go_hotel.services.booking_data_release import release_booking_data
from go_hotel.db.session import SessionLocal
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
router=APIRouter(tags=["sprint3c-mobility"])
def w(fn,*a):
 try:return {"data":fn(*a)}
 except ValueError as e:
  if str(e) in {'REFUND_QUOTE_CHANGED_RECONFIRM_REQUIRED','REFUND_HISTORICAL_CONSENT_UNAVAILABLE','REFUND_OPERATION_INTEGRITY_INVALID'}:raise HTTPException(409,detail=str(e))
  msg=str(e); code=503 if "PROVIDER_TRUTH_REQUIRED" in msg else (422 if any(x in msg for x in ("ILLEGAL_STATE","CHANGEABLE","CANCELLABLE","INVALID","RECONCILIATION","QUOTE_","RECONFIRM","NOT_CONFIRMED","FORBIDDEN")) else 404)
  raise HTTPException(code,detail=str(e))
class RideSearch(BaseModel):pickup:str;dropoff:str;pickup_at:str;currency:str="CNY"
class RideBook(RideSearch):
 flight_identity:dict|None=None;flight_authority_id:str|None=None
 offer_id:str;flight_no:str|None=None;passengers:list[dict]=Field(default_factory=list);traveler_ids:list[str]=Field(default_factory=list);flight_tracking_enabled:bool=False;delay_protection_enabled:bool=False;delay_protection_free_wait_minutes:int=0;max_free_wait_minutes:int|None=None;supplier_rule_snapshot:dict=Field(default_factory=dict)
class RentalSearch(BaseModel):pickup_location:str;return_location:str;pickup_at:str;return_at:str;currency:str="CNY"
class RentalBook(RentalSearch):offer_id:str;drivers:list[dict]=Field(default_factory=list);traveler_ids:list[str]=Field(default_factory=list)
class Modify(BaseModel):new_time:str
class Fulfillment(BaseModel):action:str;evidence_reference:str
class ExternalState(BaseModel):state:str;evidence_reference:str
@router.post("/v1/mobility/rides/search")
def rs(b:RideSearch):
 try:items=m.ride_search(**b.model_dump())
 except ValueError as e:
  msg=str(e);raise HTTPException(503 if "PROVIDER_TRUTH_REQUIRED" in msg else 422,detail=msg)
 return {"data":{"items":items,"comparison_basis":["final_price","waiting_time","meet_and_greet","cancellation"]}}
@router.post("/v1/mobility/rides/orders")
def rb(b:RideBook,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):

 def execute():
  body=b.model_dump(); released=release_booking_data(p.user_id,'RIDE',b.traveler_ids,b.passengers,requester_id=p.user_id); body['passengers']=released['items']; body.pop('traveler_ids',None)
  response=w(m.create_ride,p.user_id,body)
  if released['release_ids']:
   with SessionLocal.begin() as s: append_vertical_evidence(s,'RIDE',response['data']['order_id'],'VAULT_BOOKING_DATA_RELEASED',response['data']['status'],{'release_ids':released['release_ids'],'minimum_necessary':True})
  return response
 return run_idempotent('RIDE_CREATE_ORDER',idempotency_key,{'user_id':p.user_id,**b.model_dump()},execute)
@router.post("/v1/mobility/rentals/search")
def cs(b:RentalSearch):
 try:items=m.rental_search(**b.model_dump())
 except ValueError as e:
  msg=str(e);raise HTTPException(503 if "PROVIDER_TRUTH_REQUIRED" in msg else 422,detail=msg)
 return {"data":{"items":items,"comparison_basis":["final_price","insurance","mileage","deposit","cancellation"]}}
@router.post("/v1/mobility/rentals/orders")
def cb(b:RentalBook,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):

 def execute():
  body=b.model_dump(); released=release_booking_data(p.user_id,'RENTAL',b.traveler_ids,b.drivers,requester_id=p.user_id); body['drivers']=released['items']; body.pop('traveler_ids',None)
  response=w(m.create_rental,p.user_id,body)
  if released['release_ids']:
   with SessionLocal.begin() as s: append_vertical_evidence(s,'RENTAL',response['data']['order_id'],'VAULT_BOOKING_DATA_RELEASED',response['data']['status'],{'release_ids':released['release_ids'],'minimum_necessary':True})
  return response
 return run_idempotent('RENTAL_CREATE_ORDER',idempotency_key,{'user_id':p.user_id,**b.model_dump()},execute)
@router.get("/v1/mobility/orders/{order_id}")
def order(order_id:str,p:Principal=Depends(consumer_principal)):return w(m.get_order,p.user_id,order_id)
@router.get("/v1/mobility/trips")
def trips(p:Principal=Depends(consumer_principal)):return {"data":{"items":m.trips(p.user_id)}}
@router.post("/v1/mobility/orders/{order_id}/modify")
def modify(order_id:str,b:Modify,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
 return run_idempotent('MOBILITY_MODIFY',idempotency_key,{'user_id':p.user_id,'order_id':order_id,**b.model_dump()},lambda:w(m.modify,p.user_id,order_id,b.new_time))
@router.get("/v1/mobility/orders/{order_id}/refund-quote")
def rq(order_id:str,p:Principal=Depends(consumer_principal)):return w(m.refund_quote,p.user_id,order_id)

@router.post('/v1/mobility/orders/{order_id}/refund-confirmed')
def refund_confirmed(order_id:str,b:RefundConfirmation,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
 return run_idempotent('MOBILITY_REFUND_CONFIRMED',idempotency_key,{'user_id':p.user_id,'order_id':order_id,**b.model_dump()},lambda:w(m.cancel,p.user_id,order_id,b.quote_hash))
@router.post("/v1/mobility/orders/{order_id}/cancel")
def cancel(order_id:str,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
 return run_idempotent('MOBILITY_CANCEL',idempotency_key,{'user_id':p.user_id,'order_id':order_id},lambda:w(m.cancel,p.user_id,order_id))
@router.post("/v1/mobility/orders/{order_id}/fulfillment")
def fulfill(order_id:str,b:Fulfillment,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
 return run_idempotent('MOBILITY_FULFILLMENT',idempotency_key,{'user_id':p.user_id,'order_id':order_id,**b.model_dump()},lambda:w(m.fulfill,p.user_id,order_id,b.action,b.evidence_reference))
@router.post("/internal/v1/admin/mobility/orders/{order_id}/external-state")
def external_state(order_id:str,b:ExternalState,p:Principal=Depends(admin_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
 return run_idempotent('MOBILITY_ADMIN_EXTERNAL_STATE',idempotency_key,{'actor':p.user_id,'order_id':order_id,**b.model_dump()},lambda:w(m.admin_external_state,order_id,b.state,b.evidence_reference,p.user_id))

class RentalChangeDates(BaseModel):
 model_config=ConfigDict(extra='forbid')
 pickup_at:str=Field(min_length=1,max_length=40)
 return_at:str=Field(min_length=1,max_length=40)
class RentalChangeConfirmation(BaseModel):
 model_config=ConfigDict(extra='forbid')
 expected_difference_minor:int=Field(strict=True)
 currency:Literal['CNY']
 mode:Literal['CONTRACT_SIMULATOR']
@router.post('/v1/mobility/rentals/orders/{order_id}/change-quotes')
def rental_change_quote(order_id:str,b:RentalChangeDates,p:Principal=Depends(consumer_principal)):
 from go_hotel.mobility.rental.changes import quote
 return w(quote,p.user_id,order_id,b.pickup_at,b.return_at)
@router.post('/v1/mobility/rentals/orders/{order_id}/changes/{quote_id}')
def rental_execute_change(order_id:str,quote_id:str,b:RentalChangeConfirmation,p:Principal=Depends(consumer_principal)):
 from go_hotel.mobility.rental.changes import execute
 return w(execute,p.user_id,order_id,quote_id,b.expected_difference_minor,b.currency)
