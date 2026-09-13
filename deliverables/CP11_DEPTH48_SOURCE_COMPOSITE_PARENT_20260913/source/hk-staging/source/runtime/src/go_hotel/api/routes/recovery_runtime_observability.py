from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_runtime_observability import recovery_runtime_observability_service as svc
router=APIRouter(tags=['sprint3t-recovery-runtime-observability'])
class ObservationBody(BaseModel):
 environment:str='PROD';runtime_instance:str;metrics:dict=Field(default_factory=dict)
class UnfreezeBody(BaseModel): evidence_reference:str

def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/recovery/runtime/observations')
def ingest(b:ObservationBody,p:Principal=Depends(admin_principal)):return call(svc.ingest,b.environment,b.runtime_instance,b.metrics,p.user_id)
@router.post('/internal/v1/recovery/runtime/safety/assess')
def assess(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.assess,environment,p.user_id)
@router.get('/internal/v1/recovery/runtime/safety/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
@router.post('/internal/v1/recovery/runtime/safety/unfreeze')
def unfreeze(b:UnfreezeBody,environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.unfreeze,environment,p.user_id,b.evidence_reference)
@router.post('/internal/v1/recovery/runtime/rollback-recommendations/{recommendation_id}/acknowledge')
def acknowledge(recommendation_id:str,p:Principal=Depends(admin_principal)):return call(svc.acknowledge_recommendation,recommendation_id,p.user_id)
