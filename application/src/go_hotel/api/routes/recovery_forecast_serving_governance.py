from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_serving_governance import recovery_forecast_serving_governance_service as svc
router=APIRouter(tags=['sprint4q-model-serving-attestation'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyB(BaseModel):environment:str='PROD';require_serving_attestation:bool=True;require_runtime_fingerprint:bool=True;require_artifact_binding:bool=True
class BindB(BaseModel):environment:str='PROD';model_version_id:str;forecast_model_artifact_id:str;deployment_key:str='forecast-prod';evidence_reference:str;transition_type:str='DEPLOY'
class RuntimeB(BaseModel):environment:str='PROD';deployment_key:str='forecast-prod';runtime_instance_ref:str;model_version_id:str;forecast_model_artifact_id:str
class AttestB(BaseModel):runtime_identity_id:str;loaded_artifact_digest:str;loaded_build_hash:str;observed_runtime_fingerprint:str;evidence_reference:str
class ReleaseB(BaseModel):environment:str='PROD';deployment_key:str='forecast-prod';evidence_reference:str
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-serving/policies')
def policy(b:PolicyB,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.environment,b.require_serving_attestation,b.require_runtime_fingerprint,b.require_artifact_binding,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-serving/policies/{policy_id}/approve')
def approve(policy_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_policy,policy_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-serving/deployments')
def bind(b:BindB,p:Principal=Depends(admin_principal)):return call(svc.bind_deployment,b.environment,b.model_version_id,b.forecast_model_artifact_id,b.deployment_key,b.evidence_reference,b.transition_type,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-serving/runtime-identities')
def runtime(b:RuntimeB,p:Principal=Depends(admin_principal)):return call(svc.register_runtime_identity,b.environment,b.deployment_key,b.runtime_instance_ref,b.model_version_id,b.forecast_model_artifact_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-serving/attestations')
def attest(b:AttestB,p:Principal=Depends(admin_principal)):return call(svc.attest_serving,b.runtime_identity_id,b.loaded_artifact_digest,b.loaded_build_hash,b.observed_runtime_fingerprint,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-serving/safety/release')
def release(b:ReleaseB,p:Principal=Depends(admin_principal)):return call(svc.release_safety_control,b.environment,b.deployment_key,b.evidence_reference,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-serving/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
