from datetime import datetime, timezone, timedelta
from uuid import uuid4
import hashlib, hmac, json, os
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryTrustTransparencyLogRow, JourneyRecoveryCredentialStatusDistributionRow,
    JourneyRecoveryFederatedAdmissionDecisionRow,
    JourneyRecoveryMerkleCheckpointRow, JourneyRecoveryExternalTrustWitnessRow,
    JourneyRecoveryWitnessCosignatureRow, JourneyRecoveryRegionTrustReplicaRow,
    JourneyRecoveryMultiRegionAdmissionPolicyRow, JourneyRecoveryMultiRegionAdmissionDecisionRow,
    JourneyRecoveryRegionIsolationRow, JourneyRecoveryTrustPlaneDisasterIncidentRow,
)
from go_hotel.journey.recovery_federated_trust import recovery_federated_trust_service as ft

def now(): return datetime.now(timezone.utc)
def aware(v): return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def sha_text(v): return hashlib.sha256(v.encode()).hexdigest()
def sha(v): return sha_text(canon(v))
def witness_env_key(ref): return 'GO_TRUST_WITNESS_KEY_'+''.join(c if c.isalnum() else '_' for c in ref.upper())

def _pair(a,b): return sha_text(a+b)
def merkle_root(leaves):
    if not leaves: return sha_text('')
    level=list(leaves)
    while len(level)>1:
        if len(level)%2: level.append(level[-1])
        level=[_pair(level[i],level[i+1]) for i in range(0,len(level),2)]
    return level[0]
def merkle_proof(leaves,index):
    proof=[];level=list(leaves);idx=index
    while len(level)>1:
        if len(level)%2: level.append(level[-1])
        sib=idx-1 if idx%2 else idx+1
        proof.append({'hash':level[sib],'position':'LEFT' if sib<idx else 'RIGHT'})
        idx//=2;level=[_pair(level[i],level[i+1]) for i in range(0,len(level),2)]
    return proof
def verify_proof(leaf,proof,root):
    h=leaf
    for p in proof:
        h=_pair(p['hash'],h) if p['position']=='LEFT' else _pair(h,p['hash'])
    return h==root

