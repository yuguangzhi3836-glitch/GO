from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_runtime_identity_reissuance import recovery_runtime_identity_reissuance_service as svc
router=APIRouter(tags=['sprint3x-runtime-identity-reissuance'])
class RequestBody(BaseModel):
    predecessor_identity_id:str;replacement_identity_key:str;replacement_subject_ref:str;replacement_key_ref:str;attestation_key_ref:str;reason_code:str;evidence_reference:str;break_glass:bool=False
class AttestationBody(BaseModel):
    attestation_type:str;challenge_nonce:str;workload_measurement:str;evidence_reference:str;attestation_signature:str
class ApprovalBody(BaseModel): approval_evidence_reference:str

def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/recovery/runtime/identity-reissuance/requests')
def request(b:RequestBody,p:Principal=Depends(admin_principal)):return call(svc.request,b.predecessor_identity_id,b.replacement_identity_key,b.replacement_subject_ref,b.replacement_key_ref,b.attestation_key_ref,b.reason_code,b.evidence_reference,p.user_id,b.break_glass)
@router.get('/internal/v1/recovery/runtime/identity-reissuance/requests/{request_id}')
def get_request(request_id:str,p:Principal=Depends(admin_principal)):return call(svc.get,request_id)
@router.post('/internal/v1/recovery/runtime/identity-reissuance/requests/{request_id}/attestation')
def attestation(request_id:str,b:AttestationBody,p:Principal=Depends(admin_principal)):return call(svc.submit_attestation,request_id,b.attestation_type,b.challenge_nonce,b.workload_measurement,b.evidence_reference,b.attestation_signature,p.user_id)
@router.post('/internal/v1/recovery/runtime/identity-reissuance/requests/{request_id}/approve')
def approve(request_id:str,b:ApprovalBody,p:Principal=Depends(admin_principal)):return call(svc.approve,request_id,b.approval_evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/identity-reissuance/requests/{request_id}/issue')
def issue(request_id:str,p:Principal=Depends(admin_principal)):return call(svc.issue,request_id,p.user_id)
@router.get('/internal/v1/recovery/runtime/identity-reissuance/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
