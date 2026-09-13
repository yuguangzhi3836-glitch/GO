from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_artifact_governance import recovery_forecast_artifact_governance_service as svc
router=APIRouter(tags=['sprint4p-forecast-artifact-governance'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyB(BaseModel):
    environment:str='PROD';require_sbom:bool=True;require_signed_attestation:bool=True;require_promotion_binding:bool=True;allowed_package_formats:list[str]=['ONNX','PICKLE','JOBLIB','TORCHSCRIPT','MODEL_BUNDLE'];allowed_builder_key_refs:list[str]=['builder://engineering']
class ArtifactB(BaseModel):
    environment:str='PROD';challenger_model_version_id:str;training_manifest_id:str;package_ref:str;package_format:str='MODEL_BUNDLE';artifact_digest:str;artifact_size_bytes:int;registry_namespace:str='go-forecast-models'
class SbomB(BaseModel): artifact_id:str;sbom_format:str='SPDX-LITE';components:list[dict];provenance:dict={}
class AttestB(BaseModel): artifact_id:str;builder_identity:str;signing_key_ref:str;signature:str;evidence_reference:str
class IntegrityB(BaseModel): artifact_id:str;observed_artifact_digest:str;observed_build_hash:str;evidence_reference:str
class BindB(BaseModel): artifact_id:str
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-artifacts/policies')
def create_policy(b:PolicyB,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.environment,b.require_sbom,b.require_signed_attestation,b.require_promotion_binding,b.allowed_package_formats,b.allowed_builder_key_refs,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-artifacts/policies/{policy_id}/approve')
def approve(policy_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_policy,policy_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-artifacts/registry')
def register(b:ArtifactB,p:Principal=Depends(admin_principal)):return call(svc.register_artifact,b.environment,b.challenger_model_version_id,b.training_manifest_id,b.package_ref,b.package_format,b.artifact_digest,b.artifact_size_bytes,b.registry_namespace,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-artifacts/sbom')
def sbom(b:SbomB,p:Principal=Depends(admin_principal)):return call(svc.attach_sbom,b.artifact_id,b.sbom_format,b.components,b.provenance,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-artifacts/attestations')
def attest(b:AttestB,p:Principal=Depends(admin_principal)):return call(svc.attest_build,b.artifact_id,b.builder_identity,b.signing_key_ref,b.signature,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-artifacts/integrity')
def integrity(b:IntegrityB,p:Principal=Depends(admin_principal)):return call(svc.assess_integrity,b.artifact_id,b.observed_artifact_digest,b.observed_build_hash,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-artifacts/promotion-bindings')
def bind(b:BindB,p:Principal=Depends(admin_principal)):return call(svc.bind_for_promotion,b.artifact_id,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-artifacts/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
