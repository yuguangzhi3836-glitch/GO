from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_enterprise_risk_portfolio import recovery_enterprise_risk_portfolio_service as svc
router=APIRouter(tags=['sprint4h-enterprise-risk-portfolio'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class LimitBody(BaseModel):
    limit_key:str='prod-enterprise-residual-risk';environment:str='PROD';max_aggregate_exposure_points:float=Field(default=300,gt=0);max_team_concentration_pct:float=Field(default=60,gt=0,le=100);max_risk_domain_concentration_pct:float=Field(default=60,gt=0,le=100);max_correlated_exposure_points:float=Field(default=180,gt=0);max_active_acceptances:int=Field(default=8,gt=0)
class PositionBody(BaseModel):
    executive_risk_acceptance_id:str;team_key:str;risk_domain:str;exposure_points:float=Field(gt=0);correlation_keys:list[str]=[]
class EvidenceBody(BaseModel):evidence_reference:str
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/limits')
def create_limit(b:LimitBody,p:Principal=Depends(admin_principal)):return call(svc.create_limit,b.limit_key,b.environment,b.max_aggregate_exposure_points,b.max_team_concentration_pct,b.max_risk_domain_concentration_pct,b.max_correlated_exposure_points,b.max_active_acceptances,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/limits/{limit_id}/approve')
def approve_limit(limit_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_limit,limit_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/positions')
def position(b:PositionBody,p:Principal=Depends(admin_principal)):return call(svc.register_position,b.executive_risk_acceptance_id,b.team_key,b.risk_domain,b.exposure_points,b.correlation_keys,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/portfolio/evaluate')
def evaluate(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.evaluate,environment,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/portfolio-freeze/release')
def release(b:EvidenceBody,environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.release_freeze,environment,b.evidence_reference,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
