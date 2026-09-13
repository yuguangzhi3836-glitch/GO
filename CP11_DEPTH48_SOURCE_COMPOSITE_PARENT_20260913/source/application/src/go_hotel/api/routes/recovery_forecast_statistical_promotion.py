from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_statistical_promotion import recovery_forecast_statistical_promotion_service as svc
router=APIRouter(tags=['sprint4m-statistical-model-governance'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyB(BaseModel):
    environment:str='PROD';minimum_sample_count:int=30;significance_alpha:float=.05;minimum_effect_size_pct:float=5;stability_evaluations_required:int=2;required_segments:list[str]=['ALL'];probation_seconds:int=86400;max_mae_regression_pct:float=10;max_brier_regression_pct:float=10;max_safety_regression_pct:float=5
class AssessB(BaseModel): environment:str='PROD';challenger_model_version_id:str
class PromoteB(BaseModel): environment:str='PROD';challenger_model_version_id:str;evidence:dict
class TickB(BaseModel): environment:str='PROD';evidence:dict|None=None
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-model-statistics/policies')
def create_policy(b:PolicyB,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.environment,b.minimum_sample_count,b.significance_alpha,b.minimum_effect_size_pct,b.stability_evaluations_required,b.required_segments,b.probation_seconds,b.max_mae_regression_pct,b.max_brier_regression_pct,b.max_safety_regression_pct,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-model-statistics/policies/{policy_id}/approve')
def approve(policy_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_policy,policy_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-model-statistics/assess')
def assess(b:AssessB,p:Principal=Depends(admin_principal)):return call(svc.assess,b.environment,b.challenger_model_version_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-model-statistics/promote')
def promote(b:PromoteB,p:Principal=Depends(admin_principal)):return call(svc.promote,b.environment,b.challenger_model_version_id,b.evidence)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-model-statistics/probation/tick')
def tick(b:TickB,p:Principal=Depends(admin_principal)):return call(svc.probation_tick,b.environment,b.evidence,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-model-statistics/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
