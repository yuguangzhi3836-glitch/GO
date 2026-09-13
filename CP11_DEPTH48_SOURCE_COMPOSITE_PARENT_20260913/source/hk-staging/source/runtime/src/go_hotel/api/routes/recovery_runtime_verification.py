from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_runtime_verification import recovery_runtime_verification_service as svc
router=APIRouter(tags=['sprint3s-recovery-runtime-verification'])
class AttestBody(BaseModel):
 environment:str;runtime_instance:str;observed_fingerprint:str;metadata:dict=Field(default_factory=dict)
class VerifyBody(BaseModel):
 smoke_tests:dict=Field(default_factory=dict);health_slo:dict=Field(default_factory=dict)
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/internal/v1/recovery/runtime/fingerprint')
def fingerprint(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':{'environment':environment,'expected_fingerprint':svc.expected_fingerprint(environment)}}
@router.post('/internal/v1/recovery/releases/manifests/{manifest_id}/attest')
def attest(manifest_id:str,b:AttestBody,p:Principal=Depends(admin_principal)):return call(svc.attest,manifest_id,b.environment,b.runtime_instance,b.observed_fingerprint,p.user_id,b.metadata)
@router.post('/internal/v1/recovery/runtime/attestations/{attestation_id}/verify')
def verify(attestation_id:str,b:VerifyBody,p:Principal=Depends(admin_principal)):return call(svc.verify,attestation_id,b.smoke_tests,b.health_slo,p.user_id)
@router.post('/internal/v1/recovery/runtime/verifications/{verification_id}/rollback')
def rollback(verification_id:str,p:Principal=Depends(admin_principal)):return call(svc.rollback_on_failure,verification_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/verifications/{verification_id}/seal')
def seal(verification_id:str,p:Principal=Depends(admin_principal)):return call(svc.seal,verification_id,p.user_id)
@router.get('/internal/v1/recovery/runtime/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
