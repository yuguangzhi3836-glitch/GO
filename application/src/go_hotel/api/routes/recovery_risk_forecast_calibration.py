from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_risk_forecast_calibration import recovery_risk_forecast_calibration_service as svc
router=APIRouter(tags=['sprint4k-risk-forecast-calibration'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class ModelBody(BaseModel):
    model_key:str='enterprise-risk-forecast';environment:str='PROD';algorithm_key:str='DETERMINISTIC_WEIGHTED_SIGNAL_V1';parameters:dict={'growth_multiplier':1.0};conservative_parameters:dict={'growth_multiplier':1.5,'minimum_growth':0.08};minimum_samples:int=5;max_mae_points:float=40;max_brier_score:float=0.30;max_false_positive_rate:float=0.50;max_false_negative_rate:float=0.30;max_capacity_drift_pct:float=30
class OutcomeBody(BaseModel):
    risk_forecast_id:str;actual_exposure_points:float;evidence:dict
class AssessBody(BaseModel):environment:str='PROD';horizon_hours:int=24
class EvidenceBody(BaseModel):evidence_reference:str
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-calibration/models')
def model(b:ModelBody,p:Principal=Depends(admin_principal)):return call(svc.create_model,b.model_key,b.environment,b.algorithm_key,b.parameters,b.conservative_parameters,b.minimum_samples,b.max_mae_points,b.max_brier_score,b.max_false_positive_rate,b.max_false_negative_rate,b.max_capacity_drift_pct,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-calibration/models/{model_id}/approve')
def approve(model_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_model,model_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-calibration/outcomes')
def outcome(b:OutcomeBody,p:Principal=Depends(admin_principal)):return call(svc.record_outcome,b.risk_forecast_id,b.actual_exposure_points,b.evidence)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-calibration/assess')
def assess(b:AssessBody,p:Principal=Depends(admin_principal)):return call(svc.assess,b.environment,b.horizon_hours,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-calibration/conservative-baseline/release')
def release(b:EvidenceBody,environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.release_conservative,environment,b.evidence_reference,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-calibration/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
