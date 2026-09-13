from datetime import datetime, timezone
from uuid import uuid4
from hashlib import sha256
import hmac, json, os, re
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True,default=str)
def h(v): return sha256(canon(v).encode()).hexdigest()
def key_env(ref): return 'GO_MODEL_BUILD_SIGNING_KEY_'+re.sub(r'[^A-Z0-9]','_',ref.upper())
def valid_sha256(v): return isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdefABCDEF' for c in v)

class RecoveryForecastArtifactGovernanceService:
    def active_policy_in_session(self,s,environment):
        return s.execute(select(JourneyRecoveryForecastArtifactPolicyRow).where(JourneyRecoveryForecastArtifactPolicyRow.environment==environment,JourneyRecoveryForecastArtifactPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryForecastArtifactPolicyRow.version_no.desc())).scalars().first()
    def create_policy(self,environment,require_sbom=True,require_signed_attestation=True,require_promotion_binding=True,allowed_package_formats=None,allowed_builder_key_refs=None,actor='model-supply-chain-governance'):
        allowed_package_formats=allowed_package_formats or ['ONNX','PICKLE','JOBLIB','TORCHSCRIPT','MODEL_BUNDLE']
        allowed_builder_key_refs=allowed_builder_key_refs or ['builder://engineering']
        if not allowed_package_formats or not allowed_builder_key_refs: raise ValueError('INVALID_MODEL_ARTIFACT_POLICY')
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryForecastArtifactPolicyRow).where(JourneyRecoveryForecastArtifactPolicyRow.environment==environment).order_by(JourneyRecoveryForecastArtifactPolicyRow.version_no.desc())).scalars().first()
            x=JourneyRecoveryForecastArtifactPolicyRow(forecast_artifact_policy_id=nid('jfap'),environment=environment,version_no=(prev.version_no+1 if prev else 1),require_sbom=require_sbom,require_signed_attestation=require_signed_attestation,require_promotion_binding=require_promotion_binding,allowed_package_formats_json=allowed_package_formats,allowed_builder_key_refs_json=allowed_builder_key_refs,requested_by=actor,approver_one=None,approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.policy(x.forecast_artifact_policy_id)
    def approve_policy(self,policy_id,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryForecastArtifactPolicyRow,policy_id)
            if not x: raise ValueError('MODEL_ARTIFACT_POLICY_NOT_FOUND')
            if actor==x.requested_by: raise ValueError('MODEL_ARTIFACT_POLICY_MAKER_CHECKER_REQUIRED')
            if not x.approver_one: x.approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
            elif x.approver_one==actor: raise ValueError('TWO_DISTINCT_ARTIFACT_POLICY_APPROVERS_REQUIRED')
            elif not x.approver_two:
                x.approver_two=actor
                for y in s.execute(select(JourneyRecoveryForecastArtifactPolicyRow).where(JourneyRecoveryForecastArtifactPolicyRow.environment==x.environment,JourneyRecoveryForecastArtifactPolicyRow.state=='ACTIVE')).scalars().all(): y.state='SUPERSEDED'
                x.state='ACTIVE'
            s.commit();return self.policy(policy_id)
    def register_artifact(self,environment,challenger_model_version_id,training_manifest_id,package_ref,package_format,artifact_digest,artifact_size_bytes,registry_namespace='go-forecast-models',actor='model-registry'):
        if not package_ref or not valid_sha256(artifact_digest) or artifact_size_bytes<1: raise ValueError('VALID_MODEL_ARTIFACT_METADATA_REQUIRED')
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p: raise ValueError('ACTIVE_MODEL_ARTIFACT_POLICY_REQUIRED')
            if package_format not in p.allowed_package_formats_json: raise ValueError('MODEL_PACKAGE_FORMAT_NOT_ALLOWED')
            m=s.get(JourneyRecoveryForecastTrainingManifestRow,training_manifest_id)
            if not m or m.environment!=environment or m.challenger_model_version_id!=challenger_model_version_id: raise ValueError('TRAINING_MANIFEST_MODEL_BINDING_MISMATCH')
            e=s.execute(select(JourneyRecoveryForecastModelBuildEligibilityRow).where(JourneyRecoveryForecastModelBuildEligibilityRow.environment==environment,JourneyRecoveryForecastModelBuildEligibilityRow.challenger_model_version_id==challenger_model_version_id,JourneyRecoveryForecastModelBuildEligibilityRow.training_manifest_id==training_manifest_id,JourneyRecoveryForecastModelBuildEligibilityRow.eligibility_state=='ELIGIBLE').order_by(JourneyRecoveryForecastModelBuildEligibilityRow.evaluated_at.desc())).scalars().first()
            if not e: raise ValueError('REPRODUCIBLE_MODEL_BUILD_ELIGIBILITY_REQUIRED')
            x=JourneyRecoveryForecastModelArtifactRow(forecast_model_artifact_id=nid('jfma'),environment=environment,challenger_model_version_id=challenger_model_version_id,training_manifest_id=training_manifest_id,build_hash=m.build_hash,package_ref=package_ref,package_format=package_format,artifact_digest=artifact_digest.lower(),artifact_size_bytes=artifact_size_bytes,registry_namespace=registry_namespace,state='REGISTERED',registered_by=actor,registered_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,environment,'MODEL_ARTIFACT_REGISTERED',challenger_model_version_id,x.forecast_model_artifact_id,{'artifact_digest':x.artifact_digest,'build_hash':x.build_hash},actor);s.commit();return self.artifact(x.forecast_model_artifact_id)
    def attach_sbom(self,artifact_id,sbom_format,components,provenance=None,actor='model-supply-chain'):
        components=components or [];provenance=provenance or {}
        if not sbom_format or not components: raise ValueError('MODEL_ARTIFACT_SBOM_REQUIRED')
        with SessionLocal() as s:
            a=s.get(JourneyRecoveryForecastModelArtifactRow,artifact_id)
            if not a: raise ValueError('MODEL_ARTIFACT_NOT_FOUND')
            payload={'artifact_digest':a.artifact_digest,'sbom_format':sbom_format,'components':components,'provenance':provenance}
            x=JourneyRecoveryForecastArtifactSbomRow(forecast_artifact_sbom_id=nid('jfas'),environment=a.environment,forecast_model_artifact_id=artifact_id,sbom_format=sbom_format,components_json=components,sbom_digest=h(payload),provenance_json=provenance,created_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,a.environment,'MODEL_ARTIFACT_SBOM_ATTACHED',a.challenger_model_version_id,artifact_id,{'sbom_digest':x.sbom_digest},actor);s.commit();return self.sbom(x.forecast_artifact_sbom_id)
    def attestation_message(self,artifact,training_manifest,sbom_digest,builder_identity,signing_key_ref):
        return canon({'forecast_model_artifact_id':artifact.forecast_model_artifact_id,'challenger_model_version_id':artifact.challenger_model_version_id,'training_manifest_id':training_manifest.forecast_training_manifest_id,'build_hash':training_manifest.build_hash,'artifact_digest':artifact.artifact_digest,'sbom_digest':sbom_digest,'builder_identity':builder_identity,'signing_key_ref':signing_key_ref})
    def sign_for_engineering(self,artifact_id,builder_identity,signing_key_ref):
        with SessionLocal() as s:
            a=s.get(JourneyRecoveryForecastModelArtifactRow,artifact_id)
            if not a: raise ValueError('MODEL_ARTIFACT_NOT_FOUND')
            m=s.get(JourneyRecoveryForecastTrainingManifestRow,a.training_manifest_id);sb=s.execute(select(JourneyRecoveryForecastArtifactSbomRow).where(JourneyRecoveryForecastArtifactSbomRow.forecast_model_artifact_id==artifact_id).order_by(JourneyRecoveryForecastArtifactSbomRow.created_at.desc())).scalars().first()
            if not sb: raise ValueError('MODEL_ARTIFACT_SBOM_REQUIRED')
            key=os.getenv(key_env(signing_key_ref))
            if not key: raise ValueError('MODEL_BUILD_SIGNING_KEY_UNAVAILABLE')
            return hmac.new(key.encode(),self.attestation_message(a,m,sb.sbom_digest,builder_identity,signing_key_ref).encode(),sha256).hexdigest()
    def attest_build(self,artifact_id,builder_identity,signing_key_ref,signature,evidence_reference,actor='build-attestation-verifier'):
        if not evidence_reference: raise ValueError('BUILD_ATTESTATION_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            a=s.get(JourneyRecoveryForecastModelArtifactRow,artifact_id)
            if not a: raise ValueError('MODEL_ARTIFACT_NOT_FOUND')
            p=self.active_policy_in_session(s,a.environment)
            if not p: raise ValueError('ACTIVE_MODEL_ARTIFACT_POLICY_REQUIRED')
            if signing_key_ref not in p.allowed_builder_key_refs_json: raise ValueError('BUILDER_SIGNING_KEY_NOT_ALLOWED')
            m=s.get(JourneyRecoveryForecastTrainingManifestRow,a.training_manifest_id);sb=s.execute(select(JourneyRecoveryForecastArtifactSbomRow).where(JourneyRecoveryForecastArtifactSbomRow.forecast_model_artifact_id==artifact_id).order_by(JourneyRecoveryForecastArtifactSbomRow.created_at.desc())).scalars().first()
            if p.require_sbom and not sb: raise ValueError('MODEL_ARTIFACT_SBOM_REQUIRED')
            sd=sb.sbom_digest if sb else h({'none':True})
            msg=self.attestation_message(a,m,sd,builder_identity,signing_key_ref);ph=sha256(msg.encode()).hexdigest();key=os.getenv(key_env(signing_key_ref))
            if not key: raise ValueError('MODEL_BUILD_SIGNING_KEY_UNAVAILABLE')
            expected=hmac.new(key.encode(),msg.encode(),sha256).hexdigest();state='VERIFIED' if hmac.compare_digest(expected,signature) else 'INVALID'
            x=JourneyRecoveryForecastBuildAttestationRow(forecast_build_attestation_id=nid('jfba'),environment=a.environment,forecast_model_artifact_id=artifact_id,training_manifest_id=m.forecast_training_manifest_id,build_hash=m.build_hash,artifact_digest=a.artifact_digest,sbom_digest=sd,builder_identity=builder_identity,signing_key_ref=signing_key_ref,attestation_payload_hash=ph,signature=signature,verification_state=state,evidence_reference=evidence_reference,verified_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,a.environment,'BUILD_ATTESTATION_VERIFIED',a.challenger_model_version_id,artifact_id,{'verification_state':state,'payload_hash':ph},actor);s.commit();return self.attestation(x.forecast_build_attestation_id)
    def assess_integrity(self,artifact_id,observed_artifact_digest,observed_build_hash,evidence_reference,actor='artifact-integrity-controller'):
        if not evidence_reference or not valid_sha256(observed_artifact_digest) or not valid_sha256(observed_build_hash): raise ValueError('ARTIFACT_INTEGRITY_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            a=s.get(JourneyRecoveryForecastModelArtifactRow,artifact_id)
            if not a: raise ValueError('MODEL_ARTIFACT_NOT_FOUND')
            reasons=[]
            if a.artifact_digest!=observed_artifact_digest.lower(): reasons.append('ARTIFACT_DIGEST_MISMATCH')
            if a.build_hash!=observed_build_hash.lower(): reasons.append('BUILD_HASH_MISMATCH')
            state='TAMPERED' if reasons else 'PASS'
            x=JourneyRecoveryForecastArtifactIntegrityAssessmentRow(forecast_artifact_integrity_assessment_id=nid('jfai'),environment=a.environment,forecast_model_artifact_id=artifact_id,expected_artifact_digest=a.artifact_digest,observed_artifact_digest=observed_artifact_digest.lower(),expected_build_hash=a.build_hash,observed_build_hash=observed_build_hash.lower(),integrity_state=state,reason_codes_json=reasons,evidence_reference=evidence_reference,assessed_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,a.environment,'MODEL_ARTIFACT_INTEGRITY_ASSESSED',a.challenger_model_version_id,artifact_id,{'state':state,'reason_codes':reasons},actor);s.commit();return self.integrity(x.forecast_artifact_integrity_assessment_id)
    def bind_for_promotion(self,artifact_id,actor='model-promotion-binding'):
        with SessionLocal() as s:
            a=s.get(JourneyRecoveryForecastModelArtifactRow,artifact_id)
            if not a: raise ValueError('MODEL_ARTIFACT_NOT_FOUND')
            p=self.active_policy_in_session(s,a.environment)
            if not p: raise ValueError('ACTIVE_MODEL_ARTIFACT_POLICY_REQUIRED')
            att=s.execute(select(JourneyRecoveryForecastBuildAttestationRow).where(JourneyRecoveryForecastBuildAttestationRow.forecast_model_artifact_id==artifact_id,JourneyRecoveryForecastBuildAttestationRow.verification_state=='VERIFIED').order_by(JourneyRecoveryForecastBuildAttestationRow.verified_at.desc())).scalars().first()
            integ=s.execute(select(JourneyRecoveryForecastArtifactIntegrityAssessmentRow).where(JourneyRecoveryForecastArtifactIntegrityAssessmentRow.forecast_model_artifact_id==artifact_id).order_by(JourneyRecoveryForecastArtifactIntegrityAssessmentRow.assessed_at.desc())).scalars().first()
            if p.require_signed_attestation and not att: raise ValueError('VERIFIED_BUILD_ATTESTATION_REQUIRED')
            if not integ or integ.integrity_state!='PASS': raise ValueError('MODEL_ARTIFACT_INTEGRITY_PASS_REQUIRED')
            payload={'challenger_model_version_id':a.challenger_model_version_id,'artifact_id':artifact_id,'training_manifest_id':a.training_manifest_id,'attestation_id':att.forecast_build_attestation_id if att else None,'build_hash':a.build_hash,'artifact_digest':a.artifact_digest}
            x=JourneyRecoveryForecastArtifactPromotionBindingRow(forecast_artifact_promotion_binding_id=nid('jfapb'),environment=a.environment,challenger_model_version_id=a.challenger_model_version_id,forecast_model_artifact_id=artifact_id,training_manifest_id=a.training_manifest_id,forecast_build_attestation_id=(att.forecast_build_attestation_id if att else 'NOT_REQUIRED'),build_hash=a.build_hash,artifact_digest=a.artifact_digest,binding_hash=h(payload),binding_state='ACTIVE',bound_by=actor,bound_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,a.environment,'MODEL_ARTIFACT_BOUND_FOR_PROMOTION',a.challenger_model_version_id,artifact_id,{'binding_hash':x.binding_hash},actor);s.commit();return self.binding(x.forecast_artifact_promotion_binding_id)
    def assert_artifact_eligible_in_session(self,s,environment,challenger_id):
        p=self.active_policy_in_session(s,environment)
        if not p:return
        b=s.execute(select(JourneyRecoveryForecastArtifactPromotionBindingRow).where(JourneyRecoveryForecastArtifactPromotionBindingRow.environment==environment,JourneyRecoveryForecastArtifactPromotionBindingRow.challenger_model_version_id==challenger_id,JourneyRecoveryForecastArtifactPromotionBindingRow.binding_state=='ACTIVE').order_by(JourneyRecoveryForecastArtifactPromotionBindingRow.bound_at.desc())).scalars().first()
        if p.require_promotion_binding and not b: raise ValueError('SIGNED_MODEL_ARTIFACT_PROMOTION_BINDING_REQUIRED')
        if not b:return
        a=s.get(JourneyRecoveryForecastModelArtifactRow,b.forecast_model_artifact_id);m=s.get(JourneyRecoveryForecastTrainingManifestRow,b.training_manifest_id);att=s.get(JourneyRecoveryForecastBuildAttestationRow,b.forecast_build_attestation_id) if b.forecast_build_attestation_id!='NOT_REQUIRED' else None
        if not a or not m or a.challenger_model_version_id!=challenger_id or a.build_hash!=m.build_hash or b.build_hash!=m.build_hash or b.artifact_digest!=a.artifact_digest: raise ValueError('MODEL_ARTIFACT_BUILD_BINDING_MISMATCH')
        if p.require_signed_attestation and (not att or att.verification_state!='VERIFIED' or att.build_hash!=m.build_hash or att.artifact_digest!=a.artifact_digest): raise ValueError('VERIFIED_BUILD_ATTESTATION_REQUIRED')
        if p.require_sbom:
            sb=s.execute(select(JourneyRecoveryForecastArtifactSbomRow).where(JourneyRecoveryForecastArtifactSbomRow.forecast_model_artifact_id==a.forecast_model_artifact_id).order_by(JourneyRecoveryForecastArtifactSbomRow.created_at.desc())).scalars().first()
            if not sb or (att and att.sbom_digest!=sb.sbom_digest): raise ValueError('MODEL_ARTIFACT_SBOM_BINDING_REQUIRED')
        integ=s.execute(select(JourneyRecoveryForecastArtifactIntegrityAssessmentRow).where(JourneyRecoveryForecastArtifactIntegrityAssessmentRow.forecast_model_artifact_id==a.forecast_model_artifact_id).order_by(JourneyRecoveryForecastArtifactIntegrityAssessmentRow.assessed_at.desc())).scalars().first()
        if not integ or integ.integrity_state!='PASS' or integ.observed_artifact_digest!=a.artifact_digest or integ.observed_build_hash!=m.build_hash: raise ValueError('MODEL_ARTIFACT_INTEGRITY_PASS_REQUIRED')
    def status(self,environment):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            return {'active_policy':self._policy(p) if p else None,'artifacts':[self._artifact(x) for x in s.execute(select(JourneyRecoveryForecastModelArtifactRow).where(JourneyRecoveryForecastModelArtifactRow.environment==environment).order_by(JourneyRecoveryForecastModelArtifactRow.registered_at.desc()).limit(20)).scalars().all()],'bindings':[self._binding(x) for x in s.execute(select(JourneyRecoveryForecastArtifactPromotionBindingRow).where(JourneyRecoveryForecastArtifactPromotionBindingRow.environment==environment).order_by(JourneyRecoveryForecastArtifactPromotionBindingRow.bound_at.desc()).limit(20)).scalars().all()],'integrity':[self._integrity(x) for x in s.execute(select(JourneyRecoveryForecastArtifactIntegrityAssessmentRow).where(JourneyRecoveryForecastArtifactIntegrityAssessmentRow.environment==environment).order_by(JourneyRecoveryForecastArtifactIntegrityAssessmentRow.assessed_at.desc()).limit(20)).scalars().all()]}
    def _event(self,s,environment,event_type,challenger,artifact,evidence,actor): s.add(JourneyRecoveryForecastArtifactGovernanceEventRow(forecast_artifact_governance_event_id=nid('jfage'),environment=environment,event_type=event_type,challenger_model_version_id=challenger,forecast_model_artifact_id=artifact,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def policy(self,i):
        with SessionLocal() as s:return self._policy(s.get(JourneyRecoveryForecastArtifactPolicyRow,i))
    def artifact(self,i):
        with SessionLocal() as s:return self._artifact(s.get(JourneyRecoveryForecastModelArtifactRow,i))
    def sbom(self,i):
        with SessionLocal() as s:return self._sbom(s.get(JourneyRecoveryForecastArtifactSbomRow,i))
    def attestation(self,i):
        with SessionLocal() as s:return self._attestation(s.get(JourneyRecoveryForecastBuildAttestationRow,i))
    def integrity(self,i):
        with SessionLocal() as s:return self._integrity(s.get(JourneyRecoveryForecastArtifactIntegrityAssessmentRow,i))
    def binding(self,i):
        with SessionLocal() as s:return self._binding(s.get(JourneyRecoveryForecastArtifactPromotionBindingRow,i))
    def _policy(self,x): return {'forecast_artifact_policy_id':x.forecast_artifact_policy_id,'environment':x.environment,'version_no':x.version_no,'require_sbom':x.require_sbom,'require_signed_attestation':x.require_signed_attestation,'require_promotion_binding':x.require_promotion_binding,'allowed_package_formats':x.allowed_package_formats_json,'allowed_builder_key_refs':x.allowed_builder_key_refs_json,'state':x.state,'supplier_fact_unchanged':True}
    def _artifact(self,x): return {'forecast_model_artifact_id':x.forecast_model_artifact_id,'challenger_model_version_id':x.challenger_model_version_id,'training_manifest_id':x.training_manifest_id,'build_hash':x.build_hash,'package_ref':x.package_ref,'package_format':x.package_format,'artifact_digest':x.artifact_digest,'artifact_size_bytes':x.artifact_size_bytes,'registry_namespace':x.registry_namespace,'state':x.state,'supplier_fact_unchanged':True}
    def _sbom(self,x): return {'forecast_artifact_sbom_id':x.forecast_artifact_sbom_id,'forecast_model_artifact_id':x.forecast_model_artifact_id,'sbom_format':x.sbom_format,'sbom_digest':x.sbom_digest,'components':x.components_json,'provenance':x.provenance_json,'supplier_fact_unchanged':True}
    def _attestation(self,x): return {'forecast_build_attestation_id':x.forecast_build_attestation_id,'forecast_model_artifact_id':x.forecast_model_artifact_id,'build_hash':x.build_hash,'artifact_digest':x.artifact_digest,'sbom_digest':x.sbom_digest,'builder_identity':x.builder_identity,'signing_key_ref':x.signing_key_ref,'attestation_payload_hash':x.attestation_payload_hash,'verification_state':x.verification_state,'supplier_fact_unchanged':True}
    def _integrity(self,x): return {'forecast_artifact_integrity_assessment_id':x.forecast_artifact_integrity_assessment_id,'forecast_model_artifact_id':x.forecast_model_artifact_id,'integrity_state':x.integrity_state,'reason_codes':x.reason_codes_json,'expected_artifact_digest':x.expected_artifact_digest,'observed_artifact_digest':x.observed_artifact_digest,'supplier_fact_unchanged':True}
    def _binding(self,x): return {'forecast_artifact_promotion_binding_id':x.forecast_artifact_promotion_binding_id,'challenger_model_version_id':x.challenger_model_version_id,'forecast_model_artifact_id':x.forecast_model_artifact_id,'build_hash':x.build_hash,'artifact_digest':x.artifact_digest,'binding_hash':x.binding_hash,'binding_state':x.binding_state,'supplier_fact_unchanged':True}

recovery_forecast_artifact_governance_service=RecoveryForecastArtifactGovernanceService()
