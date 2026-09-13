from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_trust_plane_chaos import recovery_trust_plane_chaos_service as svc
router=APIRouter(tags=['sprint4d-trust-plane-chaos-readiness'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyBody(BaseModel):
    policy_key:str;environment:str='PROD';required_scenarios:list[str];minimum_readiness_score:float=Field(default=90,ge=0,le=100);max_rto_seconds:int=Field(default=300,ge=0);max_rpo_seconds:int=Field(default=60,ge=0);evidence_ttl_seconds:int=Field(default=86400,ge=1)
class CampaignBody(BaseModel): environment:str='PROD';campaign_key:str;scenarios:list[dict]
class RunBody(BaseModel): evidence_prefix:str='chaos://'
class GateBody(BaseModel): evidence_reference:str
@router.post('/internal/v1/recovery/runtime/trust-plane/chaos/policies')
def policy(b:PolicyBody,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.policy_key,b.environment,b.required_scenarios,b.minimum_readiness_score,b.max_rto_seconds,b.max_rpo_seconds,b.evidence_ttl_seconds,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/chaos/campaigns')
def campaign(b:CampaignBody,p:Principal=Depends(admin_principal)):return call(svc.create_campaign,b.environment,b.campaign_key,b.scenarios,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/chaos/campaigns/{campaign_id}/run')
def run(campaign_id:str,b:RunBody,p:Principal=Depends(admin_principal)):return call(svc.run_campaign,campaign_id,p.user_id,b.evidence_prefix)
@router.post('/internal/v1/recovery/runtime/trust-plane/chaos/campaigns/{campaign_id}/assess')
def assess(campaign_id:str,p:Principal=Depends(admin_principal)):return call(svc.assess_readiness,campaign_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/{assessment_id}/gate')
def gate(assessment_id:str,b:GateBody,p:Principal=Depends(admin_principal)):return call(svc.evaluate_gate,assessment_id,b.evidence_reference,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
