from datetime import datetime, timezone
from uuid import uuid4
import hashlib, json
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryMerkleCheckpointRow, JourneyRecoveryTrustTransparencyLogRow,
    JourneyRecoveryWitnessCosignatureRow,
    JourneyRecoveryCheckpointGossipRow, JourneyRecoveryWitnessFederationRow,
    JourneyRecoveryConsistencyProofRow, JourneyRecoverySplitViewIncidentRow,
    JourneyRecoveryRegionIsolationRow, JourneyRecoveryTrustRecoveryRow,
)
from go_hotel.journey.recovery_external_trust_witness import merkle_root

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def sha(v): return hashlib.sha256(canon(v).encode()).hexdigest()

class RecoveryTransparencyGossipService:
    def publish_gossip(self,environment,observer_key,region_key,tree_size,root_hash,checkpoint_hash,evidence_reference,actor='system'):
        with SessionLocal() as s:
            x=JourneyRecoveryCheckpointGossipRow(checkpoint_gossip_id=nid('jrcg'),environment=environment,observer_key=observer_key,region_key=region_key,tree_size=tree_size,root_hash=root_hash,checkpoint_hash=checkpoint_hash,evidence_reference=evidence_reference,observed_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.gossip(x.checkpoint_gossip_id)
    def gossip_local_checkpoint(self,checkpoint_id,observer_key,region_key,evidence_reference,actor='system'):
        with SessionLocal() as s:
            cp=s.get(JourneyRecoveryMerkleCheckpointRow,checkpoint_id)
            if not cp: raise ValueError('MERKLE_CHECKPOINT_NOT_FOUND')
            args=(cp.environment,observer_key,region_key,cp.tree_size,cp.root_hash,cp.checkpoint_hash,evidence_reference,actor)
        return self.publish_gossip(*args)
    def create_witness_federation(self,federation_key,environment,witness_ids,minimum_quorum,actor):
        if not witness_ids or minimum_quorum<1 or minimum_quorum>len(set(witness_ids)): raise ValueError('INVALID_WITNESS_FEDERATION_QUORUM')
        with SessionLocal() as s:
            ver=(s.execute(select(func.max(JourneyRecoveryWitnessFederationRow.version_no)).where(JourneyRecoveryWitnessFederationRow.federation_key==federation_key)).scalar() or 0)+1
            x=JourneyRecoveryWitnessFederationRow(witness_federation_id=nid('jrwf'),federation_key=federation_key,version_no=ver,environment=environment,witness_ids_json=sorted(set(witness_ids)),minimum_quorum=minimum_quorum,state='ACTIVE',created_by=actor,created_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.federation(x.witness_federation_id)
    def create_consistency_proof(self,old_checkpoint_id,new_checkpoint_id,actor):
        with SessionLocal() as s:
            old=s.get(JourneyRecoveryMerkleCheckpointRow,old_checkpoint_id);new=s.get(JourneyRecoveryMerkleCheckpointRow,new_checkpoint_id)
            if not old or not new or old.environment!=new.environment: raise ValueError('CHECKPOINT_PAIR_INVALID')
            if old.tree_size>new.tree_size: raise ValueError('CHECKPOINT_ORDER_INVALID')
            rows=s.execute(select(JourneyRecoveryTrustTransparencyLogRow).where(JourneyRecoveryTrustTransparencyLogRow.environment==old.environment,JourneyRecoveryTrustTransparencyLogRow.sequence_no<=new.last_sequence_no).order_by(JourneyRecoveryTrustTransparencyLogRow.sequence_no.asc())).scalars().all()
            leaves=[r.entry_hash for r in rows]
            old_leaves=leaves[:old.tree_size];appended=leaves[old.tree_size:new.tree_size]
            ok=len(leaves)>=new.tree_size and merkle_root(old_leaves)==old.root_hash and merkle_root(old_leaves+appended)==new.root_hash
            payload={'old_checkpoint_id':old_checkpoint_id,'new_checkpoint_id':new_checkpoint_id,'old_root_hash':old.root_hash,'new_root_hash':new.root_hash,'old_leaf_hashes':old_leaves,'appended_leaf_hashes':appended}
            x=JourneyRecoveryConsistencyProofRow(consistency_proof_id=nid('jrcp'),environment=old.environment,old_checkpoint_id=old_checkpoint_id,new_checkpoint_id=new_checkpoint_id,old_tree_size=old.tree_size,new_tree_size=new.tree_size,old_root_hash=old.root_hash,new_root_hash=new.root_hash,old_leaf_hashes_json=old_leaves,appended_leaf_hashes_json=appended,proof_hash=sha(payload),verification_state='VERIFIED' if ok else 'FAILED',created_by=actor,created_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.proof(x.consistency_proof_id)
    def verify_consistency_proof(self,proof_id):
        p=self.proof(proof_id)
        ok=merkle_root(p['old_leaf_hashes'])==p['old_root_hash'] and merkle_root(p['old_leaf_hashes']+p['appended_leaf_hashes'])==p['new_root_hash'] and p['old_tree_size']+len(p['appended_leaf_hashes'])==p['new_tree_size']
        return {'consistency_proof_id':proof_id,'verified':ok,'old_tree_size':p['old_tree_size'],'new_tree_size':p['new_tree_size'],'old_root_hash':p['old_root_hash'],'new_root_hash':p['new_root_hash'],'supplier_fact_unchanged':True}
    def detect_split_view(self,environment,tree_size,evidence_reference,actor):
        with SessionLocal() as s:
            rows=s.execute(select(JourneyRecoveryCheckpointGossipRow).where(JourneyRecoveryCheckpointGossipRow.environment==environment,JourneyRecoveryCheckpointGossipRow.tree_size==tree_size).order_by(JourneyRecoveryCheckpointGossipRow.observed_at.desc())).scalars().all()
            latest={}
            for r in rows:
                latest.setdefault(r.observer_key,r)
            states={k:{'region_key':r.region_key,'root_hash':r.root_hash,'checkpoint_hash':r.checkpoint_hash} for k,r in latest.items()}
            hashes=sorted(set(r.checkpoint_hash for r in latest.values()))
            roots=sorted(set(r.root_hash for r in latest.values()))
            if len(hashes)<=1 and len(roots)<=1: return {'split_view_detected':False,'tree_size':tree_size,'observer_states':states,'supplier_fact_unchanged':True}
            regions=sorted(set(r.region_key for r in latest.values()))
            existing=s.execute(select(JourneyRecoverySplitViewIncidentRow).where(JourneyRecoverySplitViewIncidentRow.environment==environment,JourneyRecoverySplitViewIncidentRow.tree_size==tree_size,JourneyRecoverySplitViewIncidentRow.state=='OPEN')).scalars().first()
            if existing:return self.incident(existing.split_view_incident_id)
            inc=JourneyRecoverySplitViewIncidentRow(split_view_incident_id=nid('jrsv'),environment=environment,tree_size=tree_size,observer_states_json=states,conflicting_checkpoint_hashes_json=hashes,affected_regions_json=regions,state='OPEN',severity='SEV1',evidence_reference=evidence_reference,opened_by=actor,opened_at=now(),resolved_at=None,supplier_fact_unchanged=True)
            s.add(inc);s.flush()
            for region in regions:
                s.add(JourneyRecoveryRegionIsolationRow(region_isolation_id=nid('jriso'),environment=environment,region_key=region,split_view_incident_id=inc.split_view_incident_id,state='ISOLATED',reason_code='SPLIT_VIEW_DETECTED',isolated_by=actor,isolated_at=now(),rejoined_at=None,supplier_fact_unchanged=True))
            s.commit();return self.incident(inc.split_view_incident_id)
    def request_recovery(self,incident_id,region_key,target_checkpoint_id,consistency_proof_id,witness_federation_id,evidence_reference,actor):
        with SessionLocal() as s:
            inc=s.get(JourneyRecoverySplitViewIncidentRow,incident_id);cp=s.get(JourneyRecoveryMerkleCheckpointRow,target_checkpoint_id);proof=s.get(JourneyRecoveryConsistencyProofRow,consistency_proof_id);fed=s.get(JourneyRecoveryWitnessFederationRow,witness_federation_id)
            if not inc or inc.state!='OPEN': raise ValueError('OPEN_SPLIT_VIEW_INCIDENT_REQUIRED')
            if not cp or cp.environment!=inc.environment or not proof or proof.verification_state!='VERIFIED' or proof.new_checkpoint_id!=target_checkpoint_id: raise ValueError('VERIFIED_CONSISTENCY_PROOF_REQUIRED')
            if not fed or fed.state!='ACTIVE' or fed.environment!=inc.environment: raise ValueError('ACTIVE_WITNESS_FEDERATION_REQUIRED')
            cos=s.execute(select(JourneyRecoveryWitnessCosignatureRow).where(JourneyRecoveryWitnessCosignatureRow.merkle_checkpoint_id==target_checkpoint_id,JourneyRecoveryWitnessCosignatureRow.verification_state=='VERIFIED')).scalars().all()
            witness_ids=sorted(set(x.external_trust_witness_id for x in cos if x.external_trust_witness_id in set(fed.witness_ids_json)))
            count=len(witness_ids)
            try:
                from go_hotel.journey.recovery_trust_plane_dr import evaluate_independence_in_session
                ind=evaluate_independence_in_session(s,inc.environment,witness_ids)
                if ind['governed']:
                    count=ind['effective_independent_quorum']
                    if not ind['passed']: raise ValueError('WITNESS_INDEPENDENCE_GOVERNANCE_NOT_MET')
            except ImportError:
                pass
            if count<fed.minimum_quorum: raise ValueError('WITNESS_FEDERATION_QUORUM_NOT_MET')
            iso=s.execute(select(JourneyRecoveryRegionIsolationRow).where(JourneyRecoveryRegionIsolationRow.split_view_incident_id==incident_id,JourneyRecoveryRegionIsolationRow.region_key==region_key,JourneyRecoveryRegionIsolationRow.state=='ISOLATED')).scalars().first()
            if not iso: raise ValueError('ISOLATED_REGION_REQUIRED')
            x=JourneyRecoveryTrustRecoveryRow(trust_recovery_id=nid('jrrec'),split_view_incident_id=incident_id,environment=inc.environment,region_key=region_key,target_checkpoint_id=target_checkpoint_id,consistency_proof_id=consistency_proof_id,witness_federation_id=witness_federation_id,witness_quorum_count=count,evidence_reference=evidence_reference,state='VERIFIED_FOR_REJOIN',requested_by=actor,requested_at=now(),completed_at=None,supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.recovery(x.trust_recovery_id)
    def rejoin_region(self,recovery_id,actor):
        with SessionLocal() as s:
            rec=s.get(JourneyRecoveryTrustRecoveryRow,recovery_id)
            if not rec or rec.state!='VERIFIED_FOR_REJOIN': raise ValueError('VERIFIED_TRUST_RECOVERY_REQUIRED')
            iso=s.execute(select(JourneyRecoveryRegionIsolationRow).where(JourneyRecoveryRegionIsolationRow.split_view_incident_id==rec.split_view_incident_id,JourneyRecoveryRegionIsolationRow.region_key==rec.region_key,JourneyRecoveryRegionIsolationRow.state=='ISOLATED')).scalars().first()
            if not iso: raise ValueError('ISOLATED_REGION_REQUIRED')
            iso.state='REJOINED';iso.rejoined_at=now();rec.state='REJOINED';rec.completed_at=now()
            remaining=s.execute(select(JourneyRecoveryRegionIsolationRow).where(JourneyRecoveryRegionIsolationRow.split_view_incident_id==rec.split_view_incident_id,JourneyRecoveryRegionIsolationRow.state=='ISOLATED')).scalars().all()
            inc=s.get(JourneyRecoverySplitViewIncidentRow,rec.split_view_incident_id)
            if len(remaining)<=1: # current row is already changed in session and excluded after flush below
                s.flush();remaining=s.execute(select(JourneyRecoveryRegionIsolationRow).where(JourneyRecoveryRegionIsolationRow.split_view_incident_id==rec.split_view_incident_id,JourneyRecoveryRegionIsolationRow.state=='ISOLATED')).scalars().all()
            if not remaining: inc.state='RESOLVED';inc.resolved_at=now()
            s.commit();return self.recovery(recovery_id)
    def isolated_regions(self,environment):
        with SessionLocal() as s:return [self.isolation(x.region_isolation_id) for x in s.execute(select(JourneyRecoveryRegionIsolationRow).where(JourneyRecoveryRegionIsolationRow.environment==environment,JourneyRecoveryRegionIsolationRow.state=='ISOLATED')).scalars().all()]
    def status(self,environment):
        with SessionLocal() as s:
            inc=s.execute(select(JourneyRecoverySplitViewIncidentRow).where(JourneyRecoverySplitViewIncidentRow.environment==environment).order_by(JourneyRecoverySplitViewIncidentRow.opened_at.desc())).scalars().all()
            fed=s.execute(select(JourneyRecoveryWitnessFederationRow).where(JourneyRecoveryWitnessFederationRow.environment==environment).order_by(JourneyRecoveryWitnessFederationRow.created_at.desc())).scalars().all()
            gos=s.execute(select(JourneyRecoveryCheckpointGossipRow).where(JourneyRecoveryCheckpointGossipRow.environment==environment).order_by(JourneyRecoveryCheckpointGossipRow.observed_at.desc())).scalars().all()
            rec=s.execute(select(JourneyRecoveryTrustRecoveryRow).where(JourneyRecoveryTrustRecoveryRow.environment==environment).order_by(JourneyRecoveryTrustRecoveryRow.requested_at.desc())).scalars().all()
            return {'environment':environment,'isolated_regions':self.isolated_regions(environment),'incidents':[self.incident(x.split_view_incident_id) for x in inc[:20]],'witness_federations':[self.federation(x.witness_federation_id) for x in fed[:20]],'recent_gossip':[self.gossip(x.checkpoint_gossip_id) for x in gos[:30]],'recoveries':[self.recovery(x.trust_recovery_id) for x in rec[:20]],'supplier_fact_unchanged':True}
    def gossip(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryCheckpointGossipRow,i);return None if not x else {'checkpoint_gossip_id':x.checkpoint_gossip_id,'environment':x.environment,'observer_key':x.observer_key,'region_key':x.region_key,'tree_size':x.tree_size,'root_hash':x.root_hash,'checkpoint_hash':x.checkpoint_hash,'evidence_reference':x.evidence_reference,'observed_at':x.observed_at.isoformat(),'supplier_fact_unchanged':True}
    def federation(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryWitnessFederationRow,i);return None if not x else {'witness_federation_id':x.witness_federation_id,'federation_key':x.federation_key,'version_no':x.version_no,'environment':x.environment,'witness_ids':x.witness_ids_json,'minimum_quorum':x.minimum_quorum,'state':x.state,'supplier_fact_unchanged':True}
    def proof(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryConsistencyProofRow,i);return None if not x else {'consistency_proof_id':x.consistency_proof_id,'environment':x.environment,'old_checkpoint_id':x.old_checkpoint_id,'new_checkpoint_id':x.new_checkpoint_id,'old_tree_size':x.old_tree_size,'new_tree_size':x.new_tree_size,'old_root_hash':x.old_root_hash,'new_root_hash':x.new_root_hash,'old_leaf_hashes':x.old_leaf_hashes_json,'appended_leaf_hashes':x.appended_leaf_hashes_json,'proof_hash':x.proof_hash,'verification_state':x.verification_state,'supplier_fact_unchanged':True}
    def incident(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoverySplitViewIncidentRow,i);return None if not x else {'split_view_incident_id':x.split_view_incident_id,'environment':x.environment,'tree_size':x.tree_size,'observer_states':x.observer_states_json,'conflicting_checkpoint_hashes':x.conflicting_checkpoint_hashes_json,'affected_regions':x.affected_regions_json,'state':x.state,'severity':x.severity,'evidence_reference':x.evidence_reference,'supplier_fact_unchanged':True}
    def isolation(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryRegionIsolationRow,i);return None if not x else {'region_isolation_id':x.region_isolation_id,'environment':x.environment,'region_key':x.region_key,'split_view_incident_id':x.split_view_incident_id,'state':x.state,'reason_code':x.reason_code,'supplier_fact_unchanged':True}
    def recovery(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryTrustRecoveryRow,i);return None if not x else {'trust_recovery_id':x.trust_recovery_id,'split_view_incident_id':x.split_view_incident_id,'environment':x.environment,'region_key':x.region_key,'target_checkpoint_id':x.target_checkpoint_id,'consistency_proof_id':x.consistency_proof_id,'witness_federation_id':x.witness_federation_id,'witness_quorum_count':x.witness_quorum_count,'state':x.state,'supplier_fact_unchanged':True}

recovery_transparency_gossip_service=RecoveryTransparencyGossipService()
