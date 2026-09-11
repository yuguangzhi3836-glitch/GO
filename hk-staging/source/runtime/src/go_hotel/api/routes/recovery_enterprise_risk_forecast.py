from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_enterprise_risk_forecast import recovery_enterprise_risk_forecast_service as svc
router=APIRouter(tags=['sprint4j-enterprise-risk-forecast'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyBody(BaseModel):
    policy_key:str='prod-risk-forecast';environment:str='PROD';warning_capacity_utilization_pct:float=80;restrict_capacity_utilization_pct:float=95;reserve_capacity_pct:float=10
class IndicatorBody(BaseModel):
    environment:str='PROD';indicator_key:str;indicator_type:str='KRI';dimension:str='GLOBAL';dimension_key:str|None=None;observed_value:float;threshold_value:float=1;direction:str='HIGH_BAD';weight:float=1;evidence:dict={}
class ForecastBody(BaseModel):environment:str='PROD';horizon_hours:int=24
class EvidenceBody(BaseModel):evidence_reference:str
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast/policies')
def create_policy(b:PolicyBody,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.policy_key,b.environment,b.warning_capacity_utilization_pct,b.restrict_capacity_utilization_pct,b.reserve_capacity_pct,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast/policies/{policy_id}/approve')
def approve(policy_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_policy,policy_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/indicators')
def indicator(b:IndicatorBody,p:Principal=Depends(admin_principal)):return call(svc.observe_indicator,b.environment,b.indicator_key,b.indicator_type,b.dimension,b.dimension_key,b.observed_value,b.threshold_value,b.direction,b.weight,b.evidence)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast/evaluate')
def forecast(b:ForecastBody,p:Principal=Depends(admin_principal)):return call(svc.forecast,b.environment,b.horizon_hours,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast/restriction/release')
def release(b:EvidenceBody,environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.release_restriction,environment,b.evidence_reference,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
