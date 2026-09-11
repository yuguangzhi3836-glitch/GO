from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_model_promotion import recovery_forecast_model_promotion_service as svc
router=APIRouter(tags=['sprint4l-forecast-model-promotion'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class RoleBody(BaseModel):environment:str='PROD';model_version_id:str;role:str
class BacktestBody(BaseModel):environment:str='PROD';champion_model_version_id:str;challenger_model_version_id:str;window_key:str='ROLLING_30D';segments:list[str]=['ALL']
class ShadowBody(BaseModel):environment:str='PROD';challenger_model_version_id:str;horizon_hours:int;segment_key:str='ALL'
class PromoteBody(BaseModel):environment:str='PROD';challenger_model_version_id:str;evidence:dict
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-model-governance/roles')
def role(b:RoleBody,p:Principal=Depends(admin_principal)):return call(svc.assign_role,b.environment,b.model_version_id,b.role,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-model-governance/backtests')
def backtest(b:BacktestBody,p:Principal=Depends(admin_principal)):return call(svc.backtest,b.environment,b.champion_model_version_id,b.challenger_model_version_id,b.window_key,b.segments)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-model-governance/shadow')
def shadow(b:ShadowBody,p:Principal=Depends(admin_principal)):return call(svc.shadow,b.environment,b.challenger_model_version_id,b.horizon_hours,b.segment_key)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-model-governance/promote')
def promote(b:PromoteBody,p:Principal=Depends(admin_principal)):return call(svc.promote,b.environment,b.challenger_model_version_id,b.evidence)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-model-governance/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
