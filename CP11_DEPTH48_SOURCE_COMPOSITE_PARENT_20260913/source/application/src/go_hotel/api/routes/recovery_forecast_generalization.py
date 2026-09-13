from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_generalization import recovery_forecast_generalization_service as svc
router=APIRouter(tags=['sprint4v-remediation-generalization'])
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyB(BaseModel):environment:str='PROD';minimum_adjacent_samples:int=3;max_adjacent_regression_pct:float=10;max_holdout_regression_pct:float=8;minimum_target_sustain_improvement_pct:float=10
class ValidationB(BaseModel):target_id:str;challenger_model_version_id:str;segment_key:str;sample_count:int;baseline_mae:float;challenger_mae:float
class ProofB(BaseModel):target_id:str;promoted_model_version_id:str;target_live_improvement_pct:float;max_adjacent_regression_pct:float;max_holdout_regression_pct:float;global_performance_state:str='PASS';evidence:dict|None=None
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-generalization/policies')
def policy(b:PolicyB,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.environment,b.minimum_adjacent_samples,b.max_adjacent_regression_pct,b.max_holdout_regression_pct,b.minimum_target_sustain_improvement_pct,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-generalization/policies/{policy_id}/approve')
def approve(policy_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_policy,policy_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-generalization/adjacent')
def adjacent(b:ValidationB,p:Principal=Depends(admin_principal)):return call(svc.validate_adjacent,b.target_id,b.challenger_model_version_id,b.segment_key,b.sample_count,b.baseline_mae,b.challenger_mae,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-generalization/holdout')
def holdout(b:ValidationB,p:Principal=Depends(admin_principal)):return call(svc.validate_holdout,b.target_id,b.challenger_model_version_id,b.segment_key,b.sample_count,b.baseline_mae,b.challenger_mae,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-generalization/post-promotion-proof')
def proof(b:ProofB,p:Principal=Depends(admin_principal)):return call(svc.post_promotion_proof,b.target_id,b.promoted_model_version_id,b.target_live_improvement_pct,b.max_adjacent_regression_pct,b.max_holdout_regression_pct,b.global_performance_state,b.evidence,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-generalization/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
