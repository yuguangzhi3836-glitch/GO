from datetime import datetime,timezone
from hashlib import sha256
from json import dumps
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryReleaseManifestRow,JourneyRecoveryEnvironmentBindingRow,JourneyRecoveryDeploymentAttestationRow,JourneyRecoveryReleaseVerificationRow,JourneyRecoveryReleaseEvidenceSealRow
from go_hotel.journey.recovery_release_governance import recovery_release_governance_service as releases
def now():return datetime.now(timezone.utc)
def nid(p):return f'{p}_{uuid4().hex[:18]}'
def h(x):return sha256(dumps(x,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
class RecoveryRuntimeVerificationService:
 def expected_fingerprint(self,environment):
  rows=releases.bindings(environment);return h([{'config_key':x['config_key'],'config_version_id':x['active_config_version_id'],'binding_hash':x['binding_hash']} for x in sorted(rows,key=lambda x:x['config_key'])])
 def attest(self,manifest_id,environment,runtime_instance,observed_fingerprint,actor,metadata=None):
  with SessionLocal() as s:
   m=s.get(JourneyRecoveryReleaseManifestRow,manifest_id)
   if not m or m.state!='PROMOTED':raise ValueError('PROMOTED_RELEASE_REQUIRED')
   if m.target_environment!=environment:raise ValueError('ATTESTATION_ENVIRONMENT_MISMATCH')
   exp=self.expected_fingerprint(environment);state='MATCHED' if observed_fingerprint==exp else 'FINGERPRINT_MISMATCH'
   r=JourneyRecoveryDeploymentAttestationRow(deployment_attestation_id=nid('jrda'),release_manifest_id=manifest_id,environment=environment,runtime_instance=runtime_instance,expected_fingerprint=exp,observed_fingerprint=observed_fingerprint,state=state,attested_by=actor,attested_at=now(),payload_json=metadata or {},supplier_fact_unchanged=True);s.add(r);s.commit();return self.attestation(r.deployment_attestation_id)
 def verify(self,attestation_id,smoke_tests,health_slo,actor):
  with SessionLocal() as s:
   a=s.get(JourneyRecoveryDeploymentAttestationRow,attestation_id)
   if not a:raise ValueError('ATTESTATION_NOT_FOUND')
   smoke_ok=bool(smoke_tests.get('passed'));health_ok=bool(health_slo.get('passed'));passed=a.state=='MATCHED' and smoke_ok and health_ok
   action='RELEASE_VERIFIED' if passed else ('CONTROLLED_ROLLBACK_REQUIRED' if a.environment=='PROD' else 'BLOCK_ENVIRONMENT_PROMOTION')
   v=JourneyRecoveryReleaseVerificationRow(release_verification_id=nid('jrrv'),release_manifest_id=a.release_manifest_id,environment=a.environment,attestation_id=a.deployment_attestation_id,smoke_test_json=smoke_tests,health_slo_json=health_slo,state='PASSED' if passed else 'FAILED',action=action,verified_by=actor,verified_at=now(),supplier_fact_unchanged=True);s.add(v);s.commit();return self.verification(v.release_verification_id)
 def rollback_on_failure(self,verification_id,actor):
  v=self.verification(verification_id)
  if v['state']!='FAILED' or v['environment']!='PROD':raise ValueError('FAILED_PROD_VERIFICATION_REQUIRED')
  out=releases.rollback(v['release_manifest_id'],actor);return {'verification_id':verification_id,'release_manifest_id':v['release_manifest_id'],'rollback_state':out['state'],'supplier_fact_unchanged':True}
 def seal(self,verification_id,actor):
  with SessionLocal() as s:
   v=s.get(JourneyRecoveryReleaseVerificationRow,verification_id)
   if not v or v.state!='PASSED':raise ValueError('PASSED_VERIFICATION_REQUIRED')
   a=s.get(JourneyRecoveryDeploymentAttestationRow,v.attestation_id);prev=s.execute(select(JourneyRecoveryReleaseEvidenceSealRow).where(JourneyRecoveryReleaseEvidenceSealRow.release_manifest_id==v.release_manifest_id).order_by(JourneyRecoveryReleaseEvidenceSealRow.sealed_at.desc())).scalars().first();ph=prev.seal_hash if prev else None
   evidence={'manifest_id':v.release_manifest_id,'attestation_id':a.deployment_attestation_id,'expected':a.expected_fingerprint,'observed':a.observed_fingerprint,'smoke':v.smoke_test_json,'health':v.health_slo_json};eh=h(evidence);sh=h({'evidence_hash':eh,'previous_hash':ph})
   r=JourneyRecoveryReleaseEvidenceSealRow(release_evidence_seal_id=nid('jrres'),release_manifest_id=v.release_manifest_id,attestation_id=a.deployment_attestation_id,verification_id=v.release_verification_id,evidence_hash=eh,previous_hash=ph,seal_hash=sh,sealed_by=actor,sealed_at=now(),supplier_fact_unchanged=True);s.add(r);s.commit();return {'release_evidence_seal_id':r.release_evidence_seal_id,'evidence_hash':eh,'previous_hash':ph,'seal_hash':sh,'supplier_fact_unchanged':True}
 def attestation(self,id):
  with SessionLocal() as s:
   x=s.get(JourneyRecoveryDeploymentAttestationRow,id)
   if not x:raise ValueError('ATTESTATION_NOT_FOUND')
   return {'deployment_attestation_id':x.deployment_attestation_id,'release_manifest_id':x.release_manifest_id,'environment':x.environment,'runtime_instance':x.runtime_instance,'expected_fingerprint':x.expected_fingerprint,'observed_fingerprint':x.observed_fingerprint,'state':x.state,'supplier_fact_unchanged':x.supplier_fact_unchanged}
 def verification(self,id):
  with SessionLocal() as s:
   x=s.get(JourneyRecoveryReleaseVerificationRow,id)
   if not x:raise ValueError('VERIFICATION_NOT_FOUND')
   return {'release_verification_id':x.release_verification_id,'release_manifest_id':x.release_manifest_id,'environment':x.environment,'attestation_id':x.attestation_id,'smoke_test':x.smoke_test_json,'health_slo':x.health_slo_json,'state':x.state,'action':x.action,'supplier_fact_unchanged':x.supplier_fact_unchanged}
 def status(self,environment='PROD'):
  with SessionLocal() as s:
   a=s.execute(select(JourneyRecoveryDeploymentAttestationRow).where(JourneyRecoveryDeploymentAttestationRow.environment==environment).order_by(JourneyRecoveryDeploymentAttestationRow.attested_at.desc())).scalars().first();v=s.execute(select(JourneyRecoveryReleaseVerificationRow).where(JourneyRecoveryReleaseVerificationRow.environment==environment).order_by(JourneyRecoveryReleaseVerificationRow.verified_at.desc())).scalars().first();return {'environment':environment,'expected_fingerprint':self.expected_fingerprint(environment),'latest_attestation':self.attestation(a.deployment_attestation_id) if a else None,'latest_verification':self.verification(v.release_verification_id) if v else None}
recovery_runtime_verification_service=RecoveryRuntimeVerificationService()
