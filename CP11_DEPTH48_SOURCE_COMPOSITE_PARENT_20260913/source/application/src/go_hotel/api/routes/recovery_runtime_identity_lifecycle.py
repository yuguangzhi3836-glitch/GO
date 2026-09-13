from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_runtime_identity_lifecycle import recovery_runtime_identity_lifecycle_service as svc
router=APIRouter(tags=['sprint3w-runtime-identity-lifecycle'])
class RotateBody(BaseModel): new_key_ref:str;transition_signature:str;overlap_seconds:int=300;valid_from:datetime|None=None;evidence_reference:str|None=None
class RevokeBody(BaseModel): reason_code:str;evidence_reference:str
class IncidentBody(BaseModel): severity:str;reason_code:str;evidence:dict=Field(default_factory=dict);revoke_immediately:bool=False
class ContainBody(BaseModel): evidence:dict=Field(default_factory=dict)
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/internal/v1/recovery/runtime/identity-lifecycle/identities/{identity_id}/keys')
def keys(identity_id:str,p:Principal=Depends(admin_principal)):return {'data':svc.key_versions(identity_id)}
@router.post('/internal/v1/recovery/runtime/identity-lifecycle/identities/{identity_id}/rotate-key')
def rotate(identity_id:str,b:RotateBody,p:Principal=Depends(admin_principal)):return call(svc.rotate_key,identity_id,b.new_key_ref,b.transition_signature,p.user_id,b.overlap_seconds,b.valid_from,b.evidence_reference)
@router.post('/internal/v1/recovery/runtime/identity-lifecycle/identities/{identity_id}/revoke')
def revoke(identity_id:str,b:RevokeBody,p:Principal=Depends(admin_principal)):return call(svc.revoke_identity,identity_id,b.reason_code,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/identity-lifecycle/identities/{identity_id}/security-incidents')
def incident(identity_id:str,b:IncidentBody,p:Principal=Depends(admin_principal)):return call(svc.open_security_incident,identity_id,b.severity,b.reason_code,b.evidence,p.user_id,b.revoke_immediately)
@router.post('/internal/v1/recovery/runtime/identity-lifecycle/security-incidents/{incident_id}/contain')
def contain(incident_id:str,b:ContainBody,p:Principal=Depends(admin_principal)):return call(svc.contain_incident,incident_id,b.evidence,p.user_id)
@router.post('/internal/v1/recovery/runtime/identity-lifecycle/key-overlap/retire-expired')
def retire(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.retire_expired_overlap,environment,p.user_id)
@router.get('/internal/v1/recovery/runtime/identity-lifecycle/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
