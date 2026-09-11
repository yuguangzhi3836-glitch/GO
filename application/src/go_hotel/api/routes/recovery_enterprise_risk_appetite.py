from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_enterprise_risk_appetite import recovery_enterprise_risk_appetite_service as svc
router=APIRouter(tags=['sprint4i-enterprise-risk-appetite'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class AppetiteBody(BaseModel):
    appetite_key:str='prod-risk-appetite';environment:str='PROD';max_current_exposure_points:float=Field(default=300,gt=0);max_stressed_exposure_points:float=Field(default=450,gt=0);min_headroom_points:float=Field(default=90,gt=0);min_capacity_buffer_pct:float=Field(default=20,gt=0,le=100);max_sensitivity_pct:float=Field(default=120,gt=0)
class ScenarioBody(BaseModel):
    environment:str='PROD';scenario_key:str;scenario_type:str;shock_multiplier:float=Field(default=1.5,ge=1);correlation_amplifier:float=Field(default=1,ge=1);affected_correlation_keys:list[str]=[];affected_risk_domains:list[str]=[]
class EvalBody(BaseModel):environment:str='PROD';scenario_ids:list[str]
class EvidenceBody(BaseModel):evidence_reference:str
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/appetite')
def create(b:AppetiteBody,p:Principal=Depends(admin_principal)):return call(svc.create_appetite,b.appetite_key,b.environment,b.max_current_exposure_points,b.max_stressed_exposure_points,b.min_headroom_points,b.min_capacity_buffer_pct,b.max_sensitivity_pct,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/appetite/{appetite_id}/approve')
def approve(appetite_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_appetite,appetite_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/stress-scenarios')
def scenario(b:ScenarioBody,p:Principal=Depends(admin_principal)):return call(svc.create_scenario,b.environment,b.scenario_key,b.scenario_type,b.shock_multiplier,b.correlation_amplifier,b.affected_correlation_keys,b.affected_risk_domains,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/stress/evaluate')
def evaluate(b:EvalBody,p:Principal=Depends(admin_principal)):return call(svc.evaluate,b.environment,b.scenario_ids,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/stress-freeze/release')
def release(b:EvidenceBody,environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.release_freeze,environment,b.evidence_reference,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/appetite/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
