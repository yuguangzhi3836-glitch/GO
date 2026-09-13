from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_federated_trust import recovery_federated_trust_service as svc
router=APIRouter(tags=['sprint3z-federated-trust'])
class FederationBody(BaseModel): federation_key:str;environment:str;cluster_scope:str='*';hardware_trust_root_id:str;peer_fingerprint:str;policy_version:int=Field(default=1,ge=1)
class StatusBody(BaseModel): status:str;evidence_reference:str;ttl_seconds:int=Field(default=300,ge=30)
class PolicyBody(BaseModel): policy_key:str;environment:str;cluster_scope:str='*';min_status_freshness_seconds:int=Field(default=300,ge=30);allowed_federation_ids:list[str];require_transparency_log:bool=True;policy:dict={}
class AdmissionBody(BaseModel): runtime_identity_id:str;environment:str;cluster_id:str='default'
class CompromiseBody(BaseModel): credential_issuer_id:str;severity:str;evidence_reference:str;ttl_seconds:int=Field(default=300,ge=30)
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/recovery/runtime/federated-trust/federations')
def federation(b:FederationBody,p:Principal=Depends(admin_principal)):return call(svc.register_federation,b.federation_key,b.environment,b.cluster_scope,b.hardware_trust_root_id,b.peer_fingerprint,b.policy_version,p.user_id)
@router.post('/internal/v1/recovery/runtime/federated-trust/credentials/{credential_id}/status')
def publish_status(credential_id:str,b:StatusBody,p:Principal=Depends(admin_principal)):return call(svc.publish_credential_status,credential_id,b.status,b.evidence_reference,p.user_id,b.ttl_seconds)
@router.post('/internal/v1/recovery/runtime/federated-trust/admission-policies')
def policy(b:PolicyBody,p:Principal=Depends(admin_principal)):return call(svc.create_admission_policy,b.policy_key,b.environment,b.cluster_scope,b.min_status_freshness_seconds,b.allowed_federation_ids,b.require_transparency_log,p.user_id,b.policy)
@router.post('/internal/v1/recovery/runtime/federated-trust/admission/evaluate')
def evaluate(b:AdmissionBody,p:Principal=Depends(admin_principal)):return call(svc.evaluate_admission,b.runtime_identity_id,b.environment,b.cluster_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/federated-trust/issuer-compromise')
def compromise(b:CompromiseBody,p:Principal=Depends(admin_principal)):return call(svc.report_issuer_compromise,b.credential_issuer_id,b.severity,b.evidence_reference,p.user_id,b.ttl_seconds)
@router.get('/internal/v1/recovery/runtime/federated-trust/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
@router.get('/v1/trust/credentials/{credential_id}/status')
def public_credential_status(credential_id:str):return {'data':svc.public_credential_status(credential_id)}
@router.get('/v1/trust/transparency/checkpoint')
def transparency_checkpoint():return {'data':svc.transparency_checkpoint()}
