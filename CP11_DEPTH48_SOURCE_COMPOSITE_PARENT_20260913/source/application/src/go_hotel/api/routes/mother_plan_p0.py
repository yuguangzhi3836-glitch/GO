from fastapi import APIRouter,Depends,HTTPException,Response
from pydantic import BaseModel,Field,ConfigDict
from typing import Literal
from go_hotel.services.travel_operational_facts import travel_facts
from go_hotel.security.deps import consumer_principal,admin_principal,supplier_principal
from go_hotel.security.service import Principal
from go_hotel.services.mother_plan_p0 import mother_plan_p0_service as svc
router=APIRouter(tags=['mother-plan-p0-product-compliance'])
class P(BaseModel):model_config={'extra':'allow'}
class SignedFact(BaseModel):
 model_config=ConfigDict(extra='forbid')
 fact:dict
 signature_hex:str=Field(min_length=128,max_length=128,pattern='^[0-9a-f]+$')
class AuthorityDraft(BaseModel):
 model_config=ConfigDict(extra='forbid')
 provider_id:str
 environment:Literal['ENGINEERING','SANDBOX']
 source_type:Literal['AIRLINE_OFFICIAL','AUTHORIZED_AIRLINE_PROVIDER']
 contract:dict
 public_key_hex:str=Field(min_length=64,max_length=64)
 valid_from_ms:int
 valid_until_ms:int
class AuthorityReview(BaseModel):
 model_config=ConfigDict(extra='forbid')
 expected_revision:int=Field(ge=1)
 action:Literal['APPROVE','REVOKE']
class RideTracking(BaseModel):
 model_config=ConfigDict(extra='forbid')
 flight_identity:dict|None=None
 authority_id:str|None=None
 tracking_enabled:bool=True
 delay_protection_enabled:bool=False
 expected_revision:int=Field(ge=0)
def travel_admin(p:Principal=Depends(admin_principal)):
 if 'admin:rules' not in p.permissions:raise HTTPException(403,detail='PERMISSION_DENIED')
 return p
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/v1/flights/orders/{order_id}/check-in')
def checkin(order_id:str,response:Response,p:Principal=Depends(consumer_principal)):
 response.headers['Cache-Control']='no-store'
 return call(svc.checkin,p.user_id,order_id)
@router.post('/internal/v1/flights/orders/{order_id}/check-in/facts')
def checkin_fact(order_id:str,b:SignedFact,p:Principal=Depends(travel_admin)):return call(svc.ingest_checkin,order_id,b.model_dump(exclude_none=True),p.user_id)
@router.put('/v1/mobility/rides/orders/{ride_id}/flight-tracking')
def bind(ride_id:str,b:RideTracking,p:Principal=Depends(consumer_principal)):return call(svc.bind_ride,p.user_id,ride_id,b.model_dump(exclude_none=True))
@router.get('/v1/mobility/rides/orders/{ride_id}/flight-tracking')
def tracking(ride_id:str,p:Principal=Depends(consumer_principal)):return call(svc.ride_tracking,p.user_id,ride_id)
@router.get('/v1/mobility/rides/orders/{ride_id}/flight-tracking/options')
def tracking_options(ride_id:str,p:Principal=Depends(consumer_principal)):
 from go_hotel.mobility.ride.flight_sync import flight_ride_sync
 return call(flight_ride_sync.options,p.user_id,ride_id)
@router.get('/internal/v1/mobility/flight-adjustments')
def flight_adjustments(p:Principal=Depends(travel_admin)):
 from go_hotel.mobility.ride.flight_sync import flight_ride_sync
 return call(flight_ride_sync.operations)
@router.post('/internal/v1/mobility/flight-events/verified')
def flight_event(b:SignedFact,p:Principal=Depends(travel_admin)):return call(svc.ingest_flight_event,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/travel-fact-authorities',status_code=201)
def authority_draft(b:AuthorityDraft,p:Principal=Depends(travel_admin)):
 return call(travel_facts.register,b.model_dump(),p.user_id)
@router.post('/internal/v1/travel-fact-authorities/{authority_id}/review')
def authority_review(authority_id:str,b:AuthorityReview,p:Principal=Depends(travel_admin)):
 return call(travel_facts.review,authority_id,p.user_id,b.expected_revision,b.action)
@router.post('/v1/go-offer/requirements',status_code=201)
def requirement(b:P,p:Principal=Depends(consumer_principal)):return call(svc.create_requirement,p.user_id,b.model_dump(exclude_none=True))
@router.get('/v1/go-offer/requirements/{requirement_id}')
def requirement_get(requirement_id:str,p:Principal=Depends(consumer_principal)):return call(svc.requirement,p.user_id,requirement_id)
@router.post('/v1/supplier/go-offer/requirements/{requirement_id}/quotes',status_code=201)
def manual_quote(requirement_id:str,b:P,p:Principal=Depends(supplier_principal)):return call(svc.manual_quote,p.supplier_id,requirement_id,b.model_dump(exclude_none=True))
@router.post('/v1/go-offer/requirements/{requirement_id}/quotes/{quote_id}/select')
def select_quote(requirement_id:str,quote_id:str,p:Principal=Depends(consumer_principal)):return call(svc.accept_quote,p.user_id,requirement_id,quote_id)
@router.post('/v1/go-offer/requirements/{requirement_id}/quotes/{quote_id}/prebook-revalidate',status_code=201)
def prebook(requirement_id:str,quote_id:str,b:P,p:Principal=Depends(consumer_principal)):return call(svc.start_prebook,p.user_id,requirement_id,quote_id,b.model_dump(exclude_none=True))
@router.post('/v1/supplier/go-offer/prebooks/{prebook_id}/revalidate')
def supplier_revalidate(prebook_id:str,b:P,p:Principal=Depends(supplier_principal)):return call(svc.supplier_revalidate,p.supplier_id,prebook_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/v1/go-offer/prebooks/{prebook_id}/order-handoff',status_code=201)
def order_handoff(prebook_id:str,b:P,p:Principal=Depends(consumer_principal)):return call(svc.order_handoff,p.user_id,prebook_id,b.model_dump(exclude_none=True))
@router.get('/v1/supplier/go-offer/requirements')
def supplier_requirements(p:Principal=Depends(supplier_principal)):return call(svc.supplier_requirements,p.supplier_id)
@router.get('/internal/v1/go-offer/status')
def admin_status(p:Principal=Depends(admin_principal)):return call(svc.admin_offer_status)