class RecoveryExternalTrustWitnessService:
    def create_checkpoint(self,environment,actor):
        with SessionLocal() as s:
            rows=s.execute(select(JourneyRecoveryTrustTransparencyLogRow).where(JourneyRecoveryTrustTransparencyLogRow.environment==environment).order_by(JourneyRecoveryTrustTransparencyLogRow.sequence_no.asc())).scalars().all()
            if not rows: raise ValueError('TRANSPARENCY_LOG_EMPTY')
            leaves=[r.entry_hash for r in rows]; root=merkle_root(leaves)
            payload={'environment':environment,'tree_size':len(rows),'root_hash':root,'first_sequence_no':rows[0].sequence_no,'last_sequence_no':rows[-1].sequence_no}
            cp=JourneyRecoveryMerkleCheckpointRow(merkle_checkpoint_id=nid('jrmc'),environment=environment,tree_size=len(rows),root_hash=root,first_sequence_no=rows[0].sequence_no,last_sequence_no=rows[-1].sequence_no,checkpoint_hash=sha(payload),state='ACTIVE',created_by=actor,created_at=now(),supplier_fact_unchanged=True)
            s.add(cp);s.commit();return self.checkpoint(cp.merkle_checkpoint_id)
    def inclusion_proof(self,sequence_no,checkpoint_id=None):
        with SessionLocal() as s:
            cp=s.get(JourneyRecoveryMerkleCheckpointRow,checkpoint_id) if checkpoint_id else s.execute(select(JourneyRecoveryMerkleCheckpointRow).order_by(JourneyRecoveryMerkleCheckpointRow.tree_size.desc(),JourneyRecoveryMerkleCheckpointRow.created_at.desc())).scalars().first()
            if not cp: raise ValueError('MERKLE_CHECKPOINT_NOT_FOUND')
            rows=s.execute(select(JourneyRecoveryTrustTransparencyLogRow).where(JourneyRecoveryTrustTransparencyLogRow.environment==cp.environment,JourneyRecoveryTrustTransparencyLogRow.sequence_no<=cp.last_sequence_no).order_by(JourneyRecoveryTrustTransparencyLogRow.sequence_no.asc())).scalars().all()
            matches=[i for i,r in enumerate(rows) if r.sequence_no==sequence_no]
            if not matches: raise ValueError('TRANSPARENCY_ENTRY_NOT_IN_CHECKPOINT')
            i=matches[0];proof=merkle_proof([r.entry_hash for r in rows],i)
            return {'sequence_no':sequence_no,'leaf_hash':rows[i].entry_hash,'checkpoint_id':cp.merkle_checkpoint_id,'tree_size':cp.tree_size,'root_hash':cp.root_hash,'proof':proof,'verified':verify_proof(rows[i].entry_hash,proof,cp.root_hash),'supplier_fact_unchanged':True}
    def register_witness(self,witness_key,environment,verification_key_ref,witness_fingerprint,actor):
        with SessionLocal() as s:
            if s.execute(select(JourneyRecoveryExternalTrustWitnessRow).where(JourneyRecoveryExternalTrustWitnessRow.witness_key==witness_key)).scalars().first(): raise ValueError('EXTERNAL_WITNESS_EXISTS')
            x=JourneyRecoveryExternalTrustWitnessRow(external_trust_witness_id=nid('jrwt'),witness_key=witness_key,environment=environment,verification_key_ref=verification_key_ref,witness_fingerprint=witness_fingerprint,state='ACTIVE',created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.witness(x.external_trust_witness_id)
    def sign_for_engineering(self,verification_key_ref,checkpoint_hash):
        key=os.environ.get(witness_env_key(verification_key_ref))
        if not key: raise ValueError('WITNESS_KEY_NOT_AVAILABLE')
        return hmac.new(key.encode(),checkpoint_hash.encode(),hashlib.sha256).hexdigest()
    def cosign_checkpoint(self,checkpoint_id,witness_id,signature,evidence_reference):
        with SessionLocal() as s:
            cp=s.get(JourneyRecoveryMerkleCheckpointRow,checkpoint_id);w=s.get(JourneyRecoveryExternalTrustWitnessRow,witness_id)
            if not cp or not w or w.state!='ACTIVE' or w.environment!=cp.environment: raise ValueError('ACTIVE_WITNESS_AND_CHECKPOINT_REQUIRED')
            key=os.environ.get(witness_env_key(w.verification_key_ref)); expected=hmac.new(key.encode(),cp.checkpoint_hash.encode(),hashlib.sha256).hexdigest() if key else None
            if not expected or not hmac.compare_digest(expected,signature): raise ValueError('INVALID_WITNESS_SIGNATURE')
            existing=s.execute(select(JourneyRecoveryWitnessCosignatureRow).where(JourneyRecoveryWitnessCosignatureRow.merkle_checkpoint_id==checkpoint_id,JourneyRecoveryWitnessCosignatureRow.external_trust_witness_id==witness_id)).scalars().first()
            if existing:return self.cosignature(existing.witness_cosignature_id)
            x=JourneyRecoveryWitnessCosignatureRow(witness_cosignature_id=nid('jrwcs'),merkle_checkpoint_id=checkpoint_id,external_trust_witness_id=witness_id,checkpoint_hash=cp.checkpoint_hash,signature=signature,evidence_reference=evidence_reference,verification_state='VERIFIED',signed_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.cosignature(x.witness_cosignature_id)
    def publish_region_replica(self,environment,region_key,credential_id,checkpoint_id,evidence_reference,actor,ttl_seconds=300,status_override=None):
        with SessionLocal() as s:
            cp=s.get(JourneyRecoveryMerkleCheckpointRow,checkpoint_id)
            if not cp or cp.environment!=environment: raise ValueError('CHECKPOINT_ENVIRONMENT_MISMATCH')
            st=s.execute(select(JourneyRecoveryCredentialStatusDistributionRow).where(JourneyRecoveryCredentialStatusDistributionRow.credential_id==credential_id,JourneyRecoveryCredentialStatusDistributionRow.publication_state=='PUBLISHED').order_by(JourneyRecoveryCredentialStatusDistributionRow.status_version.desc())).scalars().first()
            if not st: raise ValueError('CREDENTIAL_STATUS_NOT_PUBLISHED')
            status=status_override or st.status;t=now();payload={'environment':environment,'region_key':region_key,'credential_id':credential_id,'credential_status':status,'status_version':st.status_version,'checkpoint_hash':cp.checkpoint_hash,'tree_size':cp.tree_size}
            x=JourneyRecoveryRegionTrustReplicaRow(region_trust_replica_id=nid('jrrtr'),environment=environment,region_key=region_key,credential_id=credential_id,credential_status=status,status_version=st.status_version,checkpoint_hash=cp.checkpoint_hash,tree_size=cp.tree_size,replica_digest=sha(payload),observed_at=t,expires_at=t+timedelta(seconds=ttl_seconds),evidence_reference=evidence_reference,published_by=actor,supplier_fact_unchanged=True);s.add(x);s.commit();return self.replica(x.region_trust_replica_id)
    def create_policy(self,policy_key,environment,required_regions,minimum_witness_cosignatures,max_replica_age_seconds,actor):
        if len(set(required_regions))<2: raise ValueError('MULTI_REGION_POLICY_REQUIRES_TWO_REGIONS')
        with SessionLocal() as s:
            ver=(s.execute(select(func.max(JourneyRecoveryMultiRegionAdmissionPolicyRow.version_no)).where(JourneyRecoveryMultiRegionAdmissionPolicyRow.policy_key==policy_key)).scalar() or 0)+1
            p=JourneyRecoveryMultiRegionAdmissionPolicyRow(multi_region_admission_policy_id=nid('jrmap'),policy_key=policy_key,version_no=ver,environment=environment,required_regions_json=sorted(set(required_regions)),minimum_witness_cosignatures=minimum_witness_cosignatures,max_replica_age_seconds=max_replica_age_seconds,split_view_action='FAIL_SAFE_DENY',state='ACTIVE',created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(p);s.commit();return self.policy(p.multi_region_admission_policy_id)
    def evaluate_consensus(self,runtime_identity_id,credential_id,environment,cluster_id,actor):
        with SessionLocal() as s:
            p=s.execute(select(JourneyRecoveryMultiRegionAdmissionPolicyRow).where(JourneyRecoveryMultiRegionAdmissionPolicyRow.environment==environment,JourneyRecoveryMultiRegionAdmissionPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryMultiRegionAdmissionPolicyRow.created_at.desc())).scalars().first()
            if not p: raise ValueError('ACTIVE_MULTI_REGION_POLICY_REQUIRED')
            states={};reasons=[];replicas=[]
            isolated=s.execute(select(JourneyRecoveryRegionIsolationRow).where(JourneyRecoveryRegionIsolationRow.environment==environment,JourneyRecoveryRegionIsolationRow.state=='ISOLATED')).scalars().all()
            isolated_regions={x.region_key for x in isolated}
            if isolated_regions: reasons.append('REGION_ISOLATED_BY_TRUST_RECOVERY')
            for region in p.required_regions_json:
                r=s.execute(select(JourneyRecoveryRegionTrustReplicaRow).where(JourneyRecoveryRegionTrustReplicaRow.environment==environment,JourneyRecoveryRegionTrustReplicaRow.region_key==region,JourneyRecoveryRegionTrustReplicaRow.credential_id==credential_id).order_by(JourneyRecoveryRegionTrustReplicaRow.observed_at.desc())).scalars().first()
                if not r: states[region]={'state':'MISSING'};reasons.append('REGION_REPLICA_MISSING');continue
                fresh=aware(r.expires_at)>now() and (now()-aware(r.observed_at)).total_seconds()<=p.max_replica_age_seconds
                states[region]={'state':'FRESH' if fresh else 'STALE','status':r.credential_status,'status_version':r.status_version,'checkpoint_hash':r.checkpoint_hash,'replica_digest':r.replica_digest};replicas.append(r)
                if not fresh:reasons.append('REGION_REPLICA_STALE')
            statuses={r.credential_status for r in replicas};checkpoints={r.checkpoint_hash for r in replicas};split=len(statuses)>1 or len(checkpoints)>1
            cp_hash=next(iter(checkpoints)) if len(checkpoints)==1 else None
            witness_count=0
            if cp_hash:
                cp=s.execute(select(JourneyRecoveryMerkleCheckpointRow).where(JourneyRecoveryMerkleCheckpointRow.checkpoint_hash==cp_hash)).scalars().first()
                if cp:
                    cos=s.execute(select(JourneyRecoveryWitnessCosignatureRow).where(JourneyRecoveryWitnessCosignatureRow.merkle_checkpoint_id==cp.merkle_checkpoint_id,JourneyRecoveryWitnessCosignatureRow.verification_state=='VERIFIED')).scalars().all()
                    witness_ids=sorted(set(x.external_trust_witness_id for x in cos))
                    witness_count=len(witness_ids)
                    try:
                        from go_hotel.journey.recovery_trust_plane_dr import evaluate_independence_in_session
                        ind=evaluate_independence_in_session(s,environment,witness_ids)
                        if ind['governed']:
                            witness_count=ind['effective_independent_quorum']
                            if not ind['passed']: reasons.append('WITNESS_INDEPENDENCE_NOT_MET')
                    except Exception:
                        pass
            active_disasters=s.execute(select(JourneyRecoveryTrustPlaneDisasterIncidentRow).where(JourneyRecoveryTrustPlaneDisasterIncidentRow.environment==environment,JourneyRecoveryTrustPlaneDisasterIncidentRow.state=='OPEN')).scalars().all()
            unavailable=set()
            for d in active_disasters: unavailable.update(d.affected_regions_json or [])
            if unavailable.intersection(set(p.required_regions_json)): reasons.append('TRUST_PLANE_DISASTER_REGION_UNAVAILABLE')
            if split:reasons.append('SPLIT_VIEW_DETECTED')
            if witness_count<p.minimum_witness_cosignatures:reasons.append('WITNESS_QUORUM_NOT_MET')
            if statuses and statuses!={'GOOD'}:reasons.append('REGION_STATUS_NOT_GOOD')
            local=ft.evaluate_admission(runtime_identity_id,environment,cluster_id,actor)
            if local['decision']!='ALLOW':reasons.append('LOCAL_FEDERATED_ADMISSION_DENIED')
            allow=(not reasons and len(replicas)==len(p.required_regions_json) and statuses=={'GOOD'} and len(checkpoints)==1)
            decision='ALLOW' if allow else 'FAIL_SAFE_DENY';consensus='CONSISTENT' if allow else ('SPLIT_VIEW' if split else 'INSUFFICIENT_CONSENSUS')
            d=JourneyRecoveryMultiRegionAdmissionDecisionRow(multi_region_admission_decision_id=nid('jrmrad'),runtime_identity_id=runtime_identity_id,credential_id=credential_id,environment=environment,cluster_id=cluster_id,policy_id=p.multi_region_admission_policy_id,decision=decision,consensus_state=consensus,split_view_detected=split,region_states_json=states,checkpoint_hash=cp_hash,witness_count=witness_count,reason_codes_json=sorted(set(reasons)),decided_by=actor,decided_at=now(),supplier_fact_unchanged=True);s.add(d);s.commit();return self.decision(d.multi_region_admission_decision_id)
    def checkpoint(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryMerkleCheckpointRow,id)
            if not x:raise ValueError('MERKLE_CHECKPOINT_NOT_FOUND')
            return {'merkle_checkpoint_id':x.merkle_checkpoint_id,'environment':x.environment,'tree_size':x.tree_size,'root_hash':x.root_hash,'first_sequence_no':x.first_sequence_no,'last_sequence_no':x.last_sequence_no,'checkpoint_hash':x.checkpoint_hash,'state':x.state,'supplier_fact_unchanged':True}
    def witness(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryExternalTrustWitnessRow,id)
            if not x:raise ValueError('EXTERNAL_WITNESS_NOT_FOUND')
            return {'external_trust_witness_id':x.external_trust_witness_id,'witness_key':x.witness_key,'environment':x.environment,'witness_fingerprint':x.witness_fingerprint,'state':x.state,'supplier_fact_unchanged':True}
    def cosignature(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryWitnessCosignatureRow,id)
            if not x:raise ValueError('WITNESS_COSIGNATURE_NOT_FOUND')
            return {'witness_cosignature_id':x.witness_cosignature_id,'merkle_checkpoint_id':x.merkle_checkpoint_id,'external_trust_witness_id':x.external_trust_witness_id,'checkpoint_hash':x.checkpoint_hash,'verification_state':x.verification_state,'evidence_reference':x.evidence_reference,'supplier_fact_unchanged':True}
    def replica(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryRegionTrustReplicaRow,id)
            if not x:raise ValueError('REGION_TRUST_REPLICA_NOT_FOUND')
            return {'region_trust_replica_id':x.region_trust_replica_id,'environment':x.environment,'region_key':x.region_key,'credential_id':x.credential_id,'credential_status':x.credential_status,'status_version':x.status_version,'checkpoint_hash':x.checkpoint_hash,'tree_size':x.tree_size,'replica_digest':x.replica_digest,'observed_at':aware(x.observed_at).isoformat(),'expires_at':aware(x.expires_at).isoformat(),'supplier_fact_unchanged':True}
    def policy(self,id):
        with SessionLocal() as s:
            p=s.get(JourneyRecoveryMultiRegionAdmissionPolicyRow,id)
            if not p:raise ValueError('MULTI_REGION_POLICY_NOT_FOUND')
            return {'multi_region_admission_policy_id':p.multi_region_admission_policy_id,'policy_key':p.policy_key,'version_no':p.version_no,'environment':p.environment,'required_regions':p.required_regions_json,'minimum_witness_cosignatures':p.minimum_witness_cosignatures,'max_replica_age_seconds':p.max_replica_age_seconds,'split_view_action':p.split_view_action,'state':p.state,'supplier_fact_unchanged':True}
    def decision(self,id):
        with SessionLocal() as s:
            d=s.get(JourneyRecoveryMultiRegionAdmissionDecisionRow,id)
            if not d:raise ValueError('MULTI_REGION_ADMISSION_DECISION_NOT_FOUND')
            return {'multi_region_admission_decision_id':d.multi_region_admission_decision_id,'runtime_identity_id':d.runtime_identity_id,'credential_id':d.credential_id,'environment':d.environment,'cluster_id':d.cluster_id,'policy_id':d.policy_id,'decision':d.decision,'consensus_state':d.consensus_state,'split_view_detected':d.split_view_detected,'region_states':d.region_states_json,'checkpoint_hash':d.checkpoint_hash,'witness_count':d.witness_count,'reason_codes':d.reason_codes_json,'decided_at':aware(d.decided_at).isoformat(),'supplier_fact_unchanged':True}
    def public_checkpoint(self,environment='PROD'):
        with SessionLocal() as s:
            cp=s.execute(select(JourneyRecoveryMerkleCheckpointRow).where(JourneyRecoveryMerkleCheckpointRow.environment==environment).order_by(JourneyRecoveryMerkleCheckpointRow.tree_size.desc(),JourneyRecoveryMerkleCheckpointRow.created_at.desc())).scalars().first()
            if not cp:return {'environment':environment,'tree_size':0,'root_hash':None,'witness_count':0,'supplier_fact_unchanged':True}
            wc=s.execute(select(func.count(JourneyRecoveryWitnessCosignatureRow.witness_cosignature_id)).where(JourneyRecoveryWitnessCosignatureRow.merkle_checkpoint_id==cp.merkle_checkpoint_id,JourneyRecoveryWitnessCosignatureRow.verification_state=='VERIFIED')).scalar() or 0
            return {'environment':environment,'merkle_checkpoint_id':cp.merkle_checkpoint_id,'tree_size':cp.tree_size,'root_hash':cp.root_hash,'checkpoint_hash':cp.checkpoint_hash,'witness_count':wc,'supplier_fact_unchanged':True}

    def status(self,environment='PROD'):
        with SessionLocal() as s:
            cps=s.execute(select(JourneyRecoveryMerkleCheckpointRow).where(JourneyRecoveryMerkleCheckpointRow.environment==environment).order_by(JourneyRecoveryMerkleCheckpointRow.created_at.desc())).scalars().all()
            ws=s.execute(select(JourneyRecoveryExternalTrustWitnessRow).where(JourneyRecoveryExternalTrustWitnessRow.environment==environment).order_by(JourneyRecoveryExternalTrustWitnessRow.created_at.desc())).scalars().all()
            reps=s.execute(select(JourneyRecoveryRegionTrustReplicaRow).where(JourneyRecoveryRegionTrustReplicaRow.environment==environment).order_by(JourneyRecoveryRegionTrustReplicaRow.observed_at.desc())).scalars().all()
            pol=s.execute(select(JourneyRecoveryMultiRegionAdmissionPolicyRow).where(JourneyRecoveryMultiRegionAdmissionPolicyRow.environment==environment).order_by(JourneyRecoveryMultiRegionAdmissionPolicyRow.created_at.desc())).scalars().all()
            dec=s.execute(select(JourneyRecoveryMultiRegionAdmissionDecisionRow).where(JourneyRecoveryMultiRegionAdmissionDecisionRow.environment==environment).order_by(JourneyRecoveryMultiRegionAdmissionDecisionRow.decided_at.desc())).scalars().all()
            return {'environment':environment,'public_checkpoint':self.public_checkpoint(environment),'checkpoints':[self.checkpoint(x.merkle_checkpoint_id) for x in cps[:10]],'witnesses':[self.witness(x.external_trust_witness_id) for x in ws[:20]],'region_replicas':[self.replica(x.region_trust_replica_id) for x in reps[:30]],'policies':[self.policy(x.multi_region_admission_policy_id) for x in pol[:20]],'recent_decisions':[self.decision(x.multi_region_admission_decision_id) for x in dec[:30]],'supplier_fact_unchanged':True}

recovery_external_trust_witness_service=RecoveryExternalTrustWitnessService()
