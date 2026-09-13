from datetime import datetime, timezone, timedelta
from uuid import uuid4
import hashlib, hmac, json, os, re
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryRuntimeIdentityRow, JourneyRecoverySignedTelemetryEnvelopeRow,
    JourneyRecoveryTelemetryTrustAssessmentRow, JourneyRecoveryIncidentAutomationPolicyRow,
    JourneyRecoveryTelemetrySourceRow, JourneyRecoveryReleaseSafetyAssessmentRow,
    JourneyRecoveryTelemetryKeyVersionRow, JourneyRecoveryTelemetrySecurityIncidentRow,
    JourneyRecoveryAttestationPolicyRow, JourneyRecoveryCredentialIssuanceRow,
    JourneyRecoveryCredentialIssuerRow, JourneyRecoveryHardwareTrustRootRow,
    JourneyRecoveryFederatedAdmissionPolicyRow, JourneyRecoveryTrustFederationRow,
    JourneyRecoveryCredentialStatusDistributionRow, JourneyRecoveryTrustTransparencyLogRow,
)
from go_hotel.journey.recovery_runtime_telemetry_governance import recovery_runtime_telemetry_governance_service as telemetry
from go_hotel.journey.recovery_runtime_observability import recovery_runtime_observability_service as runtime_safety

LEVEL={'LOW':1,'MEDIUM':2,'HIGH':3}
def now(): return datetime.now(timezone.utc)
def aware(x): return x.replace(tzinfo=timezone.utc) if x and x.tzinfo is None else x
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def sha(v): return hashlib.sha256(canon(v).encode()).hexdigest()
def env_key(ref): return 'GO_TELEMETRY_SIGNING_KEY_'+re.sub(r'[^A-Z0-9]','_',ref.upper())

