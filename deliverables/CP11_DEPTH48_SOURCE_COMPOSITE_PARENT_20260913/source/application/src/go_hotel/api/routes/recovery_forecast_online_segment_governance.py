from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_online_segment_governance import recovery_forecast_online_segment_governance_service as svc
router=APIRouter(tags=['sprint4t-online-segment-governance'])
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyB(BaseModel):environment:str='PROD';minimum_segment_samples:int=5;max_segment_mae:float=15;max_segment_rmse:float=20;max_segment_brier:float=.25;consecutive_breaches_required:int=2
class SegmentB(BaseModel):attribution_id:str;team_key:str;risk_domain:str
class AssessB(BaseModel):environment:str='PROD';deployment_key:str;team_key:str;risk_domain:str;horizon_hours:int=24;auto_refresh:bool=True;evidence_reference:str='segment://live'
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-segments/policies')
def policy(b:PolicyB,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.environment,b.minimum_segment_samples,b.max_segment_mae,b.max_segment_rmse,b.max_segment_brier,b.consecutive_breaches_required,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-segments/policies/{policy_id}/approve')
def approve(policy_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_policy,policy_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-segments/observations')
def observation(b:SegmentB,p:Principal=Depends(admin_principal)):return call(svc.register_attribution_segment,b.attribution_id,b.team_key,b.risk_domain)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-segments/assessments')
def assess(b:AssessB,p:Principal=Depends(admin_principal)):return call(svc.assess_segment,b.environment,b.deployment_key,b.team_key,b.risk_domain,b.horizon_hours,b.auto_refresh,b.evidence_reference)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-segments/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
