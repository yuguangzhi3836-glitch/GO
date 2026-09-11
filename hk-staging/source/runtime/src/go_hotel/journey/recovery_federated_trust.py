from datetime import datetime, timezone, timedelta
from uuid import uuid4
import hashlib, json
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryHardwareTrustRootRow,JourneyRecoveryCredentialIssuerRow,JourneyRecoveryCredentialIssuanceRow,
    JourneyRecoveryRuntimeIdentityRow,JourneyRecoveryTrustFederationRow,JourneyRecoveryCredentialStatusDistributionRow,
    JourneyRecoveryTrustTransparencyLogRow,JourneyRecoveryIssuerCompromiseRow,JourneyRecoveryFederatedAdmissionPolicyRow,
    JourneyRecoveryFederatedAdmissionDecisionRow,
)
from go_hotel.journey.recovery_runtime_identity_lifecycle import recovery_runtime_identity_lifecycle_service as lifecycle

def now(): return datetime.now(timezone.utc)
def aware(v):
    if v is None:return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def sha(v): return hashlib.sha256(canon(v).encode()).hexdigest()

class RecoveryFederatedTrustService:
    def _append_log(self,s,event_type,subject_type,subject_id,environment,payload,evidence_reference,actor):
        last=s.execute(select(JourneyRecoveryTrustTransparencyLogRow).order_by(JourneyRecoveryTrustTransparencyLogRow.sequence_no.desc())).scalars().first()
        seq=(last.sequence_no if last else 0)+1;prev=last.entry_hash if last else None;ph=sha(payload)
        eh=sha({'sequence_no':seq,'event_type':event_type,'subject_type':subject_type,'subject_id':subject_id,'environment':environment,'payload_hash':ph,'previous_hash':prev})
        x=JourneyRecoveryTrustTransparencyLogRow(transparency_log_id=nid('jrttl'),sequence_no=seq,event_type=event_type,subject_type=subject_type,subject_id=subject_id,environment=environment,payload_hash=ph,previous_hash=prev,entry_hash=eh,evidence_reference=evidence_reference,created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(x);s.flush();return x
    def register_federation(self,federation_key,environment,cluster_scope,hardware_trust_root_id,peer_fingerprint,policy_version,actor):
        with SessionLocal() as s:
            root=s.get(JourneyRecoveryHardwareTrustRootRow,hardware_trust_root_id)
            if not root or root.state!='ACTIVE': raise ValueError('ACTIVE_TRUST_ROOT_REQUIRED_FOR_FEDERATION')
            if s.execute(select(JourneyRecoveryTrustFederationRow).where(JourneyRecoveryTrustFederationRow.federation_key==federation_key)).scalars().first(): raise ValueError('TRUST_FEDERATION_EXISTS')
            x=JourneyRecoveryTrustFederationRow(trust_federation_id=nid('jrtf'),federation_key=federation_key,environment=environment,cluster_scope=cluster_scope,hardware_trust_root_id=hardware_trust_root_id,state='ACTIVE',peer_fingerprint=peer_fingerprint,policy_version=policy_version,last_synchronized_at=now(),created_by=actor,created_at=now(),updated_at=now(),supplier_fact_unchanged=True);s.add(x)
            self._append_log(s,'TRUST_FEDERATION_REGISTERED','TRUST_ROOT',hardware_trust_root_id,environment,{'federation_key':federation_key,'cluster_scope':cluster_scope,'peer_fingerprint':peer_fingerprint,'policy_version':policy_version},f'federation://{federation_key}',actor);s.commit();return self.federation(x.trust_federation_id)
    def publish_credential_status(self,credential_id,status,evidence_reference,actor,ttl_seconds=300):
        if status not in {'GOOD','REVOKED','SUSPENDED','UNKNOWN'}: raise ValueError('INVALID_CREDENTIAL_STATUS')
        if ttl_seconds<30: raise ValueError('STATUS_TTL_TOO_SHORT')
        with SessionLocal() as s:
            cred=s.execute(select(JourneyRecoveryCredentialIssuanceRow).where(JourneyRecoveryCredentialIssuanceRow.credential_id==credential_id)).scalars().first()
            if not cred: raise ValueError('CREDENTIAL_NOT_FOUND')
            ver=(s.execute(select(func.max(JourneyRecoveryCredentialStatusDistributionRow.status_version)).where(JourneyRecoveryCredentialStatusDistributionRow.credential_id==credential_id)).scalar() or 0)+1
            t=now();payload={'credential_id':credential_id,'status':status,'version':ver,'this_update_at':t.isoformat(),'next_update_at':(t+timedelta(seconds=ttl_seconds)).isoformat(),'issuer_id':cred.credential_issuer_id,'root_id':cred.hardware_trust_root_id}
            x=JourneyRecoveryCredentialStatusDistributionRow(credential_status_distribution_id=nid('jrcsd'),credential_id=credential_id,environment=cred.environment,status=status,status_version=ver,this_update_at=t,next_update_at=t+timedelta(seconds=ttl_seconds),issuer_id=cred.credential_issuer_id,root_id=cred.hardware_trust_root_id,status_hash=sha(payload),publication_state='PUBLISHED',evidence_reference=evidence_reference,published_by=actor,published_at=t,supplier_fact_unchanged=True);s.add(x);s.flush()
            log=self._append_log(s,'CREDENTIAL_STATUS_PUBLISHED','CREDENTIAL',credential_id,cred.environment,payload,evidence_reference,actor);s.commit();out=self.status_distribution(x.credential_status_distribution_id);out['transparency_log_id']=log.transparency_log_id;return out
    def create_admission_policy(self,policy_key,environment,cluster_scope,min_status_freshness_seconds,allowed_federation_ids,require_transparency_log,actor,policy=None):
        if min_status_freshness_seconds<30: raise ValueError('INVALID_STATUS_FRESHNESS_POLICY')
        with SessionLocal() as s:
            ver=(s.execute(select(func.max(JourneyRecoveryFederatedAdmissionPolicyRow.version_no)).where(JourneyRecoveryFederatedAdmissionPolicyRow.policy_key==policy_key)).scalar() or 0)+1
            for fid in allowed_federation_ids:
                f=s.get(JourneyRecoveryTrustFederationRow,fid)
                if not f or f.state!='ACTIVE' or f.environment!=environment: raise ValueError('ACTIVE_FEDERATION_REQUIRED')
            p=JourneyRecoveryFederatedAdmissionPolicyRow(federated_admission_policy_id=nid('jrfap'),policy_key=policy_key,version_no=ver,environment=environment,cluster_scope=cluster_scope,state='ACTIVE',min_status_freshness_seconds=min_status_freshness_seconds,allowed_federation_ids_json=allowed_federation_ids,require_transparency_log=require_transparency_log,policy_json=policy or {},created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(p);self._append_log(s,'FEDERATED_ADMISSION_POLICY_ACTIVATED','ADMISSION_POLICY',p.federated_admission_policy_id,environment,{'policy_key':policy_key,'version_no':ver,'cluster_scope':cluster_scope,'allowed_federation_ids':allowed_federation_ids},f'policy://{policy_key}/v{ver}',actor);s.commit();return self.admission_policy(p.federated_admission_policy_id)
    def _policy(self,s,environment,cluster_id):
        rows=s.execute(select(JourneyRecoveryFederatedAdmissionPolicyRow).where(JourneyRecoveryFederatedAdmissionPolicyRow.environment==environment,JourneyRecoveryFederatedAdmissionPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryFederatedAdmissionPolicyRow.created_at.desc())).scalars().all()
        return next((p for p in rows if p.cluster_scope in {cluster_id,'*'}),None)
    def admission_allowed_in_session(self,s,runtime_identity_id,environment,cluster_id='default'):
        p=self._policy(s,environment,cluster_id)
        if not p:return True,[],None,None,None
        creds=s.execute(select(JourneyRecoveryCredentialIssuanceRow).where(JourneyRecoveryCredentialIssuanceRow.runtime_identity_id==runtime_identity_id,JourneyRecoveryCredentialIssuanceRow.environment==environment,JourneyRecoveryCredentialIssuanceRow.state=='ISSUED',JourneyRecoveryCredentialIssuanceRow.eligibility_state=='ELIGIBLE')).scalars().all()
        reasons=[]
        for cred in creds:
            issuer=s.get(JourneyRecoveryCredentialIssuerRow,cred.credential_issuer_id);root=s.get(JourneyRecoveryHardwareTrustRootRow,cred.hardware_trust_root_id)
            if not issuer or issuer.state!='ACTIVE': continue
            if not root or root.state!='ACTIVE': continue
            feds=s.execute(select(JourneyRecoveryTrustFederationRow).where(JourneyRecoveryTrustFederationRow.environment==environment,JourneyRecoveryTrustFederationRow.hardware_trust_root_id==cred.hardware_trust_root_id,JourneyRecoveryTrustFederationRow.state=='ACTIVE')).scalars().all()
            feds=[f for f in feds if f.cluster_scope in {cluster_id,'*'} and (not p.allowed_federation_ids_json or f.trust_federation_id in p.allowed_federation_ids_json)]
            if not feds: reasons.append('NO_ACTIVE_TRUST_FEDERATION');continue
            st=s.execute(select(JourneyRecoveryCredentialStatusDistributionRow).where(JourneyRecoveryCredentialStatusDistributionRow.credential_id==cred.credential_id,JourneyRecoveryCredentialStatusDistributionRow.publication_state=='PUBLISHED').order_by(JourneyRecoveryCredentialStatusDistributionRow.status_version.desc())).scalars().first()
            if not st: reasons.append('STATUS_NOT_PUBLISHED');continue
            age=(now()-aware(st.this_update_at)).total_seconds()
            if st.status!='GOOD': reasons.append('CREDENTIAL_STATUS_NOT_GOOD');continue
            if aware(st.next_update_at)<=now() or age>p.min_status_freshness_seconds: reasons.append('CREDENTIAL_STATUS_STALE');continue
            log=None
            if p.require_transparency_log:
                log=s.execute(select(JourneyRecoveryTrustTransparencyLogRow).where(JourneyRecoveryTrustTransparencyLogRow.subject_type=='CREDENTIAL',JourneyRecoveryTrustTransparencyLogRow.subject_id==cred.credential_id,JourneyRecoveryTrustTransparencyLogRow.event_type=='CREDENTIAL_STATUS_PUBLISHED').order_by(JourneyRecoveryTrustTransparencyLogRow.sequence_no.desc())).scalars().first()
                if not log: reasons.append('TRANSPARENCY_LOG_REQUIRED');continue
            return True,[],cred,st,log
        return False,sorted(set(reasons or ['NO_ELIGIBLE_CREDENTIAL'])),None,None,None
    def evaluate_admission(self,runtime_identity_id,environment,cluster_id,actor='runtime-admission-controller'):
        with SessionLocal() as s:
            p=self._policy(s,environment,cluster_id)
            if not p: return {'decision':'ALLOW_LEGACY_NO_3Z_POLICY','reason_codes':['NO_ACTIVE_3Z_POLICY'],'supplier_fact_unchanged':True}
            ok,reasons,cred,st,log=self.admission_allowed_in_session(s,runtime_identity_id,environment,cluster_id)
            d=JourneyRecoveryFederatedAdmissionDecisionRow(federated_admission_decision_id=nid('jrfad'),runtime_identity_id=runtime_identity_id,credential_id=cred.credential_id if cred else 'NONE',environment=environment,cluster_id=cluster_id,policy_id=p.federated_admission_policy_id,decision='ALLOW' if ok else 'DENY',reason_codes_json=reasons,status_distribution_id=st.credential_status_distribution_id if st else None,transparency_log_id=log.transparency_log_id if log else None,decided_by=actor,decided_at=now(),supplier_fact_unchanged=True);s.add(d);s.commit();return self.admission_decision(d.federated_admission_decision_id)
    def report_issuer_compromise(self,credential_issuer_id,severity,evidence_reference,actor,ttl_seconds=300):
        if severity not in {'SEV1','SEV2','SEV3','SEV4'}: raise ValueError('INVALID_SECURITY_INCIDENT_SEVERITY')
        with SessionLocal() as s:
            issuer=s.get(JourneyRecoveryCredentialIssuerRow,credential_issuer_id)
            if not issuer: raise ValueError('CREDENTIAL_ISSUER_NOT_FOUND')
            if issuer.state=='REVOKED': raise ValueError('CREDENTIAL_ISSUER_ALREADY_REVOKED')
            issuer.state='REVOKED';issuer.updated_at=now()
            creds=s.execute(select(JourneyRecoveryCredentialIssuanceRow).where(JourneyRecoveryCredentialIssuanceRow.credential_issuer_id==credential_issuer_id,JourneyRecoveryCredentialIssuanceRow.state=='ISSUED')).scalars().all();affected=[]
            for cred in creds:
                cred.state='REVOKED';cred.eligibility_state='REVOKED';cred.revoked_at=now();affected.append(cred.credential_id);lifecycle._invalidate(s,cred.environment,cred.runtime_identity_id,'ISSUER_COMPROMISE_FANOUT',actor)
                ver=(s.execute(select(func.max(JourneyRecoveryCredentialStatusDistributionRow.status_version)).where(JourneyRecoveryCredentialStatusDistributionRow.credential_id==cred.credential_id)).scalar() or 0)+1;t=now();payload={'credential_id':cred.credential_id,'status':'REVOKED','version':ver,'issuer_compromise':credential_issuer_id}
                st=JourneyRecoveryCredentialStatusDistributionRow(credential_status_distribution_id=nid('jrcsd'),credential_id=cred.credential_id,environment=cred.environment,status='REVOKED',status_version=ver,this_update_at=t,next_update_at=t+timedelta(seconds=ttl_seconds),issuer_id=cred.credential_issuer_id,root_id=cred.hardware_trust_root_id,status_hash=sha(payload),publication_state='PUBLISHED',evidence_reference=evidence_reference,published_by=actor,published_at=t,supplier_fact_unchanged=True);s.add(st);self._append_log(s,'ISSUER_COMPROMISE_CREDENTIAL_REVOKED','CREDENTIAL',cred.credential_id,cred.environment,payload,evidence_reference,actor)
            inc=JourneyRecoveryIssuerCompromiseRow(issuer_compromise_id=nid('jric'),credential_issuer_id=credential_issuer_id,environment=issuer.environment,severity=severity,state='OPEN',affected_credential_ids_json=affected,fanout_count=len(affected),evidence_reference=evidence_reference,opened_by=actor,opened_at=now(),contained_at=None,supplier_fact_unchanged=True);s.add(inc);self._append_log(s,'ISSUER_COMPROMISED','ISSUER',credential_issuer_id,issuer.environment,{'severity':severity,'affected_credentials':affected},evidence_reference,actor);s.commit();return self.issuer_compromise(inc.issuer_compromise_id)
    def public_credential_status(self,credential_id):
        with SessionLocal() as s:
            st=s.execute(select(JourneyRecoveryCredentialStatusDistributionRow).where(JourneyRecoveryCredentialStatusDistributionRow.credential_id==credential_id,JourneyRecoveryCredentialStatusDistributionRow.publication_state=='PUBLISHED').order_by(JourneyRecoveryCredentialStatusDistributionRow.status_version.desc())).scalars().first()
            if not st:return {'credential_id':credential_id,'status':'UNKNOWN','fresh':False,'supplier_fact_unchanged':True}
            return {'credential_id':credential_id,'status':st.status,'status_version':st.status_version,'this_update_at':aware(st.this_update_at).isoformat(),'next_update_at':aware(st.next_update_at).isoformat(),'fresh':aware(st.next_update_at)>now(),'status_hash':st.status_hash,'issuer_id':st.issuer_id,'root_id':st.root_id,'supplier_fact_unchanged':True}
    def transparency_checkpoint(self):
        with SessionLocal() as s:
            x=s.execute(select(JourneyRecoveryTrustTransparencyLogRow).order_by(JourneyRecoveryTrustTransparencyLogRow.sequence_no.desc())).scalars().first()
            return {'tree_size':x.sequence_no if x else 0,'root_entry_hash':x.entry_hash if x else None,'checkpoint_generated_at':now().isoformat(),'append_only':True,'supplier_fact_unchanged':True}
    def federation(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryTrustFederationRow,id)
            if not x:raise ValueError('TRUST_FEDERATION_NOT_FOUND')
            return {'trust_federation_id':x.trust_federation_id,'federation_key':x.federation_key,'environment':x.environment,'cluster_scope':x.cluster_scope,'hardware_trust_root_id':x.hardware_trust_root_id,'state':x.state,'peer_fingerprint':x.peer_fingerprint,'policy_version':x.policy_version,'last_synchronized_at':aware(x.last_synchronized_at).isoformat() if x.last_synchronized_at else None,'supplier_fact_unchanged':True}
    def status_distribution(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryCredentialStatusDistributionRow,id)
            if not x:raise ValueError('CREDENTIAL_STATUS_DISTRIBUTION_NOT_FOUND')
            return {'credential_status_distribution_id':x.credential_status_distribution_id,'credential_id':x.credential_id,'environment':x.environment,'status':x.status,'status_version':x.status_version,'this_update_at':aware(x.this_update_at).isoformat(),'next_update_at':aware(x.next_update_at).isoformat(),'issuer_id':x.issuer_id,'root_id':x.root_id,'status_hash':x.status_hash,'publication_state':x.publication_state,'supplier_fact_unchanged':True}
    def admission_policy(self,id):
        with SessionLocal() as s:
            p=s.get(JourneyRecoveryFederatedAdmissionPolicyRow,id)
            if not p:raise ValueError('FEDERATED_ADMISSION_POLICY_NOT_FOUND')
            return {'federated_admission_policy_id':p.federated_admission_policy_id,'policy_key':p.policy_key,'version_no':p.version_no,'environment':p.environment,'cluster_scope':p.cluster_scope,'state':p.state,'min_status_freshness_seconds':p.min_status_freshness_seconds,'allowed_federation_ids':p.allowed_federation_ids_json,'require_transparency_log':p.require_transparency_log,'policy':p.policy_json,'supplier_fact_unchanged':True}
    def admission_decision(self,id):
        with SessionLocal() as s:
            d=s.get(JourneyRecoveryFederatedAdmissionDecisionRow,id)
            if not d:raise ValueError('FEDERATED_ADMISSION_DECISION_NOT_FOUND')
            return {'federated_admission_decision_id':d.federated_admission_decision_id,'runtime_identity_id':d.runtime_identity_id,'credential_id':d.credential_id,'environment':d.environment,'cluster_id':d.cluster_id,'policy_id':d.policy_id,'decision':d.decision,'reason_codes':d.reason_codes_json,'status_distribution_id':d.status_distribution_id,'transparency_log_id':d.transparency_log_id,'decided_at':aware(d.decided_at).isoformat(),'supplier_fact_unchanged':True}
    def issuer_compromise(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryIssuerCompromiseRow,id)
            if not x:raise ValueError('ISSUER_COMPROMISE_NOT_FOUND')
            return {'issuer_compromise_id':x.issuer_compromise_id,'credential_issuer_id':x.credential_issuer_id,'environment':x.environment,'severity':x.severity,'state':x.state,'affected_credential_ids':x.affected_credential_ids_json,'fanout_count':x.fanout_count,'evidence_reference':x.evidence_reference,'opened_at':aware(x.opened_at).isoformat(),'supplier_fact_unchanged':True}
    def status(self,environment='PROD'):
        with SessionLocal() as s:
            f=s.execute(select(JourneyRecoveryTrustFederationRow).where(JourneyRecoveryTrustFederationRow.environment==environment).order_by(JourneyRecoveryTrustFederationRow.created_at.desc())).scalars().all();p=s.execute(select(JourneyRecoveryFederatedAdmissionPolicyRow).where(JourneyRecoveryFederatedAdmissionPolicyRow.environment==environment).order_by(JourneyRecoveryFederatedAdmissionPolicyRow.created_at.desc())).scalars().all();d=s.execute(select(JourneyRecoveryFederatedAdmissionDecisionRow).where(JourneyRecoveryFederatedAdmissionDecisionRow.environment==environment).order_by(JourneyRecoveryFederatedAdmissionDecisionRow.decided_at.desc())).scalars().all();i=s.execute(select(JourneyRecoveryIssuerCompromiseRow).where(JourneyRecoveryIssuerCompromiseRow.environment==environment).order_by(JourneyRecoveryIssuerCompromiseRow.opened_at.desc())).scalars().all()
            return {'environment':environment,'federations':[self.federation(x.trust_federation_id) for x in f[:20]],'admission_policies':[self.admission_policy(x.federated_admission_policy_id) for x in p[:20]],'recent_admission_decisions':[self.admission_decision(x.federated_admission_decision_id) for x in d[:30]],'issuer_compromises':[self.issuer_compromise(x.issuer_compromise_id) for x in i[:20]],'transparency_checkpoint':self.transparency_checkpoint(),'supplier_fact_unchanged':True}

recovery_federated_trust_service=RecoveryFederatedTrustService()
