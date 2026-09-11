import pytest
from go_hotel.journey.recovery_release_governance import recovery_release_governance_service as rel
from go_hotel.journey.recovery_runtime_verification import recovery_runtime_verification_service as verify
from go_hotel.journey.recovery_runtime_observability import recovery_runtime_observability_service as legacy
from go_hotel.journey.recovery_runtime_telemetry_governance import recovery_runtime_telemetry_governance_service as svc

def prod_release(key):
 c=rel.create_config_version(key,'GENERIC','GLOBAL','*','maker',{'x':1})
 s=rel.create_manifest('DEV','STAGING',[c['config_version_id']],'maker');rel.dry_run(s['release_manifest_id'],'maker');rel.approve(s['release_manifest_id'],'checker');rel.promote(s['release_manifest_id'],'deployer')
 p=rel.create_manifest('STAGING','PROD',[c['config_version_id']],'maker');rel.dry_run(p['release_manifest_id'],'maker');rel.attach_staging_evidence(p['release_manifest_id'],'e://staging','pass','maker');rel.approve(p['release_manifest_id'],'checker');out=rel.promote(p['release_manifest_id'],'deployer')
 a=verify.attest(out['release_manifest_id'],'PROD','runtime-u',verify.expected_fingerprint('PROD'),'runtime');verify.verify(a['deployment_attestation_id'],{'passed':True},{'passed':True},'runtime')
 return out

def governed_source(key='prom-main',config=None):
 return svc.register_source(key,'PROMETHEUS','PROD','ops',config or {'max_freshness_seconds':300,'min_request_count':1,'required_metric_fields':['request_count','error_count','slo_target']},'GOVERNED','prom://prod')

def active_policy(key='prod-slo'):
 return svc.create_slo_policy(key,'PROD','sre',.999,[{'minutes':5,'burn_threshold':14.4,'watch_threshold':2.0},{'minutes':30,'burn_threshold':6.0,'watch_threshold':2.0},{'minutes':60,'burn_threshold':3.0,'watch_threshold':1.5}],.8,1)

def test_governed_source_has_stable_provenance_and_state_gate():
 s=governed_source();assert len(s['source_fingerprint'])==64 and s['state']=='ACTIVE'
 svc.set_source_state(s['telemetry_source_id'],'SUSPENDED','ops')
 with pytest.raises(ValueError,match='TELEMETRY_SOURCE_NOT_ACTIVE'):svc.ingest(s['telemetry_source_id'],'r1',{'request_count':10,'error_count':0,'slo_target':.999},'telemetry')

def test_quality_gate_blocks_strong_action_even_when_burn_rate_is_bad():
 prod_release('3u.quality');src=governed_source(config={'max_freshness_seconds':300,'min_request_count':10000,'required_metric_fields':['request_count','error_count','slo_target']});active_policy()
 out=svc.ingest(src['telemetry_source_id'],'r2',{'request_count':1000,'error_count':100,'slo_target':.999},'telemetry');assert out['quality']['state']=='FAIL'
 a=svc.assess('PROD','controller');assert a['state']=='INSUFFICIENT_TELEMETRY' and a['action']=='OBSERVE_ONLY';assert legacy.control('PROD')['promotion_frozen'] is False;assert a['rollback_recommendation'] is None

def test_multi_window_breach_with_good_telemetry_freezes_and_recommends():
 prod_release('3u.breach');src=governed_source();active_policy()
 out=svc.ingest(src['telemetry_source_id'],'r3',{'request_count':1000,'error_count':50,'slo_target':.999,'latency_p95_ms':1400},'telemetry');assert out['quality']['state']=='PASS'
 a=svc.assess('PROD','controller');assert a['state']=='BREACH';assert a['action']=='FREEZE_PROMOTION_AND_RECOMMEND_ROLLBACK';assert legacy.control('PROD')['promotion_frozen'] is True;assert a['rollback_recommendation']['state']=='OPEN';assert len(a['anomaly']['windows'])==3

def test_incident_correlation_carries_release_attestation_verification_and_quality_evidence():
 p=prod_release('3u.correlation');src=governed_source();active_policy();svc.ingest(src['telemetry_source_id'],'r4',{'request_count':1000,'error_count':20,'slo_target':.999},'telemetry');a=svc.assess('PROD','controller');c=a['incident_correlation']
 assert c['release_manifest_id']==p['release_manifest_id'];assert c['deployment_attestation_id'] and c['release_verification_id'];assert c['confidence']=='HIGH';assert c['evidence']['telemetry_quality_gate']['state']=='PASS';assert c['supplier_fact_unchanged'] is True

def test_policy_requires_multiple_valid_windows():
 with pytest.raises(ValueError,match='INVALID_SLO_WINDOWS'):svc.create_slo_policy('bad','PROD','ops',.999,[{'minutes':5,'burn_threshold':14.4}],.8,1)

def test_status_exposes_source_quality_policy_correlation_and_release_safety():
 prod_release('3u.status');src=governed_source();p=active_policy();svc.ingest(src['telemetry_source_id'],'r5',{'request_count':100000,'error_count':1,'slo_target':.999},'telemetry');svc.assess('PROD','controller');st=svc.status('PROD')
 assert st['active_policy']['slo_policy_id']==p['slo_policy_id'];assert st['sources'][0]['telemetry_source_id']==src['telemetry_source_id'];assert st['latest_quality']['state']=='PASS';assert st['latest_correlation'];assert 'release_safety' in st

def test_legacy_3t_assessment_cannot_bypass_governed_telemetry_gate():
 governed_source('prom-legacy-block');active_policy('prod-slo-legacy-block')
 with pytest.raises(ValueError,match='GOVERNED_TELEMETRY_ASSESSMENT_REQUIRED'):legacy.assess('PROD','legacy-controller')
