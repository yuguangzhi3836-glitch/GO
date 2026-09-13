from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel
from go_hotel.security.deps import consumer_principal,supplier_principal,admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.consumer_growth_direct_value import consumer_growth_direct_value_service as svc
router=APIRouter(tags=['go-consumer-growth-official-direct-value'])
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a,**kw):
    try:return {'data':fn(*a,**kw)}
    except ValueError as e:
        code=404 if str(e) in {'SUPPLIER_HOTEL_NOT_FOUND','JOURNEY_NOT_FOUND','TRAVELER_NOT_FOUND'} else 409
        raise HTTPException(code,detail=str(e))
@router.get('/v1/hotels/{hotel_id}/value-layers')
def layers(hotel_id:str,check_in:str|None=None,check_out:str|None=None,room_type_key:str|None=None,occupancy_key:str|None=None,meal_plan_key:str|None=None,cancellation_key:str|None=None,tax_fee_key:str|None=None,eligibility_key:str='PUBLIC',currency:str='CNY',direct_rate_minor:int|None=None):
    q={k:v for k,v in locals().copy().items() if k!='hotel_id' and v is not None};return {'data':svc.value_layers(hotel_id,q)}
@router.put('/v1/supplier/direct-value/hotels/{hotel_id}/offer')
def supplier_offer(hotel_id:str,b:P,p:Principal=Depends(supplier_principal)):return call(svc.upsert_offer,p.supplier_id,hotel_id,b.model_dump(exclude_none=True))
@router.post('/v1/supplier/direct-value/hotels/{hotel_id}/economics/simulate')
def supplier_economics_sim(hotel_id:str,b:P,p:Principal=Depends(supplier_principal)):return call(svc.simulate_economics,p.supplier_id,hotel_id,b.model_dump(exclude_none=True))
@router.get('/v1/supplier/direct-value/hotels/{hotel_id}/economics')
def supplier_economics(hotel_id:str,limit:int=20,p:Principal=Depends(supplier_principal)):return call(svc.supplier_economics,p.supplier_id,hotel_id,min(limit,100))
@router.post('/internal/v1/admin/direct-value/benchmarks',status_code=201)
def benchmark(b:P,p:Principal=Depends(admin_principal)):return call(svc.add_benchmark,b.model_dump(exclude_none=True))
@router.get('/internal/v1/admin/direct-value/overview')
def overview(p:Principal=Depends(admin_principal)):return {'data':svc.admin_overview()}
@router.post('/v1/consumer/growth/events',status_code=201)
def growth_event(b:P,p:Principal=Depends(consumer_principal)):
    d=b.model_dump(exclude_none=True);event=d.pop('event_type');return call(svc.record_event,p.user_id,event,**d)
@router.post('/v1/trips/journeys/{journey_id}/invites',status_code=201)
def trip_invite(journey_id:str,b:P,p:Principal=Depends(consumer_principal)):return call(svc.create_trip_invite,p.user_id,journey_id,b.model_dump(exclude_none=True))
@router.post('/v1/consumer/growth/trip-invites/{token}/join')
def trip_join(token:str,p:Principal=Depends(consumer_principal)):return call(svc.join_trip,p.user_id,token)
@router.post('/v1/consumer/profile/travelers/{traveler_id}/claim-requests',status_code=201)
def claim_create(traveler_id:str,b:P,p:Principal=Depends(consumer_principal)):return call(svc.create_claim,p.user_id,traveler_id,b.model_dump()['target_email'])
@router.post('/v1/consumer/profile/traveler-claims/{token}/accept')
def claim_accept(token:str,p:Principal=Depends(consumer_principal)):return call(svc.accept_claim,p.user_id,token)
@router.post('/v1/consumer/trips/import-intents',status_code=201)
def trip_import(b:P,p:Principal=Depends(consumer_principal)):return call(svc.create_trip_import_intent,p.user_id,b.model_dump(exclude_none=True))
@router.get('/internal/v1/admin/consumer-growth/metrics')
def growth_metrics(days:int=30,p:Principal=Depends(admin_principal)):return {'data':svc.growth_metrics(days)}
