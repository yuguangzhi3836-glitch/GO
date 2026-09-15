import pytest
from go_hotel.journey.recovery_release_governance import recovery_release_governance_service as rel
from go_hotel.journey.recovery_runtime_verification import recovery_runtime_verification_service as verify
from go_hotel.journey.recovery_runtime_observability import recovery_runtime_observability_service as svc

def prod_release(key='safety.policy',rollback=None):
 c=rel.create_config_version(key,'GENERIC','GLOBAL','*','maker',{'max_attempts':8})
 s=rel.create_manifest('DEV','STAGING',[c['config_version_id']],'maker');rel.dry_run(s['release_manifest_id'],'maker');rel.approve(s['release_manifest_id'],'checker');rel.promote(s['release_manifest_id'],'deployer')
 p=rel.create_manifest('STAGING','PROD',[c['config_version_id']],'maker',rollback);rel.dry_run(p['release_manifest_id'],'maker');rel.attach_staging_evidence(p['release_manifest_id'],'e://staging','pass','maker');rel.approve(p['release_manifest_id'],'checker');out=rel.promote(p['release_manifest_id'],'deployer')
 a=verify.attest(out['release_manifest_id'],'PROD','runtime-safe',verify.expected_fingerprint('PROD'),'runtime');verify.verify(a['deployment_attestation_id'],{'passed':True},{'passed':True},'runtime')
 return out

def test_healthy_runtime_keeps_promotion_open():
 prod_release('safety.healthy');svc.ingest('PROD','r1',{'request_count':100000,'error_count':10,'slo_target':.999,'latency_p95_ms':120},'telemetry');a=svc.assess('PROD','controller');assert a['state']=='HEALTHY' and a['action']=='NONE' and svc.control('PROD')['promotion_frozen'] is False

def test_burn_rate_breach_auto_freezes_and_recommends_not_executes_rollback():
 p=prod_release('safety.breach');svc.ingest('PROD','r2',{'request_count':1000,'error_count':50,'slo_target':.999,'latency_p95_ms':1800},'telemetry');a=svc.assess('PROD','controller');assert a['state']=='BREACH' and a['action']=='FREEZE_PROMOTION_AND_RECOMMEND_ROLLBACK';assert svc.control('PROD')['promotion_frozen'] is True;assert a['rollback_recommendation']['state']=='OPEN';assert rel.manifest(p['release_manifest_id'])['state']=='PROMOTED'

def test_frozen_prod_blocks_new_promotion():
 prod_release('safety.freeze.base');svc.ingest('PROD','r3',{'request_count':1000,'error_count':50,'slo_target':.999},'telemetry');svc.assess('PROD','controller')
 c=rel.create_config_version('safety.freeze.next','GENERIC','GLOBAL','*','maker',{'x':2});s=rel.create_manifest('DEV','STAGING',[c['config_version_id']],'maker');rel.dry_run(s['release_manifest_id'],'maker');rel.approve(s['release_manifest_id'],'checker');rel.promote(s['release_manifest_id'],'deployer');p=rel.create_manifest('STAGING','PROD',[c['config_version_id']],'maker');rel.dry_run(p['release_manifest_id'],'maker');rel.attach_staging_evidence(p['release_manifest_id'],'e://ok','pass','maker');rel.approve(p['release_manifest_id'],'checker')
 with pytest.raises(ValueError,match='PROMOTION_FROZEN_BY_RUNTIME_SAFETY'):rel.promote(p['release_manifest_id'],'deployer')

def test_release_correlated_anomaly_requires_verified_release():
 prod_release('safety.correlation');svc.ingest('PROD','r4',{'request_count':1000,'error_count':10,'slo_target':.999},'telemetry');a=svc.assess('PROD','controller');assert a['release_correlated_anomaly'] is True

def test_unfreeze_requires_healthy_assessment_and_evidence():
 prod_release('safety.unfreeze');svc.ingest('PROD','r5',{'request_count':1000,'error_count':50,'slo_target':.999},'telemetry');svc.assess('PROD','controller')
 with pytest.raises(ValueError,match='RECOVERY_EVIDENCE_REQUIRED'):svc.unfreeze('PROD','ops','')
 # isolate from prior high-burn samples by making policy thresholds permissive for a fresh healthy assessment
 old1,old2=svc.SHORT_BURN_THRESHOLD,svc.LONG_BURN_THRESHOLD;svc.SHORT_BURN_THRESHOLD=100;svc.LONG_BURN_THRESHOLD=100
 try:
  svc.ingest('PROD','r5',{'request_count':1000000,'error_count':0,'slo_target':.999},'telemetry');svc.assess('PROD','controller')
  out=svc.unfreeze('PROD','ops','incident://resolved');assert out['promotion_frozen'] is False
 finally:svc.SHORT_BURN_THRESHOLD,svc.LONG_BURN_THRESHOLD=old1,old2

def test_rollback_recommendation_acknowledgement_is_governance_only():
 p=prod_release('safety.ack');svc.ingest('PROD','r6',{'request_count':1000,'error_count':50,'slo_target':.999},'telemetry');a=svc.assess('PROD','controller');r=svc.acknowledge_recommendation(a['rollback_recommendation']['rollback_recommendation_id'],'ops');assert r['state']=='ACKNOWLEDGED' and r['supplier_fact_unchanged'] is True;assert rel.manifest(p['release_manifest_id'])['state']=='PROMOTED'
