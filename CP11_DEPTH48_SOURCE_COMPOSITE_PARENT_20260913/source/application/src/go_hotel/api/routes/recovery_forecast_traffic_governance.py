from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_traffic_governance import recovery_forecast_traffic_governance_service as svc
router=APIRouter(tags=['sprint4r-model-traffic-governance'])
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyB(BaseModel):environment:str='PROD';champion_deployment_key:str;candidate_deployment_key:str;min_requests_per_step:int=100;max_error_rate:float=.02;max_timeout_rate:float=.01;max_p95_latency_ms:float=1000;max_shadow_divergence:float=.25
class PredictionB(BaseModel):environment:str='PROD';subject_key:str;prediction:dict;latency_ms:float;serving_status:str='OK'
class ShadowB(BaseModel):prediction_request_id:str;shadow_value:float;evidence:dict={}
class BudgetB(BaseModel):environment:str='PROD';request_count:int;error_rate:float;timeout_rate:float;p95_latency_ms:float;invalid_prediction_rate:float=0;fallback_rate:float=0;availability:float=1;attestation_mismatch_rate:float=0
class ProgressB(BaseModel):environment:str='PROD';to_percentage:int;evidence_reference:str
class RollbackB(BaseModel):environment:str='PROD';evidence_reference:str
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-traffic/policies')
def policy(b:PolicyB,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.environment,b.champion_deployment_key,b.candidate_deployment_key,b.min_requests_per_step,b.max_error_rate,b.max_timeout_rate,b.max_p95_latency_ms,b.max_shadow_divergence,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-traffic/policies/{policy_id}/approve')
def approve(policy_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_policy,policy_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-traffic/predictions')
def prediction(b:PredictionB,p:Principal=Depends(admin_principal)):return call(svc.record_prediction,b.environment,b.subject_key,b.prediction,b.latency_ms,b.serving_status)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-traffic/shadow-comparisons')
def shadow(b:ShadowB,p:Principal=Depends(admin_principal)):return call(svc.compare_shadow,b.prediction_request_id,b.shadow_value,b.evidence)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-traffic/budget-assessments')
def budget(b:BudgetB,p:Principal=Depends(admin_principal)):return call(svc.assess_budget,b.environment,b.request_count,b.error_rate,b.timeout_rate,b.p95_latency_ms,b.invalid_prediction_rate,b.fallback_rate,b.availability,b.attestation_mismatch_rate)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-traffic/canary/progress')
def progress(b:ProgressB,p:Principal=Depends(admin_principal)):return call(svc.progress_canary,b.environment,b.to_percentage,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-traffic/canary/rollback')
def rollback(b:RollbackB,p:Principal=Depends(admin_principal)):return call(svc.rollback,b.environment,b.evidence_reference,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-traffic/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
