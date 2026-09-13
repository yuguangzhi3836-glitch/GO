from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_exception_debt_burndown import recovery_exception_debt_burndown_service as svc
router=APIRouter(tags=['sprint4g-exception-debt-burndown'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyBody(BaseModel):
    policy_key:str='prod-exception-debt-burndown';environment:str='PROD';freeze_trigger_debt_points:float=Field(default=100,gt=0);release_threshold_debt_points:float=Field(default=35,ge=0);max_debt_age_seconds:int=Field(default=86400,gt=0);plan_due_seconds:int=Field(default=604800,gt=0);milestone_overdue_escalation_seconds:int=Field(default=14400,gt=0);executive_acceptance_max_seconds:int=Field(default=604800,gt=0)
class PlanBody(BaseModel):
    environment:str='PROD';plan_owner:str;executive_sponsor:str;objective:str;target_debt_points:float=Field(ge=0);milestones:list[dict];responsibilities:list[dict]=[]
class EvidenceBody(BaseModel): evidence_reference:str
class AcceptanceBody(BaseModel):
    residual_risk_summary:str;evidence_reference:str;starts_at:datetime;expires_at:datetime
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/exception-debt/burn-down/policies')
def policy(b:PolicyBody,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.policy_key,b.environment,b.freeze_trigger_debt_points,b.release_threshold_debt_points,b.max_debt_age_seconds,b.plan_due_seconds,b.milestone_overdue_escalation_seconds,b.executive_acceptance_max_seconds,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/exception-debt/aging/evaluate')
def aging(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.evaluate_aging,environment,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/exception-debt/burn-down/plans')
def plan(b:PlanBody,p:Principal=Depends(admin_principal)):return call(svc.create_plan,b.environment,b.plan_owner,b.executive_sponsor,b.objective,b.target_debt_points,b.milestones,b.responsibilities,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/exception-debt/burn-down/milestones/{milestone_id}/complete')
def complete(milestone_id:str,b:EvidenceBody,p:Principal=Depends(admin_principal)):return call(svc.complete_milestone,milestone_id,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/exception-debt/governance/tick')
def tick(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.governance_tick,environment,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/exception-debt/burn-down/plans/{plan_id}/executive-risk-acceptance')
def request_acceptance(plan_id:str,b:AcceptanceBody,p:Principal=Depends(admin_principal)):return call(svc.request_executive_acceptance,plan_id,b.residual_risk_summary,b.evidence_reference,b.starts_at,b.expires_at,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/exception-debt/executive-risk-acceptances/{acceptance_id}/approve')
def approve_acceptance(acceptance_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_executive_acceptance,acceptance_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/waiver-freeze/release')
def release_freeze(b:EvidenceBody,environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.release_freeze,environment,b.evidence_reference,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/exception-debt/burn-down/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
