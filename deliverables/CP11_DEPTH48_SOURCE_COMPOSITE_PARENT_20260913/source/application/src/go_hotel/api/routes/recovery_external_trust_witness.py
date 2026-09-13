from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_external_trust_witness import recovery_external_trust_witness_service as svc
router=APIRouter(tags=['sprint4a-external-trust'])
class WitnessBody(BaseModel): witness_key:str;environment:str;verification_key_ref:str;witness_fingerprint:str
class CosignBody(BaseModel): witness_id:str;signature:str;evidence_reference:str
class ReplicaBody(BaseModel): environment:str;region_key:str;credential_id:str;checkpoint_id:str;evidence_reference:str;ttl_seconds:int=Field(default=300,ge=30);status_override:str|None=None
class PolicyBody(BaseModel): policy_key:str;environment:str;required_regions:list[str];minimum_witness_cosignatures:int=Field(default=1,ge=1);max_replica_age_seconds:int=Field(default=300,ge=30)
class ConsensusBody(BaseModel): runtime_identity_id:str;credential_id:str;environment:str;cluster_id:str='default'
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/recovery/runtime/external-trust/checkpoints')
def checkpoint(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.create_checkpoint,environment,p.user_id)
@router.get('/v1/trust/transparency/merkle/checkpoint')
def public_checkpoint(environment:str='PROD'):return {'data':svc.public_checkpoint(environment)}
@router.get('/v1/trust/transparency/merkle/proof/{sequence_no}')
def proof(sequence_no:int,checkpoint_id:str|None=None):return call(svc.inclusion_proof,sequence_no,checkpoint_id)
@router.post('/internal/v1/recovery/runtime/external-trust/witnesses')
def witness(b:WitnessBody,p:Principal=Depends(admin_principal)):return call(svc.register_witness,b.witness_key,b.environment,b.verification_key_ref,b.witness_fingerprint,p.user_id)
@router.post('/internal/v1/recovery/runtime/external-trust/checkpoints/{checkpoint_id}/cosign')
def cosign(checkpoint_id:str,b:CosignBody,p:Principal=Depends(admin_principal)):return call(svc.cosign_checkpoint,checkpoint_id,b.witness_id,b.signature,b.evidence_reference)
@router.post('/internal/v1/recovery/runtime/external-trust/region-replicas')
def replica(b:ReplicaBody,p:Principal=Depends(admin_principal)):return call(svc.publish_region_replica,b.environment,b.region_key,b.credential_id,b.checkpoint_id,b.evidence_reference,p.user_id,b.ttl_seconds,b.status_override)
@router.post('/internal/v1/recovery/runtime/external-trust/admission-policies')
def policy(b:PolicyBody,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.policy_key,b.environment,b.required_regions,b.minimum_witness_cosignatures,b.max_replica_age_seconds,p.user_id)
@router.post('/internal/v1/recovery/runtime/external-trust/admission/evaluate')
def consensus(b:ConsensusBody,p:Principal=Depends(admin_principal)):return call(svc.evaluate_consensus,b.runtime_identity_id,b.credential_id,b.environment,b.cluster_id,p.user_id)

@router.get('/internal/v1/recovery/runtime/external-trust/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
