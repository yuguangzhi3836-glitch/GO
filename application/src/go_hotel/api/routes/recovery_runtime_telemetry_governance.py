from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_runtime_telemetry_governance import recovery_runtime_telemetry_governance_service as svc
router=APIRouter(tags=['sprint3u-runtime-telemetry-governance'])
class SourceBody(BaseModel):
 source_key:str;source_type:str;environment:str='PROD';trust_level:str='GOVERNED';endpoint_ref:str|None=None;config:dict=Field(default_factory=dict)
class SourceStateBody(BaseModel): state:str
class IngestBody(BaseModel): telemetry_source_id:str;runtime_instance:str;metrics:dict=Field(default_factory=dict)
class PolicyBody(BaseModel):
 policy_key:str;environment:str='PROD';slo_target:float=.999;windows:list[dict]=Field(default_factory=list);min_quality_score:float=.8;min_sources:int=1

def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/recovery/runtime/telemetry/sources')
def create_source(b:SourceBody,p:Principal=Depends(admin_principal)):return call(svc.register_source,b.source_key,b.source_type,b.environment,p.user_id,b.config,b.trust_level,b.endpoint_ref)
@router.get('/internal/v1/recovery/runtime/telemetry/sources')
def sources(environment:str|None=None,p:Principal=Depends(admin_principal)):return {'data':svc.list_sources(environment)}
@router.post('/internal/v1/recovery/runtime/telemetry/sources/{source_id}/state')
def source_state(source_id:str,b:SourceStateBody,p:Principal=Depends(admin_principal)):return call(svc.set_source_state,source_id,b.state,p.user_id)
@router.post('/internal/v1/recovery/runtime/telemetry/ingest')
def ingest(b:IngestBody,p:Principal=Depends(admin_principal)):return call(svc.ingest,b.telemetry_source_id,b.runtime_instance,b.metrics,p.user_id)
@router.post('/internal/v1/recovery/runtime/slo-policies')
def policy(b:PolicyBody,p:Principal=Depends(admin_principal)):return call(svc.create_slo_policy,b.policy_key,b.environment,p.user_id,b.slo_target,b.windows or None,b.min_quality_score,b.min_sources)
@router.post('/internal/v1/recovery/runtime/safety/governed-assess')
def assess(environment:str='PROD',p:Principal=Depends(admin_principal)):
    # Sprint 3V hardening: once an automation policy exists, strong actions must pass signed trust/quorum.
    try:
        from go_hotel.db.session import SessionLocal
        from go_hotel.db.models import JourneyRecoveryIncidentAutomationPolicyRow
        from sqlalchemy import select
        with SessionLocal() as s:
            pol=s.execute(select(JourneyRecoveryIncidentAutomationPolicyRow).where(JourneyRecoveryIncidentAutomationPolicyRow.environment==environment,JourneyRecoveryIncidentAutomationPolicyRow.state=='ACTIVE')).scalars().first()
        if pol: raise HTTPException(409,detail='SIGNED_TELEMETRY_TRUST_ASSESSMENT_REQUIRED')
    except ImportError:
        pass
    return call(svc.assess,environment,p.user_id)
@router.post('/internal/v1/recovery/runtime/incidents/correlate/{safety_assessment_id}')
def correlate(safety_assessment_id:str,p:Principal=Depends(admin_principal)):return call(svc.correlate,safety_assessment_id,p.user_id)
@router.get('/internal/v1/recovery/runtime/telemetry/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
