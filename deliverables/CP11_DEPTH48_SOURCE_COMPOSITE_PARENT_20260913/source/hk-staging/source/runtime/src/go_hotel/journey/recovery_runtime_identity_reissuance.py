from datetime import datetime, timezone
from uuid import uuid4
import hashlib,hmac,json,os,re
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryRuntimeIdentityRow,JourneyRecoveryTelemetrySecurityIncidentRow,
    JourneyRecoveryIdentityReissuanceRequestRow,JourneyRecoveryRuntimeAttestationEvidenceRow,
    JourneyRecoveryRuntimeIdentityLineageRow,JourneyRecoveryRevokedIdentityTombstoneRow,
)
from go_hotel.journey.recovery_runtime_telemetry_trust import recovery_runtime_telemetry_trust_service as trust, aware
from go_hotel.journey.recovery_runtime_identity_lifecycle import recovery_runtime_identity_lifecycle_service as lifecycle

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def sha(v): return hashlib.sha256(canon(v).encode()).hexdigest()
def attestation_env_key(ref): return 'GO_RUNTIME_ATTESTATION_KEY_'+re.sub(r'[^A-Z0-9]','_',ref.upper())

class RecoveryRuntimeIdentityReissuanceService:
    def request(self,predecessor_identity_id,replacement_identity_key,replacement_subject_ref,replacement_key_ref,attestation_key_ref,reason_code,evidence_reference,actor,break_glass=False):
        if not evidence_reference: raise ValueError('REISSUANCE_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            old=s.get(JourneyRecoveryRuntimeIdentityRow,predecessor_identity_id)
            if not old: raise ValueError('RUNTIME_IDENTITY_NOT_FOUND')
            if old.state!='REVOKED': raise ValueError('ONLY_REVOKED_IDENTITY_CAN_BE_REISSUED')
            if s.execute(select(JourneyRecoveryIdentityReissuanceRequestRow).where(JourneyRecoveryIdentityReissuanceRequestRow.predecessor_identity_id==predecessor_identity_id,JourneyRecoveryIdentityReissuanceRequestRow.state.in_(['REQUESTED','ATTESTED','APPROVED']))).scalars().first(): raise ValueError('IDENTITY_REISSUANCE_ALREADY_OPEN')
            if s.execute(select(JourneyRecoveryRuntimeIdentityRow).where(JourneyRecoveryRuntimeIdentityRow.identity_key==replacement_identity_key)).scalars().first(): raise ValueError('RUNTIME_IDENTITY_KEY_EXISTS')
            r=JourneyRecoveryIdentityReissuanceRequestRow(identity_reissuance_request_id=nid('jrirr'),predecessor_identity_id=old.runtime_identity_id,replacement_identity_id=None,environment=old.environment,identity_type=old.identity_type,replacement_identity_key=replacement_identity_key,replacement_subject_ref=replacement_subject_ref,replacement_key_ref=replacement_key_ref,state='REQUESTED',break_glass=bool(break_glass),reason_code=reason_code,request_evidence_reference=evidence_reference,attestation_key_ref=attestation_key_ref,requested_by=actor,approved_by=None,approval_evidence_reference=None,requested_at=now(),approved_at=None,issued_at=None,supplier_fact_unchanged=True);s.add(r);s.commit();return self.get(r.identity_reissuance_request_id)
    def attestation_message(self,request_id,attestation_type,challenge_nonce,workload_measurement,evidence_reference):
        return canon({'identity_reissuance_request_id':request_id,'attestation_type':attestation_type,'challenge_nonce':challenge_nonce,'workload_measurement':workload_measurement,'evidence_reference':evidence_reference})
    def sign_attestation_for_engineering(self,attestation_key_ref,**kwargs):
        key=os.getenv(attestation_env_key(attestation_key_ref))
        if not key: raise ValueError('ATTESTATION_KEY_UNAVAILABLE')
        return hmac.new(key.encode(),self.attestation_message(**kwargs).encode(),hashlib.sha256).hexdigest()
    def submit_attestation(self,request_id,attestation_type,challenge_nonce,workload_measurement,evidence_reference,attestation_signature,actor):
        if attestation_type not in {'TPM','TEE','CLOUD_WORKLOAD','ENGINEERING'}: raise ValueError('INVALID_ATTESTATION_TYPE')
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryIdentityReissuanceRequestRow,request_id)
            if not r: raise ValueError('IDENTITY_REISSUANCE_REQUEST_NOT_FOUND')
            if r.state not in {'REQUESTED','ATTESTED'}: raise ValueError('IDENTITY_REISSUANCE_NOT_ATTESTABLE')
            if s.execute(select(JourneyRecoveryRuntimeAttestationEvidenceRow).where(JourneyRecoveryRuntimeAttestationEvidenceRow.challenge_nonce==challenge_nonce)).scalars().first(): raise ValueError('ATTESTATION_REPLAY_DETECTED')
            msg=self.attestation_message(request_id,attestation_type,challenge_nonce,workload_measurement,evidence_reference)
            key=os.getenv(attestation_env_key(r.attestation_key_ref))
            if not key: raise ValueError('ATTESTATION_KEY_UNAVAILABLE')
            expected=hmac.new(key.encode(),msg.encode(),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected,attestation_signature): raise ValueError('ATTESTATION_SIGNATURE_INVALID')
            e=JourneyRecoveryRuntimeAttestationEvidenceRow(runtime_attestation_evidence_id=nid('jrrae'),identity_reissuance_request_id=request_id,predecessor_identity_id=r.predecessor_identity_id,environment=r.environment,attestation_type=attestation_type,challenge_nonce=challenge_nonce,workload_measurement=workload_measurement,evidence_reference=evidence_reference,evidence_hash=hashlib.sha256(msg.encode()).hexdigest(),attestation_signature=attestation_signature,verification_state='VERIFIED',verification_json={'signature':'HMAC_SHA256_ENGINEERING_ATTESTATION','challenge_bound':True,'identity_reissuance_bound':True,'environment':r.environment},verified_by=actor,verified_at=now(),supplier_fact_unchanged=True);s.add(e);r.state='ATTESTED';s.commit();return {'attestation':self.attestation(e.runtime_attestation_evidence_id),'request':self.get(request_id)}
    def approve(self,request_id,approval_evidence_reference,actor):
        if not approval_evidence_reference: raise ValueError('REISSUANCE_APPROVAL_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryIdentityReissuanceRequestRow,request_id)
            if not r: raise ValueError('IDENTITY_REISSUANCE_REQUEST_NOT_FOUND')
            if r.state!='ATTESTED': raise ValueError('VERIFIED_ATTESTATION_REQUIRED')
            if r.requested_by==actor: raise ValueError('MAKER_CHECKER_APPROVER_MUST_DIFFER')
            if r.break_glass and not approval_evidence_reference.startswith('breakglass://'): raise ValueError('BREAK_GLASS_APPROVAL_EVIDENCE_REQUIRED')
            r.state='APPROVED';r.approved_by=actor;r.approval_evidence_reference=approval_evidence_reference;r.approved_at=now();s.commit();return self.get(request_id)
    def issue(self,request_id,actor):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryIdentityReissuanceRequestRow,request_id)
            if not r: raise ValueError('IDENTITY_REISSUANCE_REQUEST_NOT_FOUND')
            if r.state!='APPROVED': raise ValueError('IDENTITY_REISSUANCE_NOT_APPROVED')
            old=s.get(JourneyRecoveryRuntimeIdentityRow,r.predecessor_identity_id)
            if not old or old.state!='REVOKED': raise ValueError('PREDECESSOR_IDENTITY_NOT_TERMINALLY_REVOKED')
            incident=s.execute(select(JourneyRecoveryTelemetrySecurityIncidentRow).where(JourneyRecoveryTelemetrySecurityIncidentRow.runtime_identity_id==old.runtime_identity_id,JourneyRecoveryTelemetrySecurityIncidentRow.state=='OPEN')).scalars().first()
            if incident: raise ValueError('SECURITY_INCIDENT_MUST_BE_CONTAINED_BEFORE_REISSUANCE')
        new=trust.register_identity(r.replacement_identity_key,r.identity_type,r.environment,r.replacement_subject_ref,r.replacement_key_ref,actor)
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryIdentityReissuanceRequestRow,request_id);old=s.get(JourneyRecoveryRuntimeIdentityRow,r.predecessor_identity_id)
            if old.state!='REVOKED': raise ValueError('PREDECESSOR_IDENTITY_NOT_TERMINALLY_REVOKED')
            line_payload={'predecessor_identity_id':old.runtime_identity_id,'replacement_identity_id':new['runtime_identity_id'],'request_id':request_id,'environment':r.environment,'predecessor_fingerprint':old.identity_fingerprint,'replacement_fingerprint':new['identity_fingerprint']}
            line=JourneyRecoveryRuntimeIdentityLineageRow(runtime_identity_lineage_id=nid('jrril'),predecessor_identity_id=old.runtime_identity_id,replacement_identity_id=new['runtime_identity_id'],identity_reissuance_request_id=request_id,environment=r.environment,lineage_hash=sha(line_payload),created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(line)
            tomb=s.execute(select(JourneyRecoveryRevokedIdentityTombstoneRow).where(JourneyRecoveryRevokedIdentityTombstoneRow.runtime_identity_id==old.runtime_identity_id)).scalars().first()
            if not tomb:
                tomb_payload={'runtime_identity_id':old.runtime_identity_id,'environment':old.environment,'identity_fingerprint':old.identity_fingerprint,'terminal_state':'REVOKED','reason_code':r.reason_code,'evidence_reference':r.request_evidence_reference,'replacement_identity_id':new['runtime_identity_id']}
                tomb=JourneyRecoveryRevokedIdentityTombstoneRow(revoked_identity_tombstone_id=nid('jrrit'),runtime_identity_id=old.runtime_identity_id,environment=old.environment,identity_fingerprint=old.identity_fingerprint,terminal_state='REVOKED',reason_code=r.reason_code,evidence_reference=r.request_evidence_reference,tombstone_hash=sha(tomb_payload),replacement_identity_id=new['runtime_identity_id'],created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(tomb)
            r.replacement_identity_id=new['runtime_identity_id'];r.state='ISSUED';r.issued_at=now();lifecycle._invalidate(s,r.environment,new['runtime_identity_id'],'IDENTITY_REISSUED',actor);s.commit()
            return {'request':self.get(request_id),'replacement_identity':new,'lineage':self.lineage(line.runtime_identity_lineage_id),'tombstone':self.tombstone(tomb.revoked_identity_tombstone_id),'supplier_fact_unchanged':True}
    def get(self,id):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryIdentityReissuanceRequestRow,id)
            if not r: raise ValueError('IDENTITY_REISSUANCE_REQUEST_NOT_FOUND')
            return {'identity_reissuance_request_id':r.identity_reissuance_request_id,'predecessor_identity_id':r.predecessor_identity_id,'replacement_identity_id':r.replacement_identity_id,'environment':r.environment,'identity_type':r.identity_type,'replacement_identity_key':r.replacement_identity_key,'replacement_subject_ref':r.replacement_subject_ref,'replacement_key_ref':r.replacement_key_ref,'state':r.state,'break_glass':r.break_glass,'reason_code':r.reason_code,'request_evidence_reference':r.request_evidence_reference,'attestation_key_ref':r.attestation_key_ref,'requested_by':r.requested_by,'approved_by':r.approved_by,'approval_evidence_reference':r.approval_evidence_reference,'requested_at':aware(r.requested_at).isoformat(),'approved_at':aware(r.approved_at).isoformat() if r.approved_at else None,'issued_at':aware(r.issued_at).isoformat() if r.issued_at else None,'supplier_fact_unchanged':True}
    def attestation(self,id):
        with SessionLocal() as s:
            e=s.get(JourneyRecoveryRuntimeAttestationEvidenceRow,id)
            if not e: raise ValueError('RUNTIME_ATTESTATION_EVIDENCE_NOT_FOUND')
            return {'runtime_attestation_evidence_id':e.runtime_attestation_evidence_id,'identity_reissuance_request_id':e.identity_reissuance_request_id,'attestation_type':e.attestation_type,'challenge_nonce':e.challenge_nonce,'workload_measurement':e.workload_measurement,'evidence_reference':e.evidence_reference,'evidence_hash':e.evidence_hash,'verification_state':e.verification_state,'verification':e.verification_json,'verified_by':e.verified_by,'verified_at':aware(e.verified_at).isoformat(),'supplier_fact_unchanged':True}
    def lineage(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryRuntimeIdentityLineageRow,id)
            if not x: raise ValueError('RUNTIME_IDENTITY_LINEAGE_NOT_FOUND')
            return {'runtime_identity_lineage_id':x.runtime_identity_lineage_id,'predecessor_identity_id':x.predecessor_identity_id,'replacement_identity_id':x.replacement_identity_id,'identity_reissuance_request_id':x.identity_reissuance_request_id,'environment':x.environment,'lineage_hash':x.lineage_hash,'created_by':x.created_by,'created_at':aware(x.created_at).isoformat(),'supplier_fact_unchanged':True}
    def tombstone(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryRevokedIdentityTombstoneRow,id)
            if not x: raise ValueError('REVOKED_IDENTITY_TOMBSTONE_NOT_FOUND')
            return {'revoked_identity_tombstone_id':x.revoked_identity_tombstone_id,'runtime_identity_id':x.runtime_identity_id,'environment':x.environment,'identity_fingerprint':x.identity_fingerprint,'terminal_state':x.terminal_state,'reason_code':x.reason_code,'evidence_reference':x.evidence_reference,'tombstone_hash':x.tombstone_hash,'replacement_identity_id':x.replacement_identity_id,'created_by':x.created_by,'created_at':aware(x.created_at).isoformat(),'supplier_fact_unchanged':True}
    def status(self,environment='PROD'):
        with SessionLocal() as s:
            reqs=s.execute(select(JourneyRecoveryIdentityReissuanceRequestRow).where(JourneyRecoveryIdentityReissuanceRequestRow.environment==environment).order_by(JourneyRecoveryIdentityReissuanceRequestRow.requested_at.desc())).scalars().all()
            lines=s.execute(select(JourneyRecoveryRuntimeIdentityLineageRow).where(JourneyRecoveryRuntimeIdentityLineageRow.environment==environment).order_by(JourneyRecoveryRuntimeIdentityLineageRow.created_at.desc())).scalars().all()
            tombs=s.execute(select(JourneyRecoveryRevokedIdentityTombstoneRow).where(JourneyRecoveryRevokedIdentityTombstoneRow.environment==environment).order_by(JourneyRecoveryRevokedIdentityTombstoneRow.created_at.desc())).scalars().all()
            return {'environment':environment,'reissuance_requests':[self.get(x.identity_reissuance_request_id) for x in reqs[:20]],'lineage':[self.lineage(x.runtime_identity_lineage_id) for x in lines[:20]],'tombstones':[self.tombstone(x.revoked_identity_tombstone_id) for x in tombs[:20]],'trust_cache_epoch':lifecycle._epoch(s,environment),'supplier_fact_unchanged':True}

recovery_runtime_identity_reissuance_service=RecoveryRuntimeIdentityReissuanceService()
