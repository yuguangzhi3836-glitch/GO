from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import consumer_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery import journey_recovery_service
router=APIRouter(tags=['sprint3g-journey-recovery'])
class BuildBody(BaseModel): advice_id:str|None=None
class SelectBody(BaseModel): option_ids:list[str]=Field(default_factory=list)
def call(fn,*args):
    try:return {'data':fn(*args)}
    except ValueError as e:
        msg=str(e);code=404 if 'NOT_FOUND' in msg else 409
        raise HTTPException(code,detail=msg)
@router.post('/v1/trips/journeys/{journey_id}/recovery-plans')
def build(journey_id:str,b:BuildBody,p:Principal=Depends(consumer_principal)):return call(journey_recovery_service.build,p.user_id,journey_id,b.advice_id)
@router.get('/v1/trips/journeys/{journey_id}/recovery-plans/{plan_id}')
def get_plan(journey_id:str,plan_id:str,p:Principal=Depends(consumer_principal)):return call(journey_recovery_service.get,p.user_id,journey_id,plan_id)
@router.post('/v1/trips/journeys/{journey_id}/recovery-plans/{plan_id}/select')
def select(journey_id:str,plan_id:str,b:SelectBody,p:Principal=Depends(consumer_principal)):return call(journey_recovery_service.select,p.user_id,journey_id,plan_id,b.option_ids)
