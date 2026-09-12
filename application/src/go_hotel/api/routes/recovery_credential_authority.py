from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_credential_authority import recovery_credential_authority_service as svc
router=APIRouter(tags=['sprint3y-credential-authority'])
class RootBody(BaseModel): root_key:str;provider:str;trust_class:str;root_fingerprint:str;metadata:dict={};valid_until:str|None=None
class IssuerBody(BaseModel): issuer_key:str;issuer_type:str;environment:str;hardware_trust_root_id:str;verification_key_ref:str
class PolicyBody(BaseModel): policy_key:str;environment:str;identity_type:str='ANY';min_trust_class:str;allowed_attestation_types:list[str];min_verifier_quorum:int=Field(default=2,ge=1);allowed_issuer_ids:list[str];policy:dict={}
class RequestBody(BaseModel): runtime_identity_id:str;attestation_policy_id:str;credential_issuer_id:str;runtime_attestation_evidence_id:str;predecessor_credential_id:str|None=None
class VerifyBody(BaseModel): verifier_id:str;verdict:str;evidence_reference:str
class RevokeBody(BaseModel): authority_type:str;authority_id:str;environment:str;revocation_version:int=Field(ge=1);revoked_credential_ids:list[str]=[];evidence_reference:str;revoke_authority:bool=False

def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/recovery/runtime/credential-authority/trust-roots')
def create_root(b:RootBody,p:Principal=Depends(admin_principal)):
    from datetime import datetime
    vu=datetime.fromisoformat(b.valid_until.replace('Z','+00:00')) if b.valid_until else None
    return call(svc.register_trust_root,b.root_key,b.provider,b.trust_class,b.root_fingerprint,p.user_id,b.metadata,vu)
@router.post('/internal/v1/recovery/runtime/credential-authority/issuers')
def create_issuer(b:IssuerBody,p:Principal=Depends(admin_principal)):return call(svc.register_issuer,b.issuer_key,b.issuer_type,b.environment,b.hardware_trust_root_id,b.verification_key_ref,p.user_id)
@router.post('/internal/v1/recovery/runtime/credential-authority/policies')
def create_policy(b:PolicyBody,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.policy_key,b.environment,b.identity_type,b.min_trust_class,b.allowed_attestation_types,b.min_verifier_quorum,b.allowed_issuer_ids,p.user_id,b.policy)
@router.post('/internal/v1/recovery/runtime/credential-authority/issuances')
def request_issuance(b:RequestBody,p:Principal=Depends(admin_principal)):return call(svc.request_issuance,b.runtime_identity_id,b.attestation_policy_id,b.credential_issuer_id,b.runtime_attestation_evidence_id,p.user_id,b.predecessor_credential_id)
@router.post('/internal/v1/recovery/runtime/credential-authority/issuances/{issuance_id}/verify')
def verify(issuance_id:str,b:VerifyBody,p:Principal=Depends(admin_principal)):return call(svc.verify,issuance_id,b.verifier_id,b.verdict,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/credential-authority/issuances/{issuance_id}/issue')
def issue(issuance_id:str,p:Principal=Depends(admin_principal)):return call(svc.issue,issuance_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/credential-authority/revocation-sync')
def sync_revocations(b:RevokeBody,p:Principal=Depends(admin_principal)):return call(svc.sync_revocations,b.authority_type,b.authority_id,b.environment,b.revocation_version,b.revoked_credential_ids,b.evidence_reference,p.user_id,b.revoke_authority)
@router.get('/internal/v1/recovery/runtime/credential-authority/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