class RecoveryRuntimeTelemetryTrustService:
    def register_identity(self,identity_key,identity_type,environment,subject_ref,verification_key_ref,actor):
        if identity_type not in {'WORKLOAD','COLLECTOR'}: raise ValueError('INVALID_RUNTIME_IDENTITY_TYPE')
        if environment not in {'DEV','STAGING','PROD'}: raise ValueError('INVALID_ENVIRONMENT')
        fp=sha({'identity_key':identity_key,'identity_type':identity_type,'environment':environment,'subject_ref':subject_ref,'verification_key_ref':verification_key_ref})
        with SessionLocal() as s:
            if s.execute(select(JourneyRecoveryRuntimeIdentityRow).where(JourneyRecoveryRuntimeIdentityRow.identity_key==identity_key)).scalars().first(): raise ValueError('RUNTIME_IDENTITY_KEY_EXISTS')
            r=JourneyRecoveryRuntimeIdentityRow(runtime_identity_id=nid('jrri'),identity_key=identity_key,identity_type=identity_type,environment=environment,state='ACTIVE',subject_ref=subject_ref,verification_key_ref=verification_key_ref,identity_fingerprint=fp,created_by=actor,created_at=now(),updated_at=now(),supplier_fact_unchanged=True);s.add(r);s.flush();
            kv=JourneyRecoveryTelemetryKeyVersionRow(telemetry_key_version_id=nid('jrtkv'),runtime_identity_id=r.runtime_identity_id,version_no=1,key_ref=verification_key_ref,state='ACTIVE',valid_from=now(),valid_until=None,previous_key_version_id=None,transition_payload_hash=None,transition_signature=None,evidence_json={'bootstrap':True},created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(kv);s.commit();return self.identity(r.runtime_identity_id)
    def identity(self,id):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryRuntimeIdentityRow,id)
            if not r: raise ValueError('RUNTIME_IDENTITY_NOT_FOUND')
            return {'runtime_identity_id':r.runtime_identity_id,'identity_key':r.identity_key,'identity_type':r.identity_type,'environment':r.environment,'state':r.state,'subject_ref':r.subject_ref,'verification_key_ref':r.verification_key_ref,'identity_fingerprint':r.identity_fingerprint,'supplier_fact_unchanged':True}
    def set_identity_state(self,id,state,actor):
        if state not in {'ACTIVE','SUSPENDED','REVOKED'}: raise ValueError('INVALID_RUNTIME_IDENTITY_STATE')
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryRuntimeIdentityRow,id)
            if not r: raise ValueError('RUNTIME_IDENTITY_NOT_FOUND')
            if r.state=='REVOKED' and state=='ACTIVE': raise ValueError('REVOKED_IDENTITY_REQUIRES_REISSUANCE')
            r.state=state;r.updated_at=now();s.commit();return self.identity(id)
    def create_policy(self,policy_key,environment,actor,min_evidence_level_for_freeze='HIGH',min_source_quorum=2,max_clock_skew_seconds=120,envelope_freshness_seconds=300,allow_auto_freeze=True,allow_auto_rollback_recommendation=True,policy=None):
        if min_evidence_level_for_freeze not in LEVEL: raise ValueError('INVALID_EVIDENCE_LEVEL')
        if min_source_quorum<1: raise ValueError('INVALID_SOURCE_QUORUM')
        with SessionLocal() as s:
            if s.execute(select(JourneyRecoveryIncidentAutomationPolicyRow).where(JourneyRecoveryIncidentAutomationPolicyRow.policy_key==policy_key)).scalars().first(): raise ValueError('AUTOMATION_POLICY_KEY_EXISTS')
            p=JourneyRecoveryIncidentAutomationPolicyRow(incident_automation_policy_id=nid('jriap'),policy_key=policy_key,environment=environment,state='ACTIVE',min_evidence_level_for_freeze=min_evidence_level_for_freeze,min_source_quorum=min_source_quorum,max_clock_skew_seconds=max_clock_skew_seconds,envelope_freshness_seconds=envelope_freshness_seconds,allow_auto_freeze=allow_auto_freeze,allow_auto_rollback_recommendation=allow_auto_rollback_recommendation,policy_json=policy or {},created_by=actor,created_at=now(),updated_at=now(),supplier_fact_unchanged=True);s.add(p);s.commit();return self.policy(p.incident_automation_policy_id)
    def _policy(self,s,environment): return s.execute(select(JourneyRecoveryIncidentAutomationPolicyRow).where(JourneyRecoveryIncidentAutomationPolicyRow.environment==environment,JourneyRecoveryIncidentAutomationPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryIncidentAutomationPolicyRow.created_at.desc())).scalars().first()
    def policy(self,id):
        with SessionLocal() as s:
            p=s.get(JourneyRecoveryIncidentAutomationPolicyRow,id)
            if not p: raise ValueError('AUTOMATION_POLICY_NOT_FOUND')
            return {'incident_automation_policy_id':p.incident_automation_policy_id,'policy_key':p.policy_key,'environment':p.environment,'state':p.state,'min_evidence_level_for_freeze':p.min_evidence_level_for_freeze,'min_source_quorum':p.min_source_quorum,'max_clock_skew_seconds':p.max_clock_skew_seconds,'envelope_freshness_seconds':p.envelope_freshness_seconds,'allow_auto_freeze':p.allow_auto_freeze,'allow_auto_rollback_recommendation':p.allow_auto_rollback_recommendation,'policy':p.policy_json,'supplier_fact_unchanged':True}
    def signing_message(self,source_id,workload_identity_id,collector_identity_id,environment,nonce,sequence_no,observed_at,metrics):
        ts=observed_at if isinstance(observed_at,str) else aware(observed_at).isoformat()
        return canon({'telemetry_source_id':source_id,'workload_identity_id':workload_identity_id,'collector_identity_id':collector_identity_id,'environment':environment,'nonce':nonce,'sequence_no':int(sequence_no),'observed_at':ts,'metrics':metrics})
    def sign_for_engineering(self,key_ref,**kwargs):
        key=os.getenv(env_key(key_ref))
        if not key: raise ValueError('SIGNING_KEY_UNAVAILABLE')
        return hmac.new(key.encode(),self.signing_message(**kwargs).encode(),hashlib.sha256).hexdigest()
    def ingest_signed(self,source_id,workload_identity_id,collector_identity_id,runtime_instance,metrics,nonce,sequence_no,observed_at,signature,actor='telemetry'):
        observed_at=datetime.fromisoformat(observed_at.replace('Z','+00:00')) if isinstance(observed_at,str) else aware(observed_at)
        with SessionLocal() as s:
            src=s.get(JourneyRecoveryTelemetrySourceRow,source_id);w=s.get(JourneyRecoveryRuntimeIdentityRow,workload_identity_id);c=s.get(JourneyRecoveryRuntimeIdentityRow,collector_identity_id)
            if not src: raise ValueError('TELEMETRY_SOURCE_NOT_FOUND')
            if not w or not c: raise ValueError('RUNTIME_IDENTITY_NOT_FOUND')
            if w.identity_type!='WORKLOAD' or c.identity_type!='COLLECTOR': raise ValueError('IDENTITY_ROLE_MISMATCH')
            if w.state!='ACTIVE' or c.state!='ACTIVE': raise ValueError('RUNTIME_IDENTITY_NOT_ACTIVE')
            if len({src.environment,w.environment,c.environment})!=1: raise ValueError('IDENTITY_ENVIRONMENT_MISMATCH')
            if s.execute(select(JourneyRecoverySignedTelemetryEnvelopeRow).where(JourneyRecoverySignedTelemetryEnvelopeRow.nonce==nonce)).scalars().first(): raise ValueError('TELEMETRY_REPLAY_DETECTED')
            prev=s.execute(select(JourneyRecoverySignedTelemetryEnvelopeRow).where(JourneyRecoverySignedTelemetryEnvelopeRow.collector_identity_id==collector_identity_id).order_by(JourneyRecoverySignedTelemetryEnvelopeRow.sequence_no.desc())).scalars().first()
            if prev and sequence_no<=prev.sequence_no: raise ValueError('TELEMETRY_SEQUENCE_REPLAY_DETECTED')
            p=self._policy(s,src.environment);max_skew=p.max_clock_skew_seconds if p else 120
            skew=abs((now()-aware(observed_at)).total_seconds())
            if skew>max_skew: raise ValueError('TELEMETRY_CLOCK_SKEW_EXCEEDED')
            active_incident=s.execute(select(JourneyRecoveryTelemetrySecurityIncidentRow).where(JourneyRecoveryTelemetrySecurityIncidentRow.runtime_identity_id==collector_identity_id,JourneyRecoveryTelemetrySecurityIncidentRow.state.in_(['OPEN','CONTAINED']),JourneyRecoveryTelemetrySecurityIncidentRow.quarantine_state=='QUARANTINED')).scalars().first()
            if active_incident: raise ValueError('RUNTIME_IDENTITY_QUARANTINED')
            key_versions=s.execute(select(JourneyRecoveryTelemetryKeyVersionRow).where(JourneyRecoveryTelemetryKeyVersionRow.runtime_identity_id==collector_identity_id,JourneyRecoveryTelemetryKeyVersionRow.state.in_(['ACTIVE','OVERLAP'])).order_by(JourneyRecoveryTelemetryKeyVersionRow.version_no.desc())).scalars().all()
            if not key_versions:
                key_versions=[type('LegacyKey',(),{'telemetry_key_version_id':None,'key_ref':c.verification_key_ref,'valid_from':None,'valid_until':None})()]
            msg=self.signing_message(source_id=source_id,workload_identity_id=workload_identity_id,collector_identity_id=collector_identity_id,environment=src.environment,nonce=nonce,sequence_no=sequence_no,observed_at=observed_at,metrics=metrics)
            matched=None
            for kv in key_versions:
                if kv.valid_from and aware(observed_at)<aware(kv.valid_from): continue
                if kv.valid_until and aware(observed_at)>aware(kv.valid_until): continue
                key=os.getenv(env_key(kv.key_ref))
                if not key: continue
                expected=hmac.new(key.encode(),msg.encode(),hashlib.sha256).hexdigest()
                if hmac.compare_digest(expected,signature): matched=kv;break
            if not matched: raise ValueError('TELEMETRY_SIGNATURE_INVALID')
            e=JourneyRecoverySignedTelemetryEnvelopeRow(telemetry_envelope_id=nid('jrste'),telemetry_source_id=source_id,workload_identity_id=workload_identity_id,collector_identity_id=collector_identity_id,environment=src.environment,nonce=nonce,sequence_no=sequence_no,observed_at=observed_at,received_at=now(),payload_hash=sha(metrics),signature=signature,verification_state='VERIFIED',verification_json={'clock_skew_seconds':skew,'anti_replay':'PASS','signature':'HMAC_SHA256_ENGINEERING_CONTRACT','key_version_id':getattr(matched,'telemetry_key_version_id',None),'key_ref':matched.key_ref,'workload_identity_fingerprint':w.identity_fingerprint,'collector_identity_fingerprint':c.identity_fingerprint},supplier_fact_unchanged=True);s.add(e);s.commit();eid=e.telemetry_envelope_id
        out=telemetry.ingest(source_id,runtime_instance,metrics,actor)
        with SessionLocal() as s:
            e=s.get(JourneyRecoverySignedTelemetryEnvelopeRow,eid);e.runtime_observation_id=out['observation']['runtime_observation_id'];s.commit()
        return {'telemetry_envelope_id':eid,'verification_state':'VERIFIED','observation':out['observation'],'quality':out['quality'],'supplier_fact_unchanged':True}
    def assess_trust(self,environment='PROD'):
        with SessionLocal() as s:
            p=self._policy(s,environment)
            if not p: raise ValueError('ACTIVE_INCIDENT_AUTOMATION_POLICY_REQUIRED')
            cutoff=now()-timedelta(seconds=p.envelope_freshness_seconds)
            rows=s.execute(select(JourneyRecoverySignedTelemetryEnvelopeRow).where(JourneyRecoverySignedTelemetryEnvelopeRow.environment==environment,JourneyRecoverySignedTelemetryEnvelopeRow.verification_state=='VERIFIED',JourneyRecoverySignedTelemetryEnvelopeRow.received_at>=cutoff).order_by(JourneyRecoverySignedTelemetryEnvelopeRow.received_at.desc())).scalars().all()
            eligible=[]
            for r in rows:
                w=s.get(JourneyRecoveryRuntimeIdentityRow,r.workload_identity_id);c=s.get(JourneyRecoveryRuntimeIdentityRow,r.collector_identity_id)
                if not w or not c or w.state!='ACTIVE' or c.state!='ACTIVE': continue
                quarantined=s.execute(select(JourneyRecoveryTelemetrySecurityIncidentRow).where(JourneyRecoveryTelemetrySecurityIncidentRow.runtime_identity_id.in_([r.workload_identity_id,r.collector_identity_id]),JourneyRecoveryTelemetrySecurityIncidentRow.state.in_(['OPEN','CONTAINED']),JourneyRecoveryTelemetrySecurityIncidentRow.quarantine_state=='QUARANTINED')).scalars().first()
                if quarantined: continue
                governed_credential_policy=s.execute(select(JourneyRecoveryAttestationPolicyRow).where(JourneyRecoveryAttestationPolicyRow.environment==environment,JourneyRecoveryAttestationPolicyRow.state=='ACTIVE')).scalars().first()
                if governed_credential_policy:
                    identity_ids=[r.workload_identity_id,r.collector_identity_id]
                    credential_gate_passed=True
                    for identity_id in identity_ids:
                        creds=s.execute(select(JourneyRecoveryCredentialIssuanceRow).where(JourneyRecoveryCredentialIssuanceRow.runtime_identity_id==identity_id,JourneyRecoveryCredentialIssuanceRow.environment==environment,JourneyRecoveryCredentialIssuanceRow.state=='ISSUED',JourneyRecoveryCredentialIssuanceRow.eligibility_state=='ELIGIBLE')).scalars().all()
                        credential_ok=False
                        for cred in creds:
                            pol=s.get(JourneyRecoveryAttestationPolicyRow,cred.attestation_policy_id);issuer=s.get(JourneyRecoveryCredentialIssuerRow,cred.credential_issuer_id);root=s.get(JourneyRecoveryHardwareTrustRootRow,cred.hardware_trust_root_id)
                            if pol and pol.state=='ACTIVE' and issuer and issuer.state=='ACTIVE' and root and root.state=='ACTIVE':
                                # Sprint 3Z: when an ACTIVE federated admission policy exists, local credential validity
                                # is not enough. The credential must also have fresh published status, a governed
                                # trust federation for the root, and (when required) a transparency-log entry.
                                ap=s.execute(select(JourneyRecoveryFederatedAdmissionPolicyRow).where(JourneyRecoveryFederatedAdmissionPolicyRow.environment==environment,JourneyRecoveryFederatedAdmissionPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryFederatedAdmissionPolicyRow.created_at.desc())).scalars().first()
                                if ap:
                                    feds=s.execute(select(JourneyRecoveryTrustFederationRow).where(JourneyRecoveryTrustFederationRow.environment==environment,JourneyRecoveryTrustFederationRow.hardware_trust_root_id==cred.hardware_trust_root_id,JourneyRecoveryTrustFederationRow.state=='ACTIVE')).scalars().all()
                                    feds=[f for f in feds if f.cluster_scope in {'default','*'} and (not ap.allowed_federation_ids_json or f.trust_federation_id in ap.allowed_federation_ids_json)]
                                    if not feds: continue
                                    st=s.execute(select(JourneyRecoveryCredentialStatusDistributionRow).where(JourneyRecoveryCredentialStatusDistributionRow.credential_id==cred.credential_id,JourneyRecoveryCredentialStatusDistributionRow.publication_state=='PUBLISHED').order_by(JourneyRecoveryCredentialStatusDistributionRow.status_version.desc())).scalars().first()
                                    if not st or st.status!='GOOD': continue
                                    if aware(st.next_update_at)<=now() or (now()-aware(st.this_update_at)).total_seconds()>ap.min_status_freshness_seconds: continue
                                    if ap.require_transparency_log:
                                        log=s.execute(select(JourneyRecoveryTrustTransparencyLogRow).where(JourneyRecoveryTrustTransparencyLogRow.subject_type=='CREDENTIAL',JourneyRecoveryTrustTransparencyLogRow.subject_id==cred.credential_id,JourneyRecoveryTrustTransparencyLogRow.event_type=='CREDENTIAL_STATUS_PUBLISHED')).scalars().first()
                                        if not log: continue
                                credential_ok=True;break
                        if not credential_ok:
                            credential_gate_passed=False;break
                    if not credential_gate_passed: continue
                eligible.append(r)
            distinct={r.telemetry_source_id:r for r in eligible};count=len(distinct);quorum=count>=p.min_source_quorum
            evidence_level='HIGH' if quorum and count>=max(2,p.min_source_quorum) else ('MEDIUM' if count>=1 else 'LOW')
            allowed=quorum and LEVEL[evidence_level]>=LEVEL[p.min_evidence_level_for_freeze]
            state='ALLOW_AUTOMATION' if allowed else 'HUMAN_REVIEW_ONLY'
            evidence={'verified_sources':sorted(distinct),'verified_envelopes':len(eligible),'excluded_envelopes':len(rows)-len(eligible),'required_quorum':p.min_source_quorum,'min_evidence_level_for_freeze':p.min_evidence_level_for_freeze,'anti_replay_enforced':True,'clock_skew_enforced':True,'signed_identity_required':True,'credential_authority_gate':bool(s.execute(select(JourneyRecoveryAttestationPolicyRow).where(JourneyRecoveryAttestationPolicyRow.environment==environment,JourneyRecoveryAttestationPolicyRow.state=='ACTIVE')).scalars().first()),'federated_trust_gate':bool(s.execute(select(JourneyRecoveryFederatedAdmissionPolicyRow).where(JourneyRecoveryFederatedAdmissionPolicyRow.environment==environment,JourneyRecoveryFederatedAdmissionPolicyRow.state=='ACTIVE')).scalars().first())}
            a=JourneyRecoveryTelemetryTrustAssessmentRow(telemetry_trust_assessment_id=nid('jrtta'),environment=environment,state=state,evidence_level=evidence_level,source_quorum=p.min_source_quorum,verified_source_count=count,evidence_json=evidence,assessed_at=now(),supplier_fact_unchanged=True);s.add(a);s.commit();return self.trust(a.telemetry_trust_assessment_id)
    def trust(self,id):
        with SessionLocal() as s:
            a=s.get(JourneyRecoveryTelemetryTrustAssessmentRow,id)
            if not a: raise ValueError('TELEMETRY_TRUST_ASSESSMENT_NOT_FOUND')
            return {'telemetry_trust_assessment_id':a.telemetry_trust_assessment_id,'environment':a.environment,'state':a.state,'evidence_level':a.evidence_level,'source_quorum':a.source_quorum,'verified_source_count':a.verified_source_count,'evidence':a.evidence_json,'supplier_fact_unchanged':True}
    def governed_assess(self,environment='PROD',actor='incident-automation-controller'):
        t=self.assess_trust(environment)
        with SessionLocal() as s: p=self._policy(s,environment)
        if t['state']!='ALLOW_AUTOMATION':
            return {'environment':environment,'automation_decision':'HUMAN_REVIEW_ONLY','trust':t,'safety_assessment':None,'supplier_fact_unchanged':True}
        a=telemetry.assess(environment,actor)
        decision='AUTO_ACTION_ALLOWED'
        if a['action']=='FREEZE_PROMOTION_AND_RECOMMEND_ROLLBACK' and not p.allow_auto_rollback_recommendation: decision='AUTO_FREEZE_ONLY_REVIEW_ROLLBACK'
        if a['action'] in {'FREEZE_PROMOTION','FREEZE_PROMOTION_AND_RECOMMEND_ROLLBACK'} and not p.allow_auto_freeze:
            # safety assessment is preserved, but unwind automatic freeze and require human review
            with SessionLocal() as s:
                runtime_safety._set_freeze(s,environment,False,'INCIDENT_AUTOMATION_POLICY_REQUIRES_HUMAN_REVIEW',a['safety_assessment_id'],actor);s.commit()
            decision='HUMAN_REVIEW_ONLY'
        return {'environment':environment,'automation_decision':decision,'trust':t,'safety_assessment':a,'supplier_fact_unchanged':True}
    def status(self,environment='PROD'):
        with SessionLocal() as s:
            p=self._policy(s,environment);t=s.execute(select(JourneyRecoveryTelemetryTrustAssessmentRow).where(JourneyRecoveryTelemetryTrustAssessmentRow.environment==environment).order_by(JourneyRecoveryTelemetryTrustAssessmentRow.assessed_at.desc())).scalars().first();ids=s.execute(select(JourneyRecoveryRuntimeIdentityRow).where(JourneyRecoveryRuntimeIdentityRow.environment==environment).order_by(JourneyRecoveryRuntimeIdentityRow.created_at.desc())).scalars().all()
            return {'environment':environment,'active_policy':self.policy(p.incident_automation_policy_id) if p else None,'identities':[self.identity(x.runtime_identity_id) for x in ids],'latest_trust_assessment':self.trust(t.telemetry_trust_assessment_id) if t else None,'telemetry_governance':telemetry.status(environment),'supplier_fact_unchanged':True}

recovery_runtime_telemetry_trust_service=RecoveryRuntimeTelemetryTrustService()
