from datetime import datetime, timezone
from uuid import uuid4
import hashlib, json
from collections import Counter
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryExternalTrustWitnessRow, JourneyRecoveryWitnessFederationRow,
    JourneyRecoveryWitnessCosignatureRow, JourneyRecoveryMerkleCheckpointRow,
    JourneyRecoveryTrustTransparencyLogRow,
    JourneyRecoveryWitnessOperatorRow, JourneyRecoveryWitnessIndependenceBindingRow,
    JourneyRecoveryWitnessIndependencePolicyRow, JourneyRecoveryWitnessIndependenceAssessmentRow,
    JourneyRecoveryCrossOperatorGossipRow, JourneyRecoveryCheckpointArchiveRow,
    JourneyRecoveryTrustPlaneDisasterIncidentRow, JourneyRecoveryTrustPlaneRebuildRow,
    JourneyRecoveryTrustPlaneRecoveryDrillRow,
)
from go_hotel.journey.recovery_external_trust_witness import merkle_root


def now(): return datetime.now(timezone.utc)
def aware(v): return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def canon(v): return json.dumps(v, sort_keys=True, separators=(',', ':'), default=str)
def sha(v): return hashlib.sha256(canon(v).encode()).hexdigest()


def active_independence_policy(session, environment):
    return session.execute(
        select(JourneyRecoveryWitnessIndependencePolicyRow)
        .where(JourneyRecoveryWitnessIndependencePolicyRow.environment==environment,
               JourneyRecoveryWitnessIndependencePolicyRow.state=='ACTIVE')
        .order_by(JourneyRecoveryWitnessIndependencePolicyRow.version_no.desc(),
                  JourneyRecoveryWitnessIndependencePolicyRow.created_at.desc())
    ).scalars().first()


def evaluate_independence_in_session(session, environment, witness_ids):
    """Pure governance evaluation used by 4A/4B/4C. No Supplier Fact mutation."""
    policy=active_independence_policy(session, environment)
    if not policy:
        return {'governed':False,'passed':True,'effective_independent_quorum':len(set(witness_ids)),
                'operator_count':len(set(witness_ids)),'failure_domain_count':len(set(witness_ids)),
                'cloud_provider_count':len(set(witness_ids)),'key_authority_count':len(set(witness_ids)),
                'reason_codes':[],'policy_id':None}
    bindings=session.execute(
        select(JourneyRecoveryWitnessIndependenceBindingRow)
        .where(JourneyRecoveryWitnessIndependenceBindingRow.environment==environment,
               JourneyRecoveryWitnessIndependenceBindingRow.external_trust_witness_id.in_(list(set(witness_ids))))
    ).scalars().all() if witness_ids else []
    by_witness={b.external_trust_witness_id:b for b in bindings}
    missing=sorted(set(witness_ids)-set(by_witness))
    ops=[b.witness_operator_id for b in bindings]
    operator_counts=Counter(ops)
    effective=sum(min(v, policy.max_witnesses_per_operator) for v in operator_counts.values())
    operator_count=len(operator_counts)
    failure_domain_count=len({b.failure_domain for b in bindings})
    cloud_provider_count=len({b.cloud_provider for b in bindings})
    key_authority_count=len({b.key_authority for b in bindings})
    reasons=[]
    if missing: reasons.append('WITNESS_INDEPENDENCE_BINDING_MISSING')
    if operator_count<policy.minimum_operator_quorum: reasons.append('OPERATOR_INDEPENDENCE_QUORUM_NOT_MET')
    if failure_domain_count<policy.minimum_failure_domains: reasons.append('FAILURE_DOMAIN_DIVERSITY_NOT_MET')
    if cloud_provider_count<policy.minimum_cloud_providers: reasons.append('CLOUD_PROVIDER_DIVERSITY_NOT_MET')
    if key_authority_count<policy.minimum_key_authorities: reasons.append('KEY_AUTHORITY_DIVERSITY_NOT_MET')
    if any(v>policy.max_witnesses_per_operator for v in operator_counts.values()): reasons.append('WITNESS_OPERATOR_CONCENTRATION_DETECTED')
    return {'governed':True,'passed':not reasons,'effective_independent_quorum':effective,
            'operator_count':operator_count,'failure_domain_count':failure_domain_count,
            'cloud_provider_count':cloud_provider_count,'key_authority_count':key_authority_count,
            'reason_codes':sorted(set(reasons)),'policy_id':policy.witness_independence_policy_id}


