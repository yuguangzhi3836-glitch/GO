from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_transparency_gossip import recovery_transparency_gossip_service as svc
router=APIRouter(tags=['sprint4b-transparency-gossip'])
class GossipBody(BaseModel): environment:str='PROD';observer_key:str;region_key:str;tree_size:int=Field(ge=1);root_hash:str;checkpoint_hash:str;evidence_reference:str
class FederationBody(BaseModel): federation_key:str;environment:str='PROD';witness_ids:list[str];minimum_quorum:int=Field(ge=1)
class DetectBody(BaseModel): environment:str='PROD';tree_size:int=Field(ge=1);evidence_reference:str
class RecoveryBody(BaseModel): region_key:str;target_checkpoint_id:str;consistency_proof_id:str;witness_federation_id:str;evidence_reference:str
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/recovery/runtime/trust-gossip/observations')
def gossip(b:GossipBody,p:Principal=Depends(admin_principal)):return call(svc.publish_gossip,b.environment,b.observer_key,b.region_key,b.tree_size,b.root_hash,b.checkpoint_hash,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-gossip/witness-federations')
def federation(b:FederationBody,p:Principal=Depends(admin_principal)):return call(svc.create_witness_federation,b.federation_key,b.environment,b.witness_ids,b.minimum_quorum,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-gossip/consistency-proofs')
def proof(old_checkpoint_id:str,new_checkpoint_id:str,p:Principal=Depends(admin_principal)):return call(svc.create_consistency_proof,old_checkpoint_id,new_checkpoint_id,p.user_id)
@router.get('/v1/trust/transparency/consistency/{proof_id}')
def public_proof(proof_id:str):return {'data':svc.verify_consistency_proof(proof_id)}
@router.post('/internal/v1/recovery/runtime/trust-gossip/split-view/detect')
def detect(b:DetectBody,p:Principal=Depends(admin_principal)):return call(svc.detect_split_view,b.environment,b.tree_size,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-gossip/incidents/{incident_id}/recover')
def recover(incident_id:str,b:RecoveryBody,p:Principal=Depends(admin_principal)):return call(svc.request_recovery,incident_id,b.region_key,b.target_checkpoint_id,b.consistency_proof_id,b.witness_federation_id,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-gossip/recoveries/{recovery_id}/rejoin')
def rejoin(recovery_id:str,p:Principal=Depends(admin_principal)):return call(svc.rejoin_region,recovery_id,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-gossip/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
