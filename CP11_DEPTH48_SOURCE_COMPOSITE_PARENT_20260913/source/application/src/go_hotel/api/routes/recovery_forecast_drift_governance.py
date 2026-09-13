from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_drift_governance import recovery_forecast_drift_governance_service as svc
router=APIRouter(tags=['sprint4n-forecast-drift-governance'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyB(BaseModel):
    environment:str='PROD';minimum_sample_count:int=20;max_population_psi:float=.25;max_segment_psi:float=.3;max_residual_drift_pct:float=20;consecutive_breaches_required:int=2;baseline_window_key:str='BASELINE_30D';comparison_window_key:str='ROLLING_7D'
class AssessB(BaseModel):
    environment:str='PROD';horizon_hours:int=24;baseline_breach_rate:float;current_breach_rate:float;segment_baseline:dict[str,float]|None=None;segment_current:dict[str,float]|None=None
class RefreshB(BaseModel): assessment_id:str;evidence:dict
class ChallengerB(BaseModel): retraining_request_id:str;parameters:dict|None=None
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-drift/policies')
def create_policy(b:PolicyB,p:Principal=Depends(admin_principal)): return call(svc.create_policy,b.environment,b.minimum_sample_count,b.max_population_psi,b.max_segment_psi,b.max_residual_drift_pct,b.consecutive_breaches_required,b.baseline_window_key,b.comparison_window_key,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-drift/policies/{policy_id}/approve')
def approve(policy_id:str,p:Principal=Depends(admin_principal)): return call(svc.approve_policy,policy_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-drift/assess')
def assess(b:AssessB,p:Principal=Depends(admin_principal)): return call(svc.assess,b.environment,b.horizon_hours,b.baseline_breach_rate,b.current_breach_rate,b.segment_baseline,b.segment_current,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-drift/retraining-requests')
def refresh(b:RefreshB,p:Principal=Depends(admin_principal)): return call(svc.request_refresh,b.assessment_id,b.evidence,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-drift/challengers')
def challenger(b:ChallengerB,p:Principal=Depends(admin_principal)): return call(svc.generate_challenger,b.retraining_request_id,b.parameters,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-drift/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)): return {'data':svc.status(environment)}
