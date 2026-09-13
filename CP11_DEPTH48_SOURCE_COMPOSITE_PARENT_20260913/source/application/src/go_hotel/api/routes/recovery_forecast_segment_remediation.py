from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_segment_remediation import recovery_forecast_segment_remediation_service as svc
router=APIRouter(tags=['sprint4u-segment-remediation'])
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyB(BaseModel):environment:str='PROD';minimum_target_improvement_pct:float=15;max_cross_segment_regression_pct:float=10;minimum_validation_samples:int=3
class TargetB(BaseModel):retraining_request_id:str
class ValidateB(BaseModel):target_id:str;challenger_model_version_id:str;sample_count:int;challenger_mae:float
class CrossB(BaseModel):target_id:str;challenger_model_version_id:str;segment_key:str;baseline_mae:float;challenger_mae:float
class AssessB(BaseModel):target_id:str;challenger_model_version_id:str;evidence:dict|None=None
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation/policies')
def policy(b:PolicyB,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.environment,b.minimum_target_improvement_pct,b.max_cross_segment_regression_pct,b.minimum_validation_samples,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation/policies/{policy_id}/approve')
def approve(policy_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_policy,policy_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation/targets')
def target(b:TargetB,p:Principal=Depends(admin_principal)):return call(svc.create_target,b.retraining_request_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation/validate-target')
def validate(b:ValidateB,p:Principal=Depends(admin_principal)):return call(svc.validate_target,b.target_id,b.challenger_model_version_id,b.sample_count,b.challenger_mae,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation/cross-segment')
def cross(b:CrossB,p:Principal=Depends(admin_principal)):return call(svc.register_cross_segment,b.target_id,b.challenger_model_version_id,b.segment_key,b.baseline_mae,b.challenger_mae)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation/assess')
def assess(b:AssessB,p:Principal=Depends(admin_principal)):return call(svc.assess,b.target_id,b.challenger_model_version_id,b.evidence,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
