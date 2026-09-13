from datetime import datetime, timezone, timedelta
from uuid import uuid4
import hashlib,hmac,json,os
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryRuntimeIdentityRow,JourneyRecoveryTelemetryKeyVersionRow,
    JourneyRecoveryIdentityRevocationRow,JourneyRecoveryTelemetrySecurityIncidentRow,
    JourneyRecoveryTrustCacheInvalidationRow,JourneyRecoverySignedTelemetryEnvelopeRow,
)
from go_hotel.journey.recovery_runtime_telemetry_trust import env_key,aware,canon,sha

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'

class RecoveryRuntimeIdentityLifecycleService:
    def _epoch(self,s,environment):
        v=s.execute(select(func.max(JourneyRecoveryTrustCacheInvalidationRow.new_epoch)).where(JourneyRecoveryTrustCacheInvalidationRow.environment==environment)).scalar()
        return int(v or 0)
    def _invalidate(self,s,environment,identity_id,reason,actor):
        prev=self._epoch(s,environment);new=prev+1
        r=JourneyRecoveryTrustCacheInvalidationRow(trust_cache_invalidation_id=nid('jrtci'),environment=environment,runtime_identity_id=identity_id,previous_epoch=prev,new_epoch=new,reason_code=reason,invalidated_by=actor,invalidated_at=now(),supplier_fact_unchanged=True);s.add(r);return new
    def key_versions(self,identity_id):
        with SessionLocal() as s:
            rows=s.execute(select(JourneyRecoveryTelemetryKeyVersionRow).where(JourneyRecoveryTelemetryKeyVersionRow.runtime_identity_id==identity_id).order_by(JourneyRecoveryTelemetryKeyVersionRow.version_no)).scalars().all()
            return [self._key(x) for x in rows]
    def _key(self,x):
        return {'telemetry_key_version_id':x.telemetry_key_version_id,'runtime_identity_id':x.runtime_identity_id,'version_no':x.version_no,'key_ref':x.key_ref,'state':x.state,'valid_from':aware(x.valid_from).isoformat(),'valid_until':aware(x.valid_until).isoformat() if x.valid_until else None,'previous_key_version_id':x.previous_key_version_id,'transition_payload_hash':x.transition_payload_hash,'transition_signature':x.transition_signature,'evidence':x.evidence_json,'supplier_fact_unchanged':True}
    def transition_message(self,identity_id,old_key_version_id,new_key_ref,valid_from,overlap_seconds):
        ts=valid_from if isinstance(valid_from,str) else aware(valid_from).isoformat()
        return canon({'runtime_identity_id':identity_id,'old_key_version_id':old_key_version_id,'new_key_ref':new_key_ref,'valid_from':ts,'overlap_seconds':int(overlap_seconds)})
    def sign_transition_for_engineering(self,old_key_ref,**kwargs):
        key=os.getenv(env_key(old_key_ref))
        if not key: raise ValueError('SIGNING_KEY_UNAVAILABLE')
        return hmac.new(key.encode(),self.transition_message(**kwargs).encode(),hashlib.sha256).hexdigest()
    def rotate_key(self,identity_id,new_key_ref,transition_signature,actor,overlap_seconds=300,valid_from=None,evidence_reference=None):
        valid_from=aware(valid_from or now())
        if overlap_seconds<0 or overlap_seconds>86400: raise ValueError('INVALID_KEY_OVERLAP_SECONDS')
        with SessionLocal() as s:
            ident=s.get(JourneyRecoveryRuntimeIdentityRow,identity_id)
            if not ident: raise ValueError('RUNTIME_IDENTITY_NOT_FOUND')
            if ident.state!='ACTIVE': raise ValueError('RUNTIME_IDENTITY_NOT_ACTIVE')
            old=s.execute(select(JourneyRecoveryTelemetryKeyVersionRow).where(JourneyRecoveryTelemetryKeyVersionRow.runtime_identity_id==identity_id,JourneyRecoveryTelemetryKeyVersionRow.state=='ACTIVE').order_by(JourneyRecoveryTelemetryKeyVersionRow.version_no.desc())).scalars().first()
            if not old:
                old=JourneyRecoveryTelemetryKeyVersionRow(telemetry_key_version_id=nid('jrtkv'),runtime_identity_id=identity_id,version_no=1,key_ref=ident.verification_key_ref,state='ACTIVE',valid_from=ident.created_at,valid_until=None,previous_key_version_id=None,transition_payload_hash=None,transition_signature=None,evidence_json={'legacy_bootstrap':True},created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(old);s.flush()
            msg=self.transition_message(identity_id,old.telemetry_key_version_id,new_key_ref,valid_from,overlap_seconds)
            key=os.getenv(env_key(old.key_ref))
            if not key: raise ValueError('CURRENT_KEY_UNAVAILABLE')
            expected=hmac.new(key.encode(),msg.encode(),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected,transition_signature): raise ValueError('KEY_TRANSITION_SIGNATURE_INVALID')
            old.state='OVERLAP' if overlap_seconds>0 else 'RETIRED';old.valid_until=valid_from+timedelta(seconds=overlap_seconds) if overlap_seconds>0 else valid_from
            new=JourneyRecoveryTelemetryKeyVersionRow(telemetry_key_version_id=nid('jrtkv'),runtime_identity_id=identity_id,version_no=old.version_no+1,key_ref=new_key_ref,state='ACTIVE',valid_from=valid_from,valid_until=None,previous_key_version_id=old.telemetry_key_version_id,transition_payload_hash=hashlib.sha256(msg.encode()).hexdigest(),transition_signature=transition_signature,evidence_json={'evidence_reference':evidence_reference,'dual_key_overlap_seconds':overlap_seconds,'signed_by_key_version_id':old.telemetry_key_version_id},created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(new)
            ident.verification_key_ref=new_key_ref;ident.updated_at=now();epoch=self._invalidate(s,ident.environment,identity_id,'KEY_ROTATED',actor);s.commit();return {'identity_id':identity_id,'new_key_version':self._key(new),'cache_epoch':epoch,'supplier_fact_unchanged':True}
    def retire_expired_overlap(self,environment='PROD',actor='key-lifecycle-worker'):
        with SessionLocal() as s:
            rows=s.execute(select(JourneyRecoveryTelemetryKeyVersionRow,JourneyRecoveryRuntimeIdentityRow).join(JourneyRecoveryRuntimeIdentityRow,JourneyRecoveryRuntimeIdentityRow.runtime_identity_id==JourneyRecoveryTelemetryKeyVersionRow.runtime_identity_id).where(JourneyRecoveryRuntimeIdentityRow.environment==environment,JourneyRecoveryTelemetryKeyVersionRow.state=='OVERLAP')).all();n=0
            for kv,ident in rows:
                if kv.valid_until and aware(kv.valid_until)<=now(): kv.state='RETIRED';n+=1
            if n:self._invalidate(s,environment,None,'KEY_OVERLAP_EXPIRED',actor)
            s.commit();return {'environment':environment,'retired_count':n,'supplier_fact_unchanged':True}
    def revoke_identity(self,identity_id,reason_code,evidence_reference,actor):
        if not evidence_reference: raise ValueError('REVOCATION_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            ident=s.get(JourneyRecoveryRuntimeIdentityRow,identity_id)
            if not ident: raise ValueError('RUNTIME_IDENTITY_NOT_FOUND')
            if ident.state=='REVOKED': raise ValueError('RUNTIME_IDENTITY_ALREADY_REVOKED')
            ident.state='REVOKED';ident.updated_at=now()
            for kv in s.execute(select(JourneyRecoveryTelemetryKeyVersionRow).where(JourneyRecoveryTelemetryKeyVersionRow.runtime_identity_id==identity_id,JourneyRecoveryTelemetryKeyVersionRow.state.in_(['ACTIVE','OVERLAP']))).scalars().all(): kv.state='REVOKED';kv.valid_until=now()
            epoch=self._invalidate(s,ident.environment,identity_id,'IDENTITY_REVOKED',actor)
            r=JourneyRecoveryIdentityRevocationRow(identity_revocation_id=nid('jrir'),runtime_identity_id=identity_id,environment=ident.environment,reason_code=reason_code,evidence_reference=evidence_reference,effective_at=now(),revoked_by=actor,propagation_state='PROPAGATED',cache_epoch=epoch,supplier_fact_unchanged=True);s.add(r);s.commit();return {'identity_revocation_id':r.identity_revocation_id,'runtime_identity_id':identity_id,'state':'REVOKED','cache_epoch':epoch,'propagation_state':'PROPAGATED','supplier_fact_unchanged':True}
    def open_security_incident(self,identity_id,severity,reason_code,evidence,actor,revoke_immediately=False):
        if severity not in {'SEV1','SEV2','SEV3','SEV4'}: raise ValueError('INVALID_SECURITY_INCIDENT_SEVERITY')
        with SessionLocal() as s:
            ident=s.get(JourneyRecoveryRuntimeIdentityRow,identity_id)
            if not ident: raise ValueError('RUNTIME_IDENTITY_NOT_FOUND')
            existing=s.execute(select(JourneyRecoveryTelemetrySecurityIncidentRow).where(JourneyRecoveryTelemetrySecurityIncidentRow.runtime_identity_id==identity_id,JourneyRecoveryTelemetrySecurityIncidentRow.state.in_(['OPEN','CONTAINED']))).scalars().first()
            if existing: raise ValueError('SECURITY_INCIDENT_ALREADY_OPEN')
            ident.state='REVOKED' if revoke_immediately else 'SUSPENDED';ident.updated_at=now()
            if revoke_immediately:
                for kv in s.execute(select(JourneyRecoveryTelemetryKeyVersionRow).where(JourneyRecoveryTelemetryKeyVersionRow.runtime_identity_id==identity_id,JourneyRecoveryTelemetryKeyVersionRow.state.in_(['ACTIVE','OVERLAP']))).scalars().all(): kv.state='REVOKED';kv.valid_until=now()
            inc=JourneyRecoveryTelemetrySecurityIncidentRow(telemetry_security_incident_id=nid('jrtsi'),runtime_identity_id=identity_id,environment=ident.environment,severity=severity,state='OPEN',reason_code=reason_code,quarantine_state='QUARANTINED',evidence_json=evidence or {},opened_by=actor,opened_at=now(),contained_at=None,closed_at=None,supplier_fact_unchanged=True);s.add(inc)
            epoch=self._invalidate(s,ident.environment,identity_id,'IDENTITY_COMPROMISE_QUARANTINE',actor);s.commit();return {'telemetry_security_incident_id':inc.telemetry_security_incident_id,'runtime_identity_id':identity_id,'identity_state':ident.state,'quarantine_state':'QUARANTINED','cache_epoch':epoch,'supplier_fact_unchanged':True}
    def contain_incident(self,incident_id,evidence,actor):
        with SessionLocal() as s:
            inc=s.get(JourneyRecoveryTelemetrySecurityIncidentRow,incident_id)
            if not inc: raise ValueError('TELEMETRY_SECURITY_INCIDENT_NOT_FOUND')
            if inc.state!='OPEN': raise ValueError('SECURITY_INCIDENT_NOT_OPEN')
            inc.state='CONTAINED';inc.contained_at=now();inc.evidence_json={**(inc.evidence_json or {}),'containment_evidence':evidence or {}};epoch=self._invalidate(s,inc.environment,inc.runtime_identity_id,'SECURITY_INCIDENT_CONTAINED',actor);s.commit();return {'incident_id':incident_id,'state':'CONTAINED','quarantine_state':inc.quarantine_state,'cache_epoch':epoch,'supplier_fact_unchanged':True}
    def status(self,environment='PROD'):
        with SessionLocal() as s:
            epoch=self._epoch(s,environment)
            incidents=s.execute(select(JourneyRecoveryTelemetrySecurityIncidentRow).where(JourneyRecoveryTelemetrySecurityIncidentRow.environment==environment,JourneyRecoveryTelemetrySecurityIncidentRow.state.in_(['OPEN','CONTAINED'])).order_by(JourneyRecoveryTelemetrySecurityIncidentRow.opened_at.desc())).scalars().all()
            revocations=s.execute(select(JourneyRecoveryIdentityRevocationRow).where(JourneyRecoveryIdentityRevocationRow.environment==environment).order_by(JourneyRecoveryIdentityRevocationRow.effective_at.desc())).scalars().all()
            return {'environment':environment,'trust_cache_epoch':epoch,'active_security_incidents':[{'incident_id':x.telemetry_security_incident_id,'runtime_identity_id':x.runtime_identity_id,'severity':x.severity,'state':x.state,'reason_code':x.reason_code,'quarantine_state':x.quarantine_state} for x in incidents],'recent_revocations':[{'identity_revocation_id':x.identity_revocation_id,'runtime_identity_id':x.runtime_identity_id,'reason_code':x.reason_code,'cache_epoch':x.cache_epoch} for x in revocations[:20]],'supplier_fact_unchanged':True}

recovery_runtime_identity_lifecycle_service=RecoveryRuntimeIdentityLifecycleService()
