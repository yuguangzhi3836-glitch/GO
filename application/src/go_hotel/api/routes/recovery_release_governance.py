from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_release_governance import recovery_release_governance_service as svc
router=APIRouter(tags=['sprint3r-recovery-release-governance'])
class ConfigBody(BaseModel):
    config_key:str;config_type:str='GENERIC';scope_type:str='GLOBAL';scope_key:str='*';payload:dict=Field(default_factory=dict);source_ref_kind:str|None=None;source_ref_id:str|None=None
class ManifestBody(BaseModel):
    source_environment:str;target_environment:str;config_version_ids:list[str];rollback_target_manifest_id:str|None=None
class EvidenceBody(BaseModel): evidence_reference:str;summary:str=''
class DriftBody(BaseModel): environment:str;observed_bindings:dict=Field(default_factory=dict)
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/recovery/releases/config-versions')
def create_config(b:ConfigBody,p:Principal=Depends(admin_principal)):return call(svc.create_config_version,b.config_key,b.config_type,b.scope_type,b.scope_key,p.user_id,b.payload,b.source_ref_kind,b.source_ref_id)
@router.get('/internal/v1/recovery/releases/config-versions')
def configs(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.configs()}}
@router.get('/internal/v1/recovery/releases/environment-bindings')
def bindings(environment:str|None=None,p:Principal=Depends(admin_principal)):return {'data':{'items':svc.bindings(environment)}}
@router.post('/internal/v1/recovery/releases/manifests')
def create_manifest(b:ManifestBody,p:Principal=Depends(admin_principal)):return call(svc.create_manifest,b.source_environment,b.target_environment,b.config_version_ids,p.user_id,b.rollback_target_manifest_id)
@router.get('/internal/v1/recovery/releases/manifests')
def manifests(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.manifests()}}
@router.get('/internal/v1/recovery/releases/manifests/{manifest_id}')
def manifest(manifest_id:str,p:Principal=Depends(admin_principal)):return call(svc.manifest,manifest_id)
@router.post('/internal/v1/recovery/releases/manifests/{manifest_id}/dry-run')
def dry_run(manifest_id:str,p:Principal=Depends(admin_principal)):return call(svc.dry_run,manifest_id,p.user_id)
@router.post('/internal/v1/recovery/releases/manifests/{manifest_id}/staging-evidence')
def evidence(manifest_id:str,b:EvidenceBody,p:Principal=Depends(admin_principal)):return call(svc.attach_staging_evidence,manifest_id,b.evidence_reference,b.summary,p.user_id)
@router.post('/internal/v1/recovery/releases/manifests/{manifest_id}/approve')
def approve(manifest_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve,manifest_id,p.user_id)
@router.post('/internal/v1/recovery/releases/manifests/{manifest_id}/promote')
def promote(manifest_id:str,p:Principal=Depends(admin_principal)):return call(svc.promote,manifest_id,p.user_id)
@router.post('/internal/v1/recovery/releases/manifests/{manifest_id}/rollback')
def rollback(manifest_id:str,p:Principal=Depends(admin_principal)):return call(svc.rollback,manifest_id,p.user_id)
@router.post('/internal/v1/recovery/releases/drift/check')
def drift(b:DriftBody,p:Principal=Depends(admin_principal)):return call(svc.check_drift,b.environment,b.observed_bindings,p.user_id)
@router.get('/internal/v1/recovery/releases/drift')
def drift_list(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.drift_assessments()}}
