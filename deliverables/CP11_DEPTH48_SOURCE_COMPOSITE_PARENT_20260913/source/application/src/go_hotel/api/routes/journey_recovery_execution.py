from fastapi import APIRouter,Depends,HTTPException,Header,Request
from pydantic import BaseModel,Field
from go_hotel.security.deps import consumer_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_execution import journey_recovery_execution_service
router=APIRouter(tags=['sprint3h-recovery-orchestrator'])
class CreateBody(BaseModel):
    plan_id:str
    authorized_delta_minor:int=Field(ge=0)
    payment_method_ref:str|None=None
class ResolveBody(BaseModel):
    action:str
    authorized_delta_minor:int|None=Field(default=None,ge=0)
def call(fn,*args):
    try:return {'data':fn(*args)}
    except ValueError as e:
        msg=str(e);code=404 if 'NOT_FOUND' in msg else 409
        raise HTTPException(code,detail=msg)
@router.post('/v1/trips/journeys/{journey_id}/recovery-executions')
def create(journey_id:str,b:CreateBody,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    return call(journey_recovery_execution_service.create,p.user_id,journey_id,b.plan_id,b.authorized_delta_minor,b.payment_method_ref,idempotency_key)
@router.post('/v1/trips/journeys/{journey_id}/recovery-executions/{execution_id}/confirm')
def confirm(journey_id:str,execution_id:str,request:Request,p:Principal=Depends(consumer_principal)):
    return call(journey_recovery_execution_service.confirm,p.user_id,journey_id,execution_id,getattr(request.state,'request_id',None))
@router.get('/v1/trips/journeys/{journey_id}/recovery-executions/{execution_id}')
def get_execution(journey_id:str,execution_id:str,p:Principal=Depends(consumer_principal)):
    return call(journey_recovery_execution_service.get,p.user_id,journey_id,execution_id)
@router.post('/v1/trips/journeys/{journey_id}/recovery-executions/{execution_id}/items/{item_id}/resolve')
def resolve(journey_id:str,execution_id:str,item_id:str,b:ResolveBody,request:Request,p:Principal=Depends(consumer_principal)):
    return call(journey_recovery_execution_service.resolve,p.user_id,journey_id,execution_id,item_id,b.action,b.authorized_delta_minor,getattr(request.state,'request_id',None))
