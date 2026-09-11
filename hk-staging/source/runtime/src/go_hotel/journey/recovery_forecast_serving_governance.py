from datetime import datetime,timezone
from uuid import uuid4
from hashlib import sha256
import json
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True,default=str)
def h(v): return sha256(canon(v).encode()).hexdigest()
def valid_hash(v): return isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdefABCDEF' for c in v)

class RecoveryForecastServingGovernanceService:
    def active_policy_in_session(self,s,environment):
        return s.execute(select(JourneyRecoveryForecastServingPolicyRow).where(JourneyRecoveryForecastServingPolicyRow.environment==environment,JourneyRecoveryForecastServingPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryForecastServingPolicyRow.version_no.desc())).scalars().first()
    def create_policy(self,environment,require_serving_attestation=True,require_runtime_fingerprint=True,require_artifact_binding=True,actor='model-serving-governance'):
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryForecastServingPolicyRow).where(JourneyRecoveryForecastServingPolicyRow.environment==environment).order_by(JourneyRecoveryForecastServingPolicyRow.version_no.desc())).scalars().first()
            x=JourneyRecoveryForecastServingPolicyRow(forecast_serving_policy_id=nid('jfsp'),environment=environment,version_no=(prev.version_no+1 if prev else 1),require_serving_attestation=require_serving_attestation,require_runtime_fingerprint=require_runtime_fingerprint,require_artifact_binding=require_artifact_binding,requested_by=actor,approver_one=None,approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.policy(x.forecast_serving_policy_id)
    def approve_policy(self,policy_id,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryForecastServingPolicyRow,policy_id)
            if not x: raise ValueError('MODEL_SERVING_POLICY_NOT_FOUND')
            if actor==x.requested_by: raise ValueError('MODEL_SERVING_POLICY_MAKER_CHECKER_REQUIRED')
            if not x.approver_one:x.approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
            elif x.approver_one==actor:raise ValueError('TWO_DISTINCT_MODEL_SERVING_POLICY_APPROVERS_REQUIRED')
            elif not x.approver_two:
                x.approver_two=actor
                for y in s.execute(select(JourneyRecoveryForecastServingPolicyRow).where(JourneyRecoveryForecastServingPolicyRow.environment==x.environment,JourneyRecoveryForecastServingPolicyRow.state=='ACTIVE')).scalars().all():y.state='SUPERSEDED'
                x.state='ACTIVE'
            s.commit();return self.policy(policy_id)
    def bind_deployment(self,environment,model_version_id,forecast_model_artifact_id,deployment_key,evidence_reference,transition_type='DEPLOY',actor='model-release'):
        if not deployment_key or not evidence_reference or transition_type not in {'DEPLOY','ROLLBACK'}: raise ValueError('VALID_MODEL_DEPLOYMENT_BINDING_REQUIRED')
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p: raise ValueError('ACTIVE_MODEL_SERVING_POLICY_REQUIRED')
            a=s.get(JourneyRecoveryForecastModelArtifactRow,forecast_model_artifact_id)
            if not a or a.environment!=environment or a.challenger_model_version_id!=model_version_id: raise ValueError('MODEL_ARTIFACT_DEPLOYMENT_BINDING_MISMATCH')
            pb=s.execute(select(JourneyRecoveryForecastArtifactPromotionBindingRow).where(JourneyRecoveryForecastArtifactPromotionBindingRow.environment==environment,JourneyRecoveryForecastArtifactPromotionBindingRow.challenger_model_version_id==model_version_id,JourneyRecoveryForecastArtifactPromotionBindingRow.forecast_model_artifact_id==forecast_model_artifact_id,JourneyRecoveryForecastArtifactPromotionBindingRow.binding_state=='ACTIVE').order_by(JourneyRecoveryForecastArtifactPromotionBindingRow.bound_at.desc())).scalars().first()
            if not pb: raise ValueError('SIGNED_MODEL_ARTIFACT_PROMOTION_BINDING_REQUIRED')
            integ=s.execute(select(JourneyRecoveryForecastArtifactIntegrityAssessmentRow).where(JourneyRecoveryForecastArtifactIntegrityAssessmentRow.forecast_model_artifact_id==forecast_model_artifact_id).order_by(JourneyRecoveryForecastArtifactIntegrityAssessmentRow.assessed_at.desc())).scalars().first()
            if not integ or integ.integrity_state!='PASS': raise ValueError('MODEL_ARTIFACT_INTEGRITY_PASS_REQUIRED')
            prev=s.execute(select(JourneyRecoveryForecastArtifactDeploymentBindingRow).where(JourneyRecoveryForecastArtifactDeploymentBindingRow.environment==environment,JourneyRecoveryForecastArtifactDeploymentBindingRow.deployment_key==deployment_key,JourneyRecoveryForecastArtifactDeploymentBindingRow.state=='ACTIVE').order_by(JourneyRecoveryForecastArtifactDeploymentBindingRow.bound_at.desc())).scalars().first()
            if prev: prev.state='SUPERSEDED'
            bh=h({'environment':environment,'model_version_id':model_version_id,'artifact_id':forecast_model_artifact_id,'promotion_binding_id':pb.forecast_artifact_promotion_binding_id,'deployment_key':deployment_key,'artifact_digest':a.artifact_digest,'build_hash':a.build_hash})
            x=JourneyRecoveryForecastArtifactDeploymentBindingRow(forecast_artifact_deployment_binding_id=nid('jfdb'),environment=environment,model_version_id=model_version_id,forecast_model_artifact_id=forecast_model_artifact_id,forecast_artifact_promotion_binding_id=pb.forecast_artifact_promotion_binding_id,deployment_key=deployment_key,expected_artifact_digest=a.artifact_digest,expected_build_hash=a.build_hash,binding_hash=bh,state='ACTIVE',bound_by=actor,bound_at=now(),supplier_fact_unchanged=True);s.add(x);s.flush()
            lineage=JourneyRecoveryForecastModelDeploymentLineageRow(forecast_model_deployment_lineage_id=nid('jfdl'),environment=environment,deployment_key=deployment_key,previous_binding_id=(prev.forecast_artifact_deployment_binding_id if prev else None),current_binding_id=x.forecast_artifact_deployment_binding_id,transition_type=transition_type,transition_hash=h({'previous':prev.forecast_artifact_deployment_binding_id if prev else None,'current':x.forecast_artifact_deployment_binding_id,'type':transition_type,'evidence':evidence_reference}),evidence_reference=evidence_reference,created_at=now(),supplier_fact_unchanged=True);s.add(lineage)
            self._event(s,environment,'MODEL_DEPLOYMENT_BOUND',actor,{'binding_hash':bh,'transition_type':transition_type},model_version_id,deployment_key);s.commit();return self.binding(x.forecast_artifact_deployment_binding_id)
    def register_runtime_identity(self,environment,deployment_key,runtime_instance_ref,model_version_id,forecast_model_artifact_id,actor='runtime-attestor'):
        if not runtime_instance_ref: raise ValueError('RUNTIME_INSTANCE_REFERENCE_REQUIRED')
        with SessionLocal() as s:
            b=s.execute(select(JourneyRecoveryForecastArtifactDeploymentBindingRow).where(JourneyRecoveryForecastArtifactDeploymentBindingRow.environment==environment,JourneyRecoveryForecastArtifactDeploymentBindingRow.deployment_key==deployment_key,JourneyRecoveryForecastArtifactDeploymentBindingRow.state=='ACTIVE').order_by(JourneyRecoveryForecastArtifactDeploymentBindingRow.bound_at.desc())).scalars().first()
            if not b or b.model_version_id!=model_version_id or b.forecast_model_artifact_id!=forecast_model_artifact_id: raise ValueError('ACTIVE_ARTIFACT_DEPLOYMENT_BINDING_REQUIRED')
            fp=h({'environment':environment,'deployment_key':deployment_key,'runtime_instance_ref':runtime_instance_ref,'model_version_id':model_version_id,'artifact_id':forecast_model_artifact_id,'binding_hash':b.binding_hash})
            x=JourneyRecoveryForecastRuntimeModelIdentityRow(forecast_runtime_model_identity_id=nid('jfri'),environment=environment,deployment_key=deployment_key,runtime_instance_ref=runtime_instance_ref,model_version_id=model_version_id,forecast_model_artifact_id=forecast_model_artifact_id,runtime_model_fingerprint=fp,state='ACTIVE',registered_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,environment,'RUNTIME_MODEL_IDENTITY_REGISTERED',actor,{'runtime_model_fingerprint':fp},model_version_id,deployment_key);s.commit();return self.runtime_identity(x.forecast_runtime_model_identity_id)
    def attest_serving(self,runtime_identity_id,loaded_artifact_digest,loaded_build_hash,observed_runtime_fingerprint,evidence_reference,actor='model-serving-attestor'):
        if not all([valid_hash(loaded_artifact_digest),valid_hash(loaded_build_hash),valid_hash(observed_runtime_fingerprint),evidence_reference]): raise ValueError('VALID_MODEL_SERVING_ATTESTATION_REQUIRED')
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryForecastRuntimeModelIdentityRow,runtime_identity_id)
            if not r or r.state!='ACTIVE': raise ValueError('ACTIVE_RUNTIME_MODEL_IDENTITY_REQUIRED')
            b=s.execute(select(JourneyRecoveryForecastArtifactDeploymentBindingRow).where(JourneyRecoveryForecastArtifactDeploymentBindingRow.environment==r.environment,JourneyRecoveryForecastArtifactDeploymentBindingRow.deployment_key==r.deployment_key,JourneyRecoveryForecastArtifactDeploymentBindingRow.state=='ACTIVE').order_by(JourneyRecoveryForecastArtifactDeploymentBindingRow.bound_at.desc())).scalars().first()
            if not b: raise ValueError('ACTIVE_ARTIFACT_DEPLOYMENT_BINDING_REQUIRED')
            reasons=[]
            if r.model_version_id!=b.model_version_id: reasons.append('RUNTIME_MODEL_VERSION_MISMATCH')
            if r.forecast_model_artifact_id!=b.forecast_model_artifact_id: reasons.append('RUNTIME_ARTIFACT_ID_MISMATCH')
            if loaded_artifact_digest.lower()!=b.expected_artifact_digest.lower(): reasons.append('LOADED_ARTIFACT_DIGEST_MISMATCH')
            if loaded_build_hash.lower()!=b.expected_build_hash.lower(): reasons.append('LOADED_BUILD_HASH_MISMATCH')
            if observed_runtime_fingerprint.lower()!=r.runtime_model_fingerprint.lower(): reasons.append('RUNTIME_MODEL_FINGERPRINT_MISMATCH')
            state='VERIFIED' if not reasons else 'MISMATCH'
            x=JourneyRecoveryForecastModelServingAttestationRow(forecast_model_serving_attestation_id=nid('jfsa'),environment=r.environment,forecast_artifact_deployment_binding_id=b.forecast_artifact_deployment_binding_id,forecast_runtime_model_identity_id=r.forecast_runtime_model_identity_id,model_version_id=r.model_version_id,forecast_model_artifact_id=r.forecast_model_artifact_id,expected_artifact_digest=b.expected_artifact_digest,loaded_artifact_digest=loaded_artifact_digest.lower(),expected_build_hash=b.expected_build_hash,loaded_build_hash=loaded_build_hash.lower(),expected_runtime_fingerprint=r.runtime_model_fingerprint,observed_runtime_fingerprint=observed_runtime_fingerprint.lower(),attestation_state=state,reason_codes_json=reasons,evidence_reference=evidence_reference,attested_at=now(),supplier_fact_unchanged=True);s.add(x);s.flush()
            ctrl=s.execute(select(JourneyRecoveryForecastServingSafetyControlRow).where(JourneyRecoveryForecastServingSafetyControlRow.environment==r.environment,JourneyRecoveryForecastServingSafetyControlRow.deployment_key==r.deployment_key,JourneyRecoveryForecastServingSafetyControlRow.control_state=='BLOCKED')).scalars().first()
            if reasons and not ctrl:
                ctrl=JourneyRecoveryForecastServingSafetyControlRow(forecast_serving_safety_control_id=nid('jfsc'),environment=r.environment,model_version_id=r.model_version_id,deployment_key=r.deployment_key,control_state='BLOCKED',reason_codes_json=reasons,activated_at=now(),released_at=None,release_evidence_reference=None,supplier_fact_unchanged=True);s.add(ctrl)
            self._event(s,r.environment,'MODEL_SERVING_ATTESTED' if not reasons else 'MODEL_SERVING_MISMATCH_BLOCKED',actor,{'attestation_state':state,'reason_codes':reasons},r.model_version_id,r.deployment_key);s.commit();return self.attestation(x.forecast_model_serving_attestation_id)
    def assert_runtime_model_eligible_in_session(self,s,environment,model_version_id):
        p=self.active_policy_in_session(s,environment)
        if not p:return True
        if not model_version_id: raise ValueError('RUNTIME_MODEL_IDENTITY_REQUIRED')
        b=s.execute(select(JourneyRecoveryForecastArtifactDeploymentBindingRow).where(JourneyRecoveryForecastArtifactDeploymentBindingRow.environment==environment,JourneyRecoveryForecastArtifactDeploymentBindingRow.model_version_id==model_version_id,JourneyRecoveryForecastArtifactDeploymentBindingRow.state=='ACTIVE').order_by(JourneyRecoveryForecastArtifactDeploymentBindingRow.bound_at.desc())).scalars().first()
        if not b: raise ValueError('RUNTIME_MODEL_DEPLOYMENT_BINDING_REQUIRED')
        ctrl=s.execute(select(JourneyRecoveryForecastServingSafetyControlRow).where(JourneyRecoveryForecastServingSafetyControlRow.environment==environment,JourneyRecoveryForecastServingSafetyControlRow.deployment_key==b.deployment_key,JourneyRecoveryForecastServingSafetyControlRow.control_state=='BLOCKED')).scalars().first()
        if ctrl: raise ValueError('RUNTIME_MODEL_SERVING_BLOCKED_BY_ATTESTATION_MISMATCH')
        r=s.execute(select(JourneyRecoveryForecastRuntimeModelIdentityRow).where(JourneyRecoveryForecastRuntimeModelIdentityRow.environment==environment,JourneyRecoveryForecastRuntimeModelIdentityRow.deployment_key==b.deployment_key,JourneyRecoveryForecastRuntimeModelIdentityRow.model_version_id==model_version_id,JourneyRecoveryForecastRuntimeModelIdentityRow.forecast_model_artifact_id==b.forecast_model_artifact_id,JourneyRecoveryForecastRuntimeModelIdentityRow.state=='ACTIVE').order_by(JourneyRecoveryForecastRuntimeModelIdentityRow.registered_at.desc())).scalars().first()
        if not r: raise ValueError('RUNTIME_MODEL_IDENTITY_REQUIRED')
        a=s.execute(select(JourneyRecoveryForecastModelServingAttestationRow).where(JourneyRecoveryForecastModelServingAttestationRow.environment==environment,JourneyRecoveryForecastModelServingAttestationRow.forecast_runtime_model_identity_id==r.forecast_runtime_model_identity_id,JourneyRecoveryForecastModelServingAttestationRow.forecast_artifact_deployment_binding_id==b.forecast_artifact_deployment_binding_id).order_by(JourneyRecoveryForecastModelServingAttestationRow.attested_at.desc())).scalars().first()
        if not a or a.attestation_state!='VERIFIED': raise ValueError('VERIFIED_MODEL_SERVING_ATTESTATION_REQUIRED')
        return True
    def release_safety_control(self,environment,deployment_key,evidence_reference,actor='model-serving-ops'):
        if not evidence_reference: raise ValueError('MODEL_SERVING_RELEASE_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            c=s.execute(select(JourneyRecoveryForecastServingSafetyControlRow).where(JourneyRecoveryForecastServingSafetyControlRow.environment==environment,JourneyRecoveryForecastServingSafetyControlRow.deployment_key==deployment_key,JourneyRecoveryForecastServingSafetyControlRow.control_state=='BLOCKED')).scalars().first()
            if not c: raise ValueError('ACTIVE_MODEL_SERVING_BLOCK_NOT_FOUND')
            b=s.execute(select(JourneyRecoveryForecastArtifactDeploymentBindingRow).where(JourneyRecoveryForecastArtifactDeploymentBindingRow.environment==environment,JourneyRecoveryForecastArtifactDeploymentBindingRow.deployment_key==deployment_key,JourneyRecoveryForecastArtifactDeploymentBindingRow.state=='ACTIVE')).scalars().first()
            if not b: raise ValueError('ACTIVE_ARTIFACT_DEPLOYMENT_BINDING_REQUIRED')
            a=s.execute(select(JourneyRecoveryForecastModelServingAttestationRow).where(JourneyRecoveryForecastModelServingAttestationRow.forecast_artifact_deployment_binding_id==b.forecast_artifact_deployment_binding_id).order_by(JourneyRecoveryForecastModelServingAttestationRow.attested_at.desc())).scalars().first()
            if not a or a.attestation_state!='VERIFIED' or a.attested_at < c.activated_at: raise ValueError('MODEL_SERVING_RECOVERY_ATTESTATION_REQUIRED')
            c.control_state='RELEASED';c.released_at=now();c.release_evidence_reference=evidence_reference;self._event(s,environment,'MODEL_SERVING_BLOCK_RELEASED',actor,{'evidence_reference':evidence_reference},c.model_version_id,deployment_key);s.commit();return self.control(c.forecast_serving_safety_control_id)
    def status(self,environment):
        with SessionLocal() as s:
            bs=s.execute(select(JourneyRecoveryForecastArtifactDeploymentBindingRow).where(JourneyRecoveryForecastArtifactDeploymentBindingRow.environment==environment).order_by(JourneyRecoveryForecastArtifactDeploymentBindingRow.bound_at.desc()).limit(20)).scalars().all();rs=s.execute(select(JourneyRecoveryForecastRuntimeModelIdentityRow).where(JourneyRecoveryForecastRuntimeModelIdentityRow.environment==environment).order_by(JourneyRecoveryForecastRuntimeModelIdentityRow.registered_at.desc()).limit(20)).scalars().all();ats=s.execute(select(JourneyRecoveryForecastModelServingAttestationRow).where(JourneyRecoveryForecastModelServingAttestationRow.environment==environment).order_by(JourneyRecoveryForecastModelServingAttestationRow.attested_at.desc()).limit(20)).scalars().all();cs=s.execute(select(JourneyRecoveryForecastServingSafetyControlRow).where(JourneyRecoveryForecastServingSafetyControlRow.environment==environment).order_by(JourneyRecoveryForecastServingSafetyControlRow.activated_at.desc()).limit(20)).scalars().all()
            return {'bindings':[self._binding(x) for x in bs],'runtime_identities':[self._runtime_identity(x) for x in rs],'attestations':[self._attestation(x) for x in ats],'safety_controls':[self._control(x) for x in cs]}
    def _event(self,s,e,t,actor,evidence,model=None,deployment=None):s.add(JourneyRecoveryForecastServingGovernanceEventRow(forecast_serving_governance_event_id=nid('jfge'),environment=e,event_type=t,model_version_id=model,deployment_key=deployment,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def policy(self,i):
        with SessionLocal() as s:return self._policy(s.get(JourneyRecoveryForecastServingPolicyRow,i))
    def binding(self,i):
        with SessionLocal() as s:return self._binding(s.get(JourneyRecoveryForecastArtifactDeploymentBindingRow,i))
    def runtime_identity(self,i):
        with SessionLocal() as s:return self._runtime_identity(s.get(JourneyRecoveryForecastRuntimeModelIdentityRow,i))
    def attestation(self,i):
        with SessionLocal() as s:return self._attestation(s.get(JourneyRecoveryForecastModelServingAttestationRow,i))
    def control(self,i):
        with SessionLocal() as s:return self._control(s.get(JourneyRecoveryForecastServingSafetyControlRow,i))
    def _policy(self,x):return {'forecast_serving_policy_id':x.forecast_serving_policy_id,'environment':x.environment,'version_no':x.version_no,'state':x.state,'supplier_fact_unchanged':True}
    def _binding(self,x):return {'forecast_artifact_deployment_binding_id':x.forecast_artifact_deployment_binding_id,'environment':x.environment,'model_version_id':x.model_version_id,'forecast_model_artifact_id':x.forecast_model_artifact_id,'deployment_key':x.deployment_key,'expected_artifact_digest':x.expected_artifact_digest,'expected_build_hash':x.expected_build_hash,'binding_hash':x.binding_hash,'state':x.state,'supplier_fact_unchanged':True}
    def _runtime_identity(self,x):return {'forecast_runtime_model_identity_id':x.forecast_runtime_model_identity_id,'deployment_key':x.deployment_key,'runtime_instance_ref':x.runtime_instance_ref,'model_version_id':x.model_version_id,'forecast_model_artifact_id':x.forecast_model_artifact_id,'runtime_model_fingerprint':x.runtime_model_fingerprint,'state':x.state,'supplier_fact_unchanged':True}
    def _attestation(self,x):return {'forecast_model_serving_attestation_id':x.forecast_model_serving_attestation_id,'model_version_id':x.model_version_id,'forecast_model_artifact_id':x.forecast_model_artifact_id,'attestation_state':x.attestation_state,'reason_codes':x.reason_codes_json,'loaded_artifact_digest':x.loaded_artifact_digest,'loaded_build_hash':x.loaded_build_hash,'supplier_fact_unchanged':True}
    def _control(self,x):return {'forecast_serving_safety_control_id':x.forecast_serving_safety_control_id,'deployment_key':x.deployment_key,'model_version_id':x.model_version_id,'control_state':x.control_state,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}

recovery_forecast_serving_governance_service=RecoveryForecastServingGovernanceService()
