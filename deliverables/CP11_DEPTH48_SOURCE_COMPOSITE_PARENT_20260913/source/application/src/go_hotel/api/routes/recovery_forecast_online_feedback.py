from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from datetime import datetime
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_online_feedback import recovery_forecast_online_feedback_service as svc
router=APIRouter(tags=['sprint4s-online-prediction-feedback'])
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
class OutcomeB(BaseModel):prediction_request_id:str;actual_value:float;horizon_hours:int=24;evidence_reference:str;outcome_state:str='FINAL'
class AssessB(BaseModel):environment:str='PROD';deployment_key:str;min_samples:int=5;max_mae:float=15;max_rmse:float=20;max_brier:float=.25;auto_degrade:bool=True;evidence_reference:str='live://assessment'
class ReleaseB(BaseModel):environment:str='PROD';deployment_key:str;evidence_reference:str
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-feedback/outcomes')
def outcome(b:OutcomeB,p:Principal=Depends(admin_principal)):return call(svc.attribute_outcome,b.prediction_request_id,b.actual_value,b.horizon_hours,b.evidence_reference,None,b.outcome_state)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-feedback/assessments')
def assess(b:AssessB,p:Principal=Depends(admin_principal)):return call(svc.assess_live_performance,b.environment,b.deployment_key,b.min_samples,b.max_mae,b.max_rmse,b.max_brier,b.auto_degrade,b.evidence_reference)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-feedback/auto-degrade/release')
def release(b:ReleaseB,p:Principal=Depends(admin_principal)):return call(svc.release_degrade,b.environment,b.deployment_key,b.evidence_reference,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-feedback/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
