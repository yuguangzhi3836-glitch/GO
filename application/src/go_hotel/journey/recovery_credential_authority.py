from datetime import datetime, timezone
from uuid import uuid4
import hashlib, json
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryRuntimeIdentityRow,
    JourneyRecoveryRuntimeAttestationEvidenceRow,
    JourneyRecoveryIdentityReissuanceRequestRow,
    JourneyRecoveryHardwareTrustRootRow,
    JourneyRecoveryCredentialIssuerRow,
    JourneyRecoveryAttestationPolicyRow,
    JourneyRecoveryCredentialIssuanceRow,
    JourneyRecoveryAttestationVerificationRow,
    JourneyRecoveryCredentialLineageRow,
    JourneyRecoveryRevocationSyncRow,
)
from go_hotel.journey.recovery_runtime_identity_lifecycle import recovery_runtime_identity_lifecycle_service as lifecycle
from go_hotel.journey.recovery_runtime_telemetry_trust import aware

TRUST_CLASS={'ENGINEERING':1,'SOFTWARE_BOUND':2,'CLOUD_ATTESTED':3,'HARDWARE_BACKED':4,'HIGH_ASSURANCE':5}

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def sha(v): return hashlib.sha256(canon(v).encode()).hexdigest()

class RecoveryCredentialAuthorityService:
    def register_trust_root(self,root_key,provider,trust_class,root_fingerprint,actor,metadata=None,valid_until=None):
        if trust_class not in TRUST_CLASS: raise ValueError('INVALID_HARDWARE_TRUST_CLASS')
        with SessionLocal() as s:
            if s.execute(select(JourneyRecoveryHardwareTrustRootRow).where(JourneyRecoveryHardwareTrustRootRow.root_key==root_key)).scalars().first(): raise ValueError('HARDWARE_TRUST_ROOT_EXISTS')
            r=JourneyRecoveryHardwareTrustRootRow(hardware_trust_root_id=nid('jrhtr'),root_key=root_key,provider=provider,trust_class=trust_class,state='ACTIVE',root_fingerprint=root_fingerprint,valid_from=now(),valid_until=valid_until,metadata_json=metadata or {},created_by=actor,created_at=now(),updated_at=now(),supplier_fact_unchanged=True);s.add(r);s.commit();return self.trust_root(r.hardware_trust_root_id)
    def register_issuer(self,issuer_key,issuer_type,environment,hardware_trust_root_id,verification_key_ref,actor):
        if environment not in {'DEV','STAGING','PROD'}: raise ValueError('INVALID_ENVIRONMENT')
        with SessionLocal() as s:
            root=s.get(JourneyRecoveryHardwareTrustRootRow,hardware_trust_root_id)
            if not root or root.state!='ACTIVE': raise ValueError('ACTIVE_HARDWARE_TRUST_ROOT_REQUIRED')
            if s.execute(select(JourneyRecoveryCredentialIssuerRow).where(JourneyRecoveryCredentialIssuerRow.issuer_key==issuer_key)).scalars().first(): raise ValueError('CREDENTIAL_ISSUER_EXISTS')
            fp=sha({'issuer_key':issuer_key,'issuer_type':issuer_type,'environment':environment,'root':root.root_fingerprint,'verification_key_ref':verification_key_ref})
            x=JourneyRecoveryCredentialIssuerRow(credential_issuer_id=nid('jrci'),issuer_key=issuer_key,issuer_type=issuer_type,environment=environment,hardware_trust_root_id=hardware_trust_root_id,state='ACTIVE',issuer_fingerprint=fp,verification_key_ref=verification_key_ref,created_by=actor,created_at=now(),updated_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.issuer(x.credential_issuer_id)
    def create_policy(self,policy_key,environment,identity_type,min_trust_class,allowed_attestation_types,min_verifier_quorum,allowed_issuer_ids,actor,policy=None):
        if environment not in {'DEV','STAGING','PROD'}: raise ValueError('INVALID_ENVIRONMENT')
        if identity_type not in {'WORKLOAD','COLLECTOR','ANY'}: raise ValueError('INVALID_POLICY_IDENTITY_TYPE')
        if min_trust_class not in TRUST_CLASS: raise ValueError('INVALID_HARDWARE_TRUST_CLASS')
        if min_verifier_quorum<1: raise ValueError('INVALID_VERIFIER_QUORUM')
        with SessionLocal() as s:
            ver=(s.execute(select(func.max(JourneyRecoveryAttestationPolicyRow.version_no)).where(JourneyRecoveryAttestationPolicyRow.policy_key==policy_key)).scalar() or 0)+1
            for iid in allowed_issuer_ids:
                issuer=s.get(JourneyRecoveryCredentialIssuerRow,iid)
                if not issuer or issuer.state!='ACTIVE' or issuer.environment!=environment: raise ValueError('POLICY_ISSUER_NOT_ACTIVE_FOR_ENVIRONMENT')
            p=JourneyRecoveryAttestationPolicyRow(attestation_policy_id=nid('jrap'),policy_key=policy_key,version_no=ver,environment=environment,identity_type=identity_type,state='ACTIVE',min_trust_class=min_trust_class,allowed_attestation_types_json=allowed_attestation_types,allowed_issuer_ids_json=allowed_issuer_ids,min_verifier_quorum=min_verifier_quorum,policy_json=policy or {},created_by=actor,created_at=now(),activated_at=now(),supplier_fact_unchanged=True);s.add(p);s.commit();return self.policy(p.attestation_policy_id)
    def request_issuance(self,runtime_identity_id,attestation_policy_id,credential_issuer_id,runtime_attestation_evidence_id,actor,predecessor_credential_id=None):
        with SessionLocal() as s:
            ident=s.get(JourneyRecoveryRuntimeIdentityRow,runtime_identity_id);pol=s.get(JourneyRecoveryAttestationPolicyRow,attestation_policy_id);issuer=s.get(JourneyRecoveryCredentialIssuerRow,credential_issuer_id);e=s.get(JourneyRecoveryRuntimeAttestationEvidenceRow,runtime_attestation_evidence_id)
            if not ident or ident.state!='ACTIVE': raise ValueError('ACTIVE_RUNTIME_IDENTITY_REQUIRED')
            if not pol or pol.state!='ACTIVE': raise ValueError('ACTIVE_ATTESTATION_POLICY_REQUIRED')
            if ident.environment!=pol.environment: raise ValueError('IDENTITY_POLICY_ENVIRONMENT_MISMATCH')
            if pol.identity_type not in {'ANY',ident.identity_type}: raise ValueError('IDENTITY_TYPE_NOT_ALLOWED_BY_POLICY')
            if not issuer or issuer.state!='ACTIVE' or issuer.environment!=ident.environment: raise ValueError('ACTIVE_CREDENTIAL_ISSUER_REQUIRED')
            if pol.allowed_issuer_ids_json and issuer.credential_issuer_id not in pol.allowed_issuer_ids_json: raise ValueError('ISSUER_NOT_ALLOWED_BY_POLICY')
            root=s.get(JourneyRecoveryHardwareTrustRootRow,issuer.hardware_trust_root_id)
            if not root or root.state!='ACTIVE': raise ValueError('ACTIVE_HARDWARE_TRUST_ROOT_REQUIRED')
            if TRUST_CLASS[root.trust_class]<TRUST_CLASS[pol.min_trust_class]: raise ValueError('HARDWARE_TRUST_CLASS_BELOW_POLICY')
            if not e or e.verification_state!='VERIFIED': raise ValueError('VERIFIED_RUNTIME_ATTESTATION_REQUIRED')
            if e.attestation_type not in pol.allowed_attestation_types_json: raise ValueError('ATTESTATION_TYPE_NOT_ALLOWED_BY_POLICY')
            req=s.get(JourneyRecoveryIdentityReissuanceRequestRow,e.identity_reissuance_request_id)
            if not req or req.replacement_identity_id!=runtime_identity_id: raise ValueError('ATTESTATION_NOT_BOUND_TO_RUNTIME_IDENTITY')
            existing=s.execute(select(JourneyRecoveryCredentialIssuanceRow).where(JourneyRecoveryCredentialIssuanceRow.runtime_identity_id==runtime_identity_id,JourneyRecoveryCredentialIssuanceRow.state.in_(['PENDING_VERIFICATION','VERIFIED','ISSUED']))).scalars().first()
            if existing: raise ValueError('CREDENTIAL_ISSUANCE_ALREADY_OPEN_OR_ACTIVE')
            x=JourneyRecoveryCredentialIssuanceRow(credential_issuance_id=nid('jrciu'),runtime_identity_id=runtime_identity_id,attestation_policy_id=attestation_policy_id,credential_issuer_id=credential_issuer_id,hardware_trust_root_id=root.hardware_trust_root_id,runtime_attestation_evidence_id=runtime_attestation_evidence_id,environment=ident.environment,state='PENDING_VERIFICATION',credential_id=None,credential_fingerprint=None,eligibility_state='NOT_YET_ELIGIBLE',predecessor_credential_id=predecessor_credential_id,requested_by=actor,requested_at=now(),issued_by=None,issued_at=None,revoked_at=None,supplier_fact_unchanged=True);s.add(x);s.commit();return self.issuance(x.credential_issuance_id)
    def verify(self,credential_issuance_id,verifier_id,verdict,evidence_reference,actor='verifier'):
        if verdict not in {'PASS','FAIL'}: raise ValueError('INVALID_ATTESTATION_VERDICT')
        if not evidence_reference: raise ValueError('VERIFICATION_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryCredentialIssuanceRow,credential_issuance_id)
            if not x: raise ValueError('CREDENTIAL_ISSUANCE_NOT_FOUND')
            if x.state not in {'PENDING_VERIFICATION','VERIFIED'}: raise ValueError('CREDENTIAL_ISSUANCE_NOT_VERIFIABLE')
            if s.execute(select(JourneyRecoveryAttestationVerificationRow).where(JourneyRecoveryAttestationVerificationRow.credential_issuance_id==credential_issuance_id,JourneyRecoveryAttestationVerificationRow.verifier_id==verifier_id)).scalars().first(): raise ValueError('VERIFIER_ALREADY_RECORDED')
            h=sha({'issuance':credential_issuance_id,'verifier_id':verifier_id,'verdict':verdict,'evidence_reference':evidence_reference})
            v=JourneyRecoveryAttestationVerificationRow(attestation_verification_id=nid('jrav'),credential_issuance_id=credential_issuance_id,verifier_id=verifier_id,verdict=verdict,evidence_reference=evidence_reference,verification_hash=h,verified_at=now(),supplier_fact_unchanged=True);s.add(v);s.flush()
            if verdict=='FAIL': x.state='REJECTED';x.eligibility_state='REJECTED'
            else:
                pol=s.get(JourneyRecoveryAttestationPolicyRow,x.attestation_policy_id)
                passed=s.execute(select(JourneyRecoveryAttestationVerificationRow).where(JourneyRecoveryAttestationVerificationRow.credential_issuance_id==credential_issuance_id,JourneyRecoveryAttestationVerificationRow.verdict=='PASS')).scalars().all()
                if len({p.verifier_id for p in passed})>=pol.min_verifier_quorum: x.state='VERIFIED'
            s.commit();return {'verification':self.verification(v.attestation_verification_id),'issuance':self.issuance(credential_issuance_id),'supplier_fact_unchanged':True}
    def issue(self,credential_issuance_id,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryCredentialIssuanceRow,credential_issuance_id)
            if not x: raise ValueError('CREDENTIAL_ISSUANCE_NOT_FOUND')
            if x.state!='VERIFIED': raise ValueError('VERIFIER_QUORUM_REQUIRED')
            pol=s.get(JourneyRecoveryAttestationPolicyRow,x.attestation_policy_id);issuer=s.get(JourneyRecoveryCredentialIssuerRow,x.credential_issuer_id);root=s.get(JourneyRecoveryHardwareTrustRootRow,x.hardware_trust_root_id);ident=s.get(JourneyRecoveryRuntimeIdentityRow,x.runtime_identity_id)
            if not pol or pol.state!='ACTIVE': raise ValueError('ATTESTATION_POLICY_NO_LONGER_ACTIVE')
            if not issuer or issuer.state!='ACTIVE': raise ValueError('CREDENTIAL_ISSUER_NO_LONGER_ACTIVE')
            if not root or root.state!='ACTIVE': raise ValueError('TRUST_ROOT_NO_LONGER_ACTIVE')
            if not ident or ident.state!='ACTIVE': raise ValueError('RUNTIME_IDENTITY_NOT_ACTIVE')
            cid=f'go-cred-{uuid4().hex}'
            fp=sha({'credential_id':cid,'runtime_identity_id':ident.runtime_identity_id,'issuer_fingerprint':issuer.issuer_fingerprint,'root_fingerprint':root.root_fingerprint,'policy':pol.attestation_policy_id,'attestation':x.runtime_attestation_evidence_id})
            x.credential_id=cid;x.credential_fingerprint=fp;x.state='ISSUED';x.eligibility_state='ELIGIBLE';x.issued_by=actor;x.issued_at=now()
            lp={'issuance':x.credential_issuance_id,'runtime_identity_id':x.runtime_identity_id,'predecessor_credential_id':x.predecessor_credential_id,'credential_id':cid,'credential_fingerprint':fp}
            line=JourneyRecoveryCredentialLineageRow(credential_lineage_id=nid('jrcl'),credential_issuance_id=x.credential_issuance_id,runtime_identity_id=x.runtime_identity_id,predecessor_credential_id=x.predecessor_credential_id,credential_id=cid,lineage_hash=sha(lp),created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(line);lifecycle._invalidate(s,x.environment,x.runtime_identity_id,'CREDENTIAL_ISSUED',actor);s.commit();return {'issuance':self.issuance(credential_issuance_id),'lineage':self.lineage(line.credential_lineage_id),'supplier_fact_unchanged':True}
    def sync_revocations(self,authority_type,authority_id,environment,revocation_version,revoked_credential_ids,evidence_reference,actor,revoke_authority=False):
        if authority_type not in {'ISSUER','TRUST_ROOT'}: raise ValueError('INVALID_REVOCATION_AUTHORITY_TYPE')
        if not evidence_reference: raise ValueError('REVOCATION_SYNC_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            if s.execute(select(JourneyRecoveryRevocationSyncRow).where(JourneyRecoveryRevocationSyncRow.authority_type==authority_type,JourneyRecoveryRevocationSyncRow.authority_id==authority_id,JourneyRecoveryRevocationSyncRow.revocation_version==revocation_version)).scalars().first(): raise ValueError('REVOCATION_VERSION_ALREADY_SYNCED')
            if authority_type=='ISSUER': auth=s.get(JourneyRecoveryCredentialIssuerRow,authority_id)
            else: auth=s.get(JourneyRecoveryHardwareTrustRootRow,authority_id)
            if not auth: raise ValueError('REVOCATION_AUTHORITY_NOT_FOUND')
            q=select(JourneyRecoveryCredentialIssuanceRow).where(JourneyRecoveryCredentialIssuanceRow.environment==environment,JourneyRecoveryCredentialIssuanceRow.state=='ISSUED')
            q=q.where(JourneyRecoveryCredentialIssuanceRow.credential_issuer_id==authority_id) if authority_type=='ISSUER' else q.where(JourneyRecoveryCredentialIssuanceRow.hardware_trust_root_id==authority_id)
            rows=s.execute(q).scalars().all();targets=[]
            for x in rows:
                if revoke_authority or x.credential_id in revoked_credential_ids:
                    x.state='REVOKED';x.eligibility_state='REVOKED';x.revoked_at=now();targets.append(x.credential_id);lifecycle._invalidate(s,environment,x.runtime_identity_id,f'{authority_type}_REVOCATION_SYNC',actor)
            if revoke_authority:
                auth.state='REVOKED';auth.updated_at=now()
            r=JourneyRecoveryRevocationSyncRow(revocation_sync_id=nid('jrrs'),authority_type=authority_type,authority_id=authority_id,environment=environment,revocation_version=revocation_version,revoked_credential_ids_json=targets,propagation_state='PROPAGATED',evidence_reference=evidence_reference,synchronized_by=actor,synchronized_at=now(),supplier_fact_unchanged=True);s.add(r);s.commit();return self.revocation_sync(r.revocation_sync_id)
    def has_active_policy(self,s,environment):
        return s.execute(select(JourneyRecoveryAttestationPolicyRow).where(JourneyRecoveryAttestationPolicyRow.environment==environment,JourneyRecoveryAttestationPolicyRow.state=='ACTIVE')).scalars().first() is not None
    def identity_is_eligible(self,s,runtime_identity_id,environment):
        if not self.has_active_policy(s,environment): return True
        rows=s.execute(select(JourneyRecoveryCredentialIssuanceRow).where(JourneyRecoveryCredentialIssuanceRow.runtime_identity_id==runtime_identity_id,JourneyRecoveryCredentialIssuanceRow.environment==environment,JourneyRecoveryCredentialIssuanceRow.state=='ISSUED',JourneyRecoveryCredentialIssuanceRow.eligibility_state=='ELIGIBLE')).scalars().all()
        for x in rows:
            pol=s.get(JourneyRecoveryAttestationPolicyRow,x.attestation_policy_id);issuer=s.get(JourneyRecoveryCredentialIssuerRow,x.credential_issuer_id);root=s.get(JourneyRecoveryHardwareTrustRootRow,x.hardware_trust_root_id)
            if pol and pol.state=='ACTIVE' and issuer and issuer.state=='ACTIVE' and root and root.state=='ACTIVE': return True
        return False
    def trust_root(self,id):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryHardwareTrustRootRow,id)
            if not r: raise ValueError('HARDWARE_TRUST_ROOT_NOT_FOUND')
            return {'hardware_trust_root_id':r.hardware_trust_root_id,'root_key':r.root_key,'provider':r.provider,'trust_class':r.trust_class,'state':r.state,'root_fingerprint':r.root_fingerprint,'valid_from':aware(r.valid_from).isoformat(),'valid_until':aware(r.valid_until).isoformat() if r.valid_until else None,'metadata':r.metadata_json,'supplier_fact_unchanged':True}
    def issuer(self,id):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryCredentialIssuerRow,id)
            if not r: raise ValueError('CREDENTIAL_ISSUER_NOT_FOUND')
            return {'credential_issuer_id':r.credential_issuer_id,'issuer_key':r.issuer_key,'issuer_type':r.issuer_type,'environment':r.environment,'hardware_trust_root_id':r.hardware_trust_root_id,'state':r.state,'issuer_fingerprint':r.issuer_fingerprint,'verification_key_ref':r.verification_key_ref,'supplier_fact_unchanged':True}
    def policy(self,id):
        with SessionLocal() as s:
            p=s.get(JourneyRecoveryAttestationPolicyRow,id)
            if not p: raise ValueError('ATTESTATION_POLICY_NOT_FOUND')
            return {'attestation_policy_id':p.attestation_policy_id,'policy_key':p.policy_key,'version_no':p.version_no,'environment':p.environment,'identity_type':p.identity_type,'state':p.state,'min_trust_class':p.min_trust_class,'allowed_attestation_types':p.allowed_attestation_types_json,'allowed_issuer_ids':p.allowed_issuer_ids_json,'min_verifier_quorum':p.min_verifier_quorum,'policy':p.policy_json,'supplier_fact_unchanged':True}
    def issuance(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryCredentialIssuanceRow,id)
            if not x: raise ValueError('CREDENTIAL_ISSUANCE_NOT_FOUND')
            return {'credential_issuance_id':x.credential_issuance_id,'runtime_identity_id':x.runtime_identity_id,'attestation_policy_id':x.attestation_policy_id,'credential_issuer_id':x.credential_issuer_id,'hardware_trust_root_id':x.hardware_trust_root_id,'runtime_attestation_evidence_id':x.runtime_attestation_evidence_id,'environment':x.environment,'state':x.state,'credential_id':x.credential_id,'credential_fingerprint':x.credential_fingerprint,'eligibility_state':x.eligibility_state,'predecessor_credential_id':x.predecessor_credential_id,'requested_by':x.requested_by,'requested_at':aware(x.requested_at).isoformat(),'issued_by':x.issued_by,'issued_at':aware(x.issued_at).isoformat() if x.issued_at else None,'revoked_at':aware(x.revoked_at).isoformat() if x.revoked_at else None,'supplier_fact_unchanged':True}
    def verification(self,id):
        with SessionLocal() as s:
            v=s.get(JourneyRecoveryAttestationVerificationRow,id)
            if not v: raise ValueError('ATTESTATION_VERIFICATION_NOT_FOUND')
            return {'attestation_verification_id':v.attestation_verification_id,'credential_issuance_id':v.credential_issuance_id,'verifier_id':v.verifier_id,'verdict':v.verdict,'evidence_reference':v.evidence_reference,'verification_hash':v.verification_hash,'verified_at':aware(v.verified_at).isoformat(),'supplier_fact_unchanged':True}
    def lineage(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryCredentialLineageRow,id)
            if not x: raise ValueError('CREDENTIAL_LINEAGE_NOT_FOUND')
            return {'credential_lineage_id':x.credential_lineage_id,'credential_issuance_id':x.credential_issuance_id,'runtime_identity_id':x.runtime_identity_id,'predecessor_credential_id':x.predecessor_credential_id,'credential_id':x.credential_id,'lineage_hash':x.lineage_hash,'created_by':x.created_by,'created_at':aware(x.created_at).isoformat(),'supplier_fact_unchanged':True}
    def revocation_sync(self,id):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryRevocationSyncRow,id)
            if not r: raise ValueError('REVOCATION_SYNC_NOT_FOUND')
            return {'revocation_sync_id':r.revocation_sync_id,'authority_type':r.authority_type,'authority_id':r.authority_id,'environment':r.environment,'revocation_version':r.revocation_version,'revoked_credential_ids':r.revoked_credential_ids_json,'propagation_state':r.propagation_state,'evidence_reference':r.evidence_reference,'synchronized_by':r.synchronized_by,'synchronized_at':aware(r.synchronized_at).isoformat(),'supplier_fact_unchanged':True}
    def status(self,environment='PROD'):
        with SessionLocal() as s:
            roots=s.execute(select(JourneyRecoveryHardwareTrustRootRow).order_by(JourneyRecoveryHardwareTrustRootRow.created_at.desc())).scalars().all();issuers=s.execute(select(JourneyRecoveryCredentialIssuerRow).where(JourneyRecoveryCredentialIssuerRow.environment==environment).order_by(JourneyRecoveryCredentialIssuerRow.created_at.desc())).scalars().all();pols=s.execute(select(JourneyRecoveryAttestationPolicyRow).where(JourneyRecoveryAttestationPolicyRow.environment==environment).order_by(JourneyRecoveryAttestationPolicyRow.created_at.desc())).scalars().all();creds=s.execute(select(JourneyRecoveryCredentialIssuanceRow).where(JourneyRecoveryCredentialIssuanceRow.environment==environment).order_by(JourneyRecoveryCredentialIssuanceRow.requested_at.desc())).scalars().all();syncs=s.execute(select(JourneyRecoveryRevocationSyncRow).where(JourneyRecoveryRevocationSyncRow.environment==environment).order_by(JourneyRecoveryRevocationSyncRow.synchronized_at.desc())).scalars().all()
            return {'environment':environment,'trust_roots':[self.trust_root(x.hardware_trust_root_id) for x in roots[:20]],'issuers':[self.issuer(x.credential_issuer_id) for x in issuers[:20]],'policies':[self.policy(x.attestation_policy_id) for x in pols[:20]],'credential_issuances':[self.issuance(x.credential_issuance_id) for x in creds[:30]],'revocation_syncs':[self.revocation_sync(x.revocation_sync_id) for x in syncs[:20]],'supplier_fact_unchanged':True}

recovery_credential_authority_service=RecoveryCredentialAuthorityService()
