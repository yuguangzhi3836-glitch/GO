from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_portfolio_governance import recovery_forecast_portfolio_governance_service as svc
router=APIRouter(tags=['sprint4w-multi-segment-portfolio'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class PortfolioB(BaseModel):target_ids:list[str];objectives:dict[str,str]|None=None;protected_segment_keys:list[str]|None=None
class ConflictB(BaseModel):portfolio_id:str;target_a_id:str;target_b_id:str;conflict_state:str;resolution_state:str='OPEN';conflict_penalty_pct:float=0;shared_root_cause:dict|None=None;evidence:dict|None=None
class CandidateB(BaseModel):portfolio_id:str;challenger_model_version_id:str;strategy:str='UNIFIED';covered_target_ids:list[str]|None=None
class AssessB(BaseModel):candidate_id:str;evidence:dict|None=None
class PortfolioIdB(BaseModel):portfolio_id:str;evidence:dict|None=None
class GateB(BaseModel):portfolio_id:str;candidate_id:str;evidence:dict|None=None
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation-portfolios')
def create_portfolio(b:PortfolioB,p:Principal=Depends(admin_principal)):return call(svc.create_portfolio,b.target_ids,b.objectives,b.protected_segment_keys,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation-portfolios/conflicts')
def conflict(b:ConflictB,p:Principal=Depends(admin_principal)):return call(svc.register_conflict,b.portfolio_id,b.target_a_id,b.target_b_id,b.conflict_state,b.resolution_state,b.conflict_penalty_pct,b.shared_root_cause,b.evidence,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation-portfolios/candidates')
def candidate(b:CandidateB,p:Principal=Depends(admin_principal)):return call(svc.register_candidate,b.portfolio_id,b.challenger_model_version_id,b.strategy,b.covered_target_ids,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation-portfolios/assess')
def assess(b:AssessB,p:Principal=Depends(admin_principal)):return call(svc.assess_candidate,b.candidate_id,b.evidence,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation-portfolios/arbitrate')
def arbitrate(b:PortfolioIdB,p:Principal=Depends(admin_principal)):return call(svc.arbitrate,b.portfolio_id,b.evidence,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation-portfolios/promotion-gate')
def promotion_gate(b:GateB,p:Principal=Depends(admin_principal)):return call(svc.create_promotion_gate,b.portfolio_id,b.candidate_id,b.evidence,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-remediation-portfolios/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
