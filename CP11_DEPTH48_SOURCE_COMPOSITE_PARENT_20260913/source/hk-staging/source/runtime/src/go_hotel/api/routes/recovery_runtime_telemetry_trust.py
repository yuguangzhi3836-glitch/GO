from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_runtime_telemetry_trust import recovery_runtime_telemetry_trust_service as svc
router=APIRouter(tags=['sprint3v-runtime-telemetry-trust'])
class IdentityBody(BaseModel): identity_key:str;identity_type:str;environment:str='PROD';subject_ref:str;verification_key_ref:str
class IdentityStateBody(BaseModel): state:str
class PolicyBody(BaseModel):
 policy_key:str;environment:str='PROD';min_evidence_level_for_freeze:str='HIGH';min_source_quorum:int=2;max_clock_skew_seconds:int=120;envelope_freshness_seconds:int=300;allow_auto_freeze:bool=True;allow_auto_rollback_recommendation:bool=True;policy:dict=Field(default_factory=dict)
class EnvelopeBody(BaseModel): telemetry_source_id:str;workload_identity_id:str;collector_identity_id:str;runtime_instance:str;metrics:dict=Field(default_factory=dict);nonce:str;sequence_no:int;observed_at:str;signature:str

def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/recovery/runtime/trust/identities')
def identity(b:IdentityBody,p:Principal=Depends(admin_principal)):return call(svc.register_identity,b.identity_key,b.identity_type,b.environment,b.subject_ref,b.verification_key_ref,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust/identities/{identity_id}/state')
def identity_state(identity_id:str,b:IdentityStateBody,p:Principal=Depends(admin_principal)):return call(svc.set_identity_state,identity_id,b.state,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust/automation-policies')
def policy(b:PolicyBody,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.policy_key,b.environment,p.user_id,b.min_evidence_level_for_freeze,b.min_source_quorum,b.max_clock_skew_seconds,b.envelope_freshness_seconds,b.allow_auto_freeze,b.allow_auto_rollback_recommendation,b.policy)
@router.post('/internal/v1/recovery/runtime/trust/telemetry-ingest')
def signed_ingest(b:EnvelopeBody,p:Principal=Depends(admin_principal)):return call(svc.ingest_signed,b.telemetry_source_id,b.workload_identity_id,b.collector_identity_id,b.runtime_instance,b.metrics,b.nonce,b.sequence_no,b.observed_at,b.signature,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust/assess')
def trust_assess(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.assess_trust,environment)
@router.post('/internal/v1/recovery/runtime/trust/governed-safety-assess')
def governed(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.governed_assess,environment,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
