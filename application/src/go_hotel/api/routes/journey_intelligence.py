from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import consumer_principal
from go_hotel.security.service import Principal
from go_hotel.journey.intelligence import journey_intelligence_service
router=APIRouter(tags=['sprint3f-journey-intelligence'])
class Disruption(BaseModel):
    source_item_id:str|None=None
    source_vertical:str|None=None
    source_order_id:str|None=None
    event_type:str
    severity:str='MEDIUM'
    event_at:str|None=None
    facts:dict=Field(default_factory=dict)
def call(fn,*args):
    try:return {'data':fn(*args)}
    except ValueError as e: raise HTTPException(404 if 'NOT_FOUND' in str(e) else 409,detail=str(e))
@router.post('/v1/trips/journeys/{journey_id}/disruptions/evaluate')
def evaluate(journey_id:str,b:Disruption,p:Principal=Depends(consumer_principal)):
    return call(journey_intelligence_service.evaluate,p.user_id,journey_id,b.model_dump())
@router.get('/v1/trips/journeys/{journey_id}/disruptions/latest')
def latest(journey_id:str,p:Principal=Depends(consumer_principal)):
    return call(journey_intelligence_service.latest,p.user_id,journey_id)
@router.post('/v1/trips/journeys/{journey_id}/advice/{advice_id}/acknowledge')
def acknowledge(journey_id:str,advice_id:str,p:Principal=Depends(consumer_principal)):
    return call(journey_intelligence_service.acknowledge,p.user_id,journey_id,advice_id)
