from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_waiver_exposure_governance import recovery_waiver_exposure_governance_service as svc
router=APIRouter(tags=['sprint4f-waiver-exposure-exception-debt'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyBody(BaseModel):
    policy_key:str='prod-waiver-exposure';environment:str='PROD';rolling_window_hours:int=Field(default=168,gt=0);max_waiver_count:int=Field(default=3,gt=0);max_consecutive_waiver_releases:int=Field(default=2,gt=0);max_exposure_seconds:int=Field(default=21600,gt=0);max_exception_debt_points:float=Field(default=100,gt=0);remediation_sla_seconds:int=Field(default=14400,gt=0);escalation_after_seconds:int=Field(default=3600,gt=0)
class ResolveBody(BaseModel): evidence_reference:str
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/waiver-exposure/policies')
def policy(b:PolicyBody,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.policy_key,b.environment,b.rolling_window_hours,b.max_waiver_count,b.max_consecutive_waiver_releases,b.max_exposure_seconds,b.max_exception_debt_points,b.remediation_sla_seconds,b.escalation_after_seconds,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/exception-debt/evaluate')
def debt(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.evaluate_debt,environment,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/remediation/tick')
def tick(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.remediation_tick,environment,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/remediations/{remediation_id}/acknowledge')
def ack(remediation_id:str,p:Principal=Depends(admin_principal)):return call(svc.acknowledge_remediation,remediation_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/remediations/{remediation_id}/resolve')
def resolve(remediation_id:str,b:ResolveBody,p:Principal=Depends(admin_principal)):return call(svc.resolve_remediation,remediation_id,b.evidence_reference,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/waiver-exposure/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
