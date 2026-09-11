from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_trust_plane_dr import recovery_trust_plane_dr_service as svc
router=APIRouter(tags=['sprint4c-trust-plane-dr'])

def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))

class OperatorBody(BaseModel): operator_key:str;organization_ref:str;control_domain:str;cloud_provider:str;key_authority:str
class BindingBody(BaseModel): witness_id:str;operator_id:str;region_key:str;failure_domain:str;cloud_provider:str;key_authority:str;evidence_reference:str
class IndependencePolicyBody(BaseModel): policy_key:str;environment:str='PROD';minimum_operator_quorum:int=Field(ge=1);minimum_failure_domains:int=Field(ge=1);minimum_cloud_providers:int=Field(ge=1);minimum_key_authorities:int=Field(ge=1);max_witnesses_per_operator:int=Field(default=1,ge=1)
class CrossGossipBody(BaseModel): operator_id:str;checkpoint_id:str;region_key:str;evidence_reference:str
class DetectBody(BaseModel): environment:str='PROD';tree_size:int=Field(ge=1);evidence_reference:str
class ArchiveBody(BaseModel): storage_reference:str
class DisasterBody(BaseModel): environment:str='PROD';failure_scope:str;failure_domain_key:str;affected_regions:list[str];evidence_reference:str;drill_mode:bool=False
class RebuildBody(BaseModel): archive_id:str;target_region_key:str;witness_federation_id:str;evidence_reference:str
class EvidenceBody(BaseModel): evidence_reference:str
class DrillBody(BaseModel): rebuild_id:str;evidence_reference:str

@router.post('/internal/v1/recovery/runtime/trust-plane/operators')
def operator(b:OperatorBody,p:Principal=Depends(admin_principal)):return call(svc.register_operator,b.operator_key,b.organization_ref,b.control_domain,b.cloud_provider,b.key_authority,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/witness-bindings')
def binding(b:BindingBody,p:Principal=Depends(admin_principal)):return call(svc.bind_witness,b.witness_id,b.operator_id,b.region_key,b.failure_domain,b.cloud_provider,b.key_authority,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/independence-policies')
def policy(b:IndependencePolicyBody,p:Principal=Depends(admin_principal)):return call(svc.create_independence_policy,b.policy_key,b.environment,b.minimum_operator_quorum,b.minimum_failure_domains,b.minimum_cloud_providers,b.minimum_key_authorities,b.max_witnesses_per_operator,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/federations/{federation_id}/assess')
def assess(federation_id:str,p:Principal=Depends(admin_principal)):return call(svc.assess_federation,federation_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/cross-operator-gossip')
def cross_gossip(b:CrossGossipBody,p:Principal=Depends(admin_principal)):return call(svc.publish_cross_operator_gossip,b.operator_id,b.checkpoint_id,b.region_key,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/cross-operator-gossip/detect')
def detect(b:DetectBody,p:Principal=Depends(admin_principal)):return call(svc.detect_cross_operator_split_view,b.environment,b.tree_size,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/checkpoints/{checkpoint_id}/archive')
def archive(checkpoint_id:str,b:ArchiveBody,p:Principal=Depends(admin_principal)):return call(svc.archive_checkpoint,checkpoint_id,b.storage_reference,p.user_id)
@router.get('/v1/trust/transparency/archive/{archive_id}/verify')
def public_archive(archive_id:str):return {'data':svc.verify_archive(archive_id)}
@router.post('/internal/v1/recovery/runtime/trust-plane/disasters')
def disaster(b:DisasterBody,p:Principal=Depends(admin_principal)):return call(svc.open_disaster,b.environment,b.failure_scope,b.failure_domain_key,b.affected_regions,b.evidence_reference,p.user_id,b.drill_mode)
@router.post('/internal/v1/recovery/runtime/trust-plane/disasters/{incident_id}/rebuild')
def rebuild(incident_id:str,b:RebuildBody,p:Principal=Depends(admin_principal)):return call(svc.rebuild_from_archive,incident_id,b.archive_id,b.target_region_key,b.witness_federation_id,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/disasters/{incident_id}/complete')
def complete(incident_id:str,b:EvidenceBody,p:Principal=Depends(admin_principal)):return call(svc.complete_disaster_recovery,incident_id,p.user_id,b.evidence_reference)
@router.post('/internal/v1/recovery/runtime/trust-plane/disasters/{incident_id}/drills')
def drill(incident_id:str,b:DrillBody,p:Principal=Depends(admin_principal)):return call(svc.record_recovery_drill,incident_id,b.rebuild_id,b.evidence_reference,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