class RecoveryTrustPlaneDRService:
    def register_operator(self,operator_key,organization_ref,control_domain,cloud_provider,key_authority,actor):
        with SessionLocal() as s:
            if s.execute(select(JourneyRecoveryWitnessOperatorRow).where(JourneyRecoveryWitnessOperatorRow.operator_key==operator_key)).scalars().first():
                raise ValueError('WITNESS_OPERATOR_EXISTS')
            x=JourneyRecoveryWitnessOperatorRow(witness_operator_id=nid('jwop'),operator_key=operator_key,
                organization_ref=organization_ref,control_domain=control_domain,cloud_provider=cloud_provider,
                key_authority=key_authority,state='ACTIVE',created_by=actor,created_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.operator(x.witness_operator_id)

    def bind_witness(self,witness_id,operator_id,region_key,failure_domain,cloud_provider,key_authority,evidence_reference,actor):
        with SessionLocal() as s:
            w=s.get(JourneyRecoveryExternalTrustWitnessRow,witness_id);op=s.get(JourneyRecoveryWitnessOperatorRow,operator_id)
            if not w or w.state!='ACTIVE': raise ValueError('ACTIVE_EXTERNAL_WITNESS_REQUIRED')
            if not op or op.state!='ACTIVE': raise ValueError('ACTIVE_WITNESS_OPERATOR_REQUIRED')
            if s.execute(select(JourneyRecoveryWitnessIndependenceBindingRow).where(JourneyRecoveryWitnessIndependenceBindingRow.external_trust_witness_id==witness_id)).scalars().first():
                raise ValueError('WITNESS_ALREADY_BOUND_TO_INDEPENDENCE_DOMAIN')
            x=JourneyRecoveryWitnessIndependenceBindingRow(witness_independence_binding_id=nid('jwib'),external_trust_witness_id=witness_id,
                witness_operator_id=operator_id,environment=w.environment,region_key=region_key,failure_domain=failure_domain,
                cloud_provider=cloud_provider,key_authority=key_authority,evidence_reference=evidence_reference,bound_by=actor,bound_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.binding(x.witness_independence_binding_id)

    def create_independence_policy(self,policy_key,environment,minimum_operator_quorum,minimum_failure_domains,minimum_cloud_providers,minimum_key_authorities,max_witnesses_per_operator,actor):
        vals=[minimum_operator_quorum,minimum_failure_domains,minimum_cloud_providers,minimum_key_authorities,max_witnesses_per_operator]
        if any(v<1 for v in vals): raise ValueError('INVALID_WITNESS_INDEPENDENCE_POLICY')
        with SessionLocal() as s:
            ver=(s.execute(select(func.max(JourneyRecoveryWitnessIndependencePolicyRow.version_no)).where(JourneyRecoveryWitnessIndependencePolicyRow.policy_key==policy_key)).scalar() or 0)+1
            # Supersede older ACTIVE version without mutating immutable evidence; policy is governance state, not evidence.
            olds=s.execute(select(JourneyRecoveryWitnessIndependencePolicyRow).where(JourneyRecoveryWitnessIndependencePolicyRow.policy_key==policy_key,JourneyRecoveryWitnessIndependencePolicyRow.state=='ACTIVE')).scalars().all()
            for o in olds:o.state='SUPERSEDED'
            x=JourneyRecoveryWitnessIndependencePolicyRow(witness_independence_policy_id=nid('jwip'),policy_key=policy_key,version_no=ver,environment=environment,
                minimum_operator_quorum=minimum_operator_quorum,minimum_failure_domains=minimum_failure_domains,
                minimum_cloud_providers=minimum_cloud_providers,minimum_key_authorities=minimum_key_authorities,
                max_witnesses_per_operator=max_witnesses_per_operator,state='ACTIVE',created_by=actor,created_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.policy(x.witness_independence_policy_id)

    def assess_federation(self,federation_id,actor):
        with SessionLocal() as s:
            fed=s.get(JourneyRecoveryWitnessFederationRow,federation_id)
            if not fed or fed.state!='ACTIVE': raise ValueError('ACTIVE_WITNESS_FEDERATION_REQUIRED')
            result=evaluate_independence_in_session(s,fed.environment,fed.witness_ids_json)
            if not result['governed']: raise ValueError('ACTIVE_WITNESS_INDEPENDENCE_POLICY_REQUIRED')
            x=JourneyRecoveryWitnessIndependenceAssessmentRow(witness_independence_assessment_id=nid('jwia'),witness_federation_id=federation_id,
                witness_independence_policy_id=result['policy_id'],environment=fed.environment,operator_count=result['operator_count'],failure_domain_count=result['failure_domain_count'],
                cloud_provider_count=result['cloud_provider_count'],key_authority_count=result['key_authority_count'],effective_independent_quorum=result['effective_independent_quorum'],
                state='PASS' if result['passed'] else 'FAIL',reason_codes_json=result['reason_codes'],assessed_by=actor,assessed_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.assessment(x.witness_independence_assessment_id)

    def publish_cross_operator_gossip(self,operator_id,checkpoint_id,region_key,evidence_reference,actor):
        from go_hotel.journey.recovery_transparency_gossip import recovery_transparency_gossip_service as gossip
        with SessionLocal() as s:
            op=s.get(JourneyRecoveryWitnessOperatorRow,operator_id);cp=s.get(JourneyRecoveryMerkleCheckpointRow,checkpoint_id)
            if not op or op.state!='ACTIVE': raise ValueError('ACTIVE_WITNESS_OPERATOR_REQUIRED')
            if not cp: raise ValueError('MERKLE_CHECKPOINT_NOT_FOUND')
            payload={'operator_id':operator_id,'region_key':region_key,'checkpoint_hash':cp.checkpoint_hash,'root_hash':cp.root_hash,'tree_size':cp.tree_size}
            x=JourneyRecoveryCrossOperatorGossipRow(cross_operator_gossip_id=nid('jxcg'),environment=cp.environment,witness_operator_id=operator_id,region_key=region_key,
                merkle_checkpoint_id=checkpoint_id,tree_size=cp.tree_size,root_hash=cp.root_hash,checkpoint_hash=cp.checkpoint_hash,peer_digest=sha(payload),
                evidence_reference=evidence_reference,observed_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();out=self.cross_gossip(x.cross_operator_gossip_id)
        gossip.publish_gossip(out['environment'],f"operator:{operator_id}",region_key,out['tree_size'],out['root_hash'],out['checkpoint_hash'],evidence_reference,actor)
        return out

    def detect_cross_operator_split_view(self,environment,tree_size,evidence_reference,actor):
        from go_hotel.journey.recovery_transparency_gossip import recovery_transparency_gossip_service as gossip
        with SessionLocal() as s:
            rows=s.execute(select(JourneyRecoveryCrossOperatorGossipRow).where(JourneyRecoveryCrossOperatorGossipRow.environment==environment,JourneyRecoveryCrossOperatorGossipRow.tree_size==tree_size).order_by(JourneyRecoveryCrossOperatorGossipRow.observed_at.desc())).scalars().all()
            latest={}
            for r in rows: latest.setdefault(r.witness_operator_id,r)
            if len(latest)<2:
                return {'split_view_detected':False,'reason_codes':['CROSS_OPERATOR_GOSSIP_QUORUM_NOT_MET'],'operator_count':len(latest),'supplier_fact_unchanged':True}
        return gossip.detect_split_view(environment,tree_size,evidence_reference,actor)

    def archive_checkpoint(self,checkpoint_id,storage_reference,actor):
        with SessionLocal() as s:
            cp=s.get(JourneyRecoveryMerkleCheckpointRow,checkpoint_id)
            if not cp: raise ValueError('MERKLE_CHECKPOINT_NOT_FOUND')
            rows=s.execute(select(JourneyRecoveryTrustTransparencyLogRow).where(JourneyRecoveryTrustTransparencyLogRow.environment==cp.environment,JourneyRecoveryTrustTransparencyLogRow.sequence_no<=cp.last_sequence_no).order_by(JourneyRecoveryTrustTransparencyLogRow.sequence_no.asc())).scalars().all()
            leaves=[r.entry_hash for r in rows]
            valid=len(leaves)==cp.tree_size and merkle_root(leaves)==cp.root_hash
            payload={'checkpoint_id':checkpoint_id,'tree_size':cp.tree_size,'root_hash':cp.root_hash,'checkpoint_hash':cp.checkpoint_hash,'leaf_hashes':leaves}
            x=JourneyRecoveryCheckpointArchiveRow(checkpoint_archive_id=nid('jcar'),environment=cp.environment,merkle_checkpoint_id=checkpoint_id,tree_size=cp.tree_size,root_hash=cp.root_hash,
                checkpoint_hash=cp.checkpoint_hash,leaf_hashes_json=leaves,archive_hash=sha(payload),storage_reference=storage_reference,state='VERIFIED' if valid else 'INVALID',
                archived_by=actor,archived_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.archive(x.checkpoint_archive_id)

    def verify_archive(self,archive_id):
        a=self.archive(archive_id)
        payload={'checkpoint_id':a['merkle_checkpoint_id'],'tree_size':a['tree_size'],'root_hash':a['root_hash'],'checkpoint_hash':a['checkpoint_hash'],'leaf_hashes':a['leaf_hashes']}
        ok=merkle_root(a['leaf_hashes'])==a['root_hash'] and sha(payload)==a['archive_hash']
        return {'checkpoint_archive_id':archive_id,'verified':ok,'tree_size':a['tree_size'],'root_hash':a['root_hash'],'checkpoint_hash':a['checkpoint_hash'],'supplier_fact_unchanged':True}

    def open_disaster(self,environment,failure_scope,failure_domain_key,affected_regions,evidence_reference,actor,drill_mode=False):
        if failure_scope not in {'REGION','PROVIDER'}: raise ValueError('INVALID_TRUST_PLANE_FAILURE_SCOPE')
        if not affected_regions: raise ValueError('AFFECTED_REGIONS_REQUIRED')
        with SessionLocal() as s:
            x=JourneyRecoveryTrustPlaneDisasterIncidentRow(trust_plane_disaster_incident_id=nid('jdr'),environment=environment,failure_scope=failure_scope,
                failure_domain_key=failure_domain_key,affected_regions_json=sorted(set(affected_regions)),state='OPEN',severity='SEV1',drill_mode=bool(drill_mode),
                evidence_reference=evidence_reference,opened_by=actor,opened_at=now(),recovered_at=None,supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.disaster(x.trust_plane_disaster_incident_id)

    def rebuild_from_archive(self,incident_id,archive_id,target_region_key,witness_federation_id,evidence_reference,actor):
        with SessionLocal() as s:
            inc=s.get(JourneyRecoveryTrustPlaneDisasterIncidentRow,incident_id);a=s.get(JourneyRecoveryCheckpointArchiveRow,archive_id);fed=s.get(JourneyRecoveryWitnessFederationRow,witness_federation_id)
            if not inc or inc.state!='OPEN': raise ValueError('OPEN_TRUST_PLANE_DISASTER_REQUIRED')
            if target_region_key not in set(inc.affected_regions_json): raise ValueError('TARGET_REGION_NOT_AFFECTED')
            if not a or a.state!='VERIFIED' or a.environment!=inc.environment: raise ValueError('VERIFIED_CHECKPOINT_ARCHIVE_REQUIRED')
            if not fed or fed.state!='ACTIVE' or fed.environment!=inc.environment: raise ValueError('ACTIVE_WITNESS_FEDERATION_REQUIRED')
            ind=evaluate_independence_in_session(s,inc.environment,fed.witness_ids_json)
            if not ind['governed'] or not ind['passed'] or ind['effective_independent_quorum']<fed.minimum_quorum:
                raise ValueError('WITNESS_INDEPENDENCE_GOVERNANCE_NOT_MET')
            cp=s.get(JourneyRecoveryMerkleCheckpointRow,a.merkle_checkpoint_id)
            cos=s.execute(select(JourneyRecoveryWitnessCosignatureRow).where(JourneyRecoveryWitnessCosignatureRow.merkle_checkpoint_id==a.merkle_checkpoint_id,JourneyRecoveryWitnessCosignatureRow.verification_state=='VERIFIED')).scalars().all()
            signed_ids=[c.external_trust_witness_id for c in cos if c.external_trust_witness_id in set(fed.witness_ids_json)]
            signed_ind=evaluate_independence_in_session(s,inc.environment,signed_ids)
            if not signed_ind['passed'] or signed_ind['effective_independent_quorum']<fed.minimum_quorum:
                raise ValueError('INDEPENDENT_WITNESS_COSIGNATURE_QUORUM_NOT_MET')
            latest_assessment=s.execute(select(JourneyRecoveryWitnessIndependenceAssessmentRow).where(JourneyRecoveryWitnessIndependenceAssessmentRow.witness_federation_id==witness_federation_id,JourneyRecoveryWitnessIndependenceAssessmentRow.state=='PASS').order_by(JourneyRecoveryWitnessIndependenceAssessmentRow.assessed_at.desc())).scalars().first()
            if not latest_assessment:
                latest_assessment=JourneyRecoveryWitnessIndependenceAssessmentRow(witness_independence_assessment_id=nid('jwia'),witness_federation_id=witness_federation_id,
                    witness_independence_policy_id=ind['policy_id'],environment=inc.environment,operator_count=ind['operator_count'],failure_domain_count=ind['failure_domain_count'],
                    cloud_provider_count=ind['cloud_provider_count'],key_authority_count=ind['key_authority_count'],effective_independent_quorum=ind['effective_independent_quorum'],state='PASS',reason_codes_json=[],assessed_by=actor,assessed_at=now(),supplier_fact_unchanged=True)
                s.add(latest_assessment);s.flush()
            rebuilt_root=merkle_root(a.leaf_hashes_json);valid=rebuilt_root==a.root_hash and (cp is None or cp.checkpoint_hash==a.checkpoint_hash)
            x=JourneyRecoveryTrustPlaneRebuildRow(trust_plane_rebuild_id=nid('jrbld'),trust_plane_disaster_incident_id=incident_id,checkpoint_archive_id=archive_id,target_region_key=target_region_key,
                rebuilt_root_hash=rebuilt_root,rebuilt_checkpoint_hash=a.checkpoint_hash,verification_state='VERIFIED' if valid else 'FAILED',witness_independence_assessment_id=latest_assessment.witness_independence_assessment_id,
                evidence_reference=evidence_reference,started_by=actor,started_at=now(),completed_at=now() if valid else None,supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.rebuild(x.trust_plane_rebuild_id)

    def complete_disaster_recovery(self,incident_id,actor,evidence_reference):
        with SessionLocal() as s:
            inc=s.get(JourneyRecoveryTrustPlaneDisasterIncidentRow,incident_id)
            if not inc or inc.state!='OPEN': raise ValueError('OPEN_TRUST_PLANE_DISASTER_REQUIRED')
            builds=s.execute(select(JourneyRecoveryTrustPlaneRebuildRow).where(JourneyRecoveryTrustPlaneRebuildRow.trust_plane_disaster_incident_id==incident_id,JourneyRecoveryTrustPlaneRebuildRow.verification_state=='VERIFIED')).scalars().all()
            recovered_regions={b.target_region_key for b in builds}
            if not set(inc.affected_regions_json).issubset(recovered_regions): raise ValueError('ALL_AFFECTED_REGIONS_REQUIRE_VERIFIED_REBUILD')
            inc.state='RECOVERED';inc.recovered_at=now();s.commit();return self.disaster(incident_id)

    def record_recovery_drill(self,incident_id,rebuild_id,evidence_reference,actor):
        with SessionLocal() as s:
            inc=s.get(JourneyRecoveryTrustPlaneDisasterIncidentRow,incident_id);b=s.get(JourneyRecoveryTrustPlaneRebuildRow,rebuild_id)
            if not inc or not inc.drill_mode: raise ValueError('DRILL_MODE_INCIDENT_REQUIRED')
            if inc.state!='RECOVERED' or not b or b.verification_state!='VERIFIED': raise ValueError('RECOVERED_INCIDENT_AND_VERIFIED_REBUILD_REQUIRED')
            secs=max(0,int((aware(inc.recovered_at)-aware(inc.opened_at)).total_seconds()))
            x=JourneyRecoveryTrustPlaneRecoveryDrillRow(trust_plane_recovery_drill_id=nid('jdrill'),trust_plane_disaster_incident_id=incident_id,trust_plane_rebuild_id=rebuild_id,
                environment=inc.environment,recovery_time_seconds=secs,result='PASS',evidence_reference=evidence_reference,recorded_by=actor,recorded_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.drill(x.trust_plane_recovery_drill_id)

    def operator(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryWitnessOperatorRow,i);return None if not x else {'witness_operator_id':x.witness_operator_id,'operator_key':x.operator_key,'organization_ref':x.organization_ref,'control_domain':x.control_domain,'cloud_provider':x.cloud_provider,'key_authority':x.key_authority,'state':x.state,'supplier_fact_unchanged':True}
    def binding(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryWitnessIndependenceBindingRow,i);return None if not x else {'witness_independence_binding_id':x.witness_independence_binding_id,'external_trust_witness_id':x.external_trust_witness_id,'witness_operator_id':x.witness_operator_id,'environment':x.environment,'region_key':x.region_key,'failure_domain':x.failure_domain,'cloud_provider':x.cloud_provider,'key_authority':x.key_authority,'supplier_fact_unchanged':True}
    def policy(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryWitnessIndependencePolicyRow,i);return None if not x else {'witness_independence_policy_id':x.witness_independence_policy_id,'policy_key':x.policy_key,'version_no':x.version_no,'environment':x.environment,'minimum_operator_quorum':x.minimum_operator_quorum,'minimum_failure_domains':x.minimum_failure_domains,'minimum_cloud_providers':x.minimum_cloud_providers,'minimum_key_authorities':x.minimum_key_authorities,'max_witnesses_per_operator':x.max_witnesses_per_operator,'state':x.state,'supplier_fact_unchanged':True}
    def assessment(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryWitnessIndependenceAssessmentRow,i);return None if not x else {'witness_independence_assessment_id':x.witness_independence_assessment_id,'witness_federation_id':x.witness_federation_id,'environment':x.environment,'operator_count':x.operator_count,'failure_domain_count':x.failure_domain_count,'cloud_provider_count':x.cloud_provider_count,'key_authority_count':x.key_authority_count,'effective_independent_quorum':x.effective_independent_quorum,'state':x.state,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
    def cross_gossip(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryCrossOperatorGossipRow,i);return None if not x else {'cross_operator_gossip_id':x.cross_operator_gossip_id,'environment':x.environment,'witness_operator_id':x.witness_operator_id,'region_key':x.region_key,'merkle_checkpoint_id':x.merkle_checkpoint_id,'tree_size':x.tree_size,'root_hash':x.root_hash,'checkpoint_hash':x.checkpoint_hash,'peer_digest':x.peer_digest,'supplier_fact_unchanged':True}
    def archive(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryCheckpointArchiveRow,i)
            if not x: raise ValueError('CHECKPOINT_ARCHIVE_NOT_FOUND')
            return {'checkpoint_archive_id':x.checkpoint_archive_id,'environment':x.environment,'merkle_checkpoint_id':x.merkle_checkpoint_id,'tree_size':x.tree_size,'root_hash':x.root_hash,'checkpoint_hash':x.checkpoint_hash,'leaf_hashes':x.leaf_hashes_json,'archive_hash':x.archive_hash,'storage_reference':x.storage_reference,'state':x.state,'supplier_fact_unchanged':True}
    def disaster(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryTrustPlaneDisasterIncidentRow,i);return None if not x else {'trust_plane_disaster_incident_id':x.trust_plane_disaster_incident_id,'environment':x.environment,'failure_scope':x.failure_scope,'failure_domain_key':x.failure_domain_key,'affected_regions':x.affected_regions_json,'state':x.state,'severity':x.severity,'drill_mode':x.drill_mode,'evidence_reference':x.evidence_reference,'supplier_fact_unchanged':True}
    def rebuild(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryTrustPlaneRebuildRow,i);return None if not x else {'trust_plane_rebuild_id':x.trust_plane_rebuild_id,'trust_plane_disaster_incident_id':x.trust_plane_disaster_incident_id,'checkpoint_archive_id':x.checkpoint_archive_id,'target_region_key':x.target_region_key,'rebuilt_root_hash':x.rebuilt_root_hash,'rebuilt_checkpoint_hash':x.rebuilt_checkpoint_hash,'verification_state':x.verification_state,'witness_independence_assessment_id':x.witness_independence_assessment_id,'supplier_fact_unchanged':True}
    def drill(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryTrustPlaneRecoveryDrillRow,i);return None if not x else {'trust_plane_recovery_drill_id':x.trust_plane_recovery_drill_id,'trust_plane_disaster_incident_id':x.trust_plane_disaster_incident_id,'trust_plane_rebuild_id':x.trust_plane_rebuild_id,'environment':x.environment,'recovery_time_seconds':x.recovery_time_seconds,'result':x.result,'supplier_fact_unchanged':True}
    def status(self,environment='PROD'):
        with SessionLocal() as s:
            ops=s.execute(select(JourneyRecoveryWitnessOperatorRow).where(JourneyRecoveryWitnessOperatorRow.state=='ACTIVE')).scalars().all()
            pol=s.execute(select(JourneyRecoveryWitnessIndependencePolicyRow).where(JourneyRecoveryWitnessIndependencePolicyRow.environment==environment,JourneyRecoveryWitnessIndependencePolicyRow.state=='ACTIVE')).scalars().all()
            assessments=s.execute(select(JourneyRecoveryWitnessIndependenceAssessmentRow).where(JourneyRecoveryWitnessIndependenceAssessmentRow.environment==environment).order_by(JourneyRecoveryWitnessIndependenceAssessmentRow.assessed_at.desc())).scalars().all()
            disasters=s.execute(select(JourneyRecoveryTrustPlaneDisasterIncidentRow).where(JourneyRecoveryTrustPlaneDisasterIncidentRow.environment==environment).order_by(JourneyRecoveryTrustPlaneDisasterIncidentRow.opened_at.desc())).scalars().all()
            return {'environment':environment,'operators':[self.operator(x.witness_operator_id) for x in ops[:20]],'active_policies':[self.policy(x.witness_independence_policy_id) for x in pol[:10]],'recent_assessments':[self.assessment(x.witness_independence_assessment_id) for x in assessments[:20]],'disasters':[self.disaster(x.trust_plane_disaster_incident_id) for x in disasters[:20]],'supplier_fact_unchanged':True}

recovery_trust_plane_dr_service=RecoveryTrustPlaneDRService()
