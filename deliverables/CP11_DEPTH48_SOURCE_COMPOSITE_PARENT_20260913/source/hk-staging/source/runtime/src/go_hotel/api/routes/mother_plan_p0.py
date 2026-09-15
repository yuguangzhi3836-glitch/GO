from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import consumer_principal,admin_principal,supplier_principal
from go_hotel.security.service import Principal
from go_hotel.services.mother_plan_p0 import mother_plan_p0_service as svc
router=APIRouter(tags=['mother-plan-p0-product-compliance'])
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/v1/flights/orders/{order_id}/check-in')
def checkin(order_id:str,p:Principal=Depends(consumer_principal)):return call(svc.checkin,p.user_id,order_id)
@router.post('/internal/v1/flights/orders/{order_id}/check-in/facts')
def checkin_fact(order_id:str,b:P,p:Principal=Depends(admin_principal)):return call(svc.ingest_checkin,order_id,b.model_dump(exclude_none=True),p.user_id)
@router.put('/v1/mobility/rides/orders/{ride_id}/flight-tracking')
def bind(ride_id:str,b:P,p:Principal=Depends(consumer_principal)):return call(svc.bind_ride,p.user_id,ride_id,b.model_dump(exclude_none=True))
@router.get('/v1/mobility/rides/orders/{ride_id}/flight-tracking')
def tracking(ride_id:str,p:Principal=Depends(consumer_principal)):return call(svc.ride_tracking,p.user_id,ride_id)
@router.post('/internal/v1/mobility/flight-events/verified')
def flight_event(b:P,p:Principal=Depends(admin_principal)):return call(svc.ingest_flight_event,b.model_dump(exclude_none=True),p.user_id)
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
