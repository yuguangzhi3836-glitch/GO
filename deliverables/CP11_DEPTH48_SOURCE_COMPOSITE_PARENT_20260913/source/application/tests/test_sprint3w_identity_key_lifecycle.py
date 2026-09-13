import os,pytest
from datetime import datetime,timezone,timedelta
from go_hotel.journey.recovery_runtime_telemetry_trust import recovery_runtime_telemetry_trust_service as trust,env_key
from go_hotel.journey.recovery_runtime_identity_lifecycle import recovery_runtime_identity_lifecycle_service as life
from go_hotel.journey.recovery_runtime_telemetry_governance import recovery_runtime_telemetry_governance_service as telemetry
from go_hotel.journey.recovery_release_governance import recovery_release_governance_service as rel
from go_hotel.journey.recovery_runtime_verification import recovery_runtime_verification_service as verify
from go_hotel.journey.recovery_runtime_observability import recovery_runtime_observability_service as safety

def prod_release(key):
 c=rel.create_config_version(key,'GENERIC','GLOBAL','*','maker',{'x':1});s=rel.create_manifest('DEV','STAGING',[c['config_version_id']],'maker');rel.dry_run(s['release_manifest_id'],'maker');rel.approve(s['release_manifest_id'],'checker');rel.promote(s['release_manifest_id'],'deployer');p=rel.create_manifest('STAGING','PROD',[c['config_version_id']],'maker');rel.dry_run(p['release_manifest_id'],'maker');rel.attach_staging_evidence(p['release_manifest_id'],'e://staging','pass','maker');rel.approve(p['release_manifest_id'],'checker');out=rel.promote(p['release_manifest_id'],'deployer');a=verify.attest(out['release_manifest_id'],'PROD','runtime-w',verify.expected_fingerprint('PROD'),'runtime');verify.verify(a['deployment_attestation_id'],{'passed':True},{'passed':True},'runtime');return out

def setup_env():
 telemetry.create_slo_policy('slo-w','PROD','sre',.999,[{'minutes':5,'burn_threshold':14.4,'watch_threshold':2.0},{'minutes':30,'burn_threshold':6.0,'watch_threshold':2.0},{'minutes':60,'burn_threshold':3.0,'watch_threshold':1.5}],.8,2)
 trust.create_policy('auto-w','PROD','sre','HIGH',2,120,300,True,True,{})
 w=trust.register_identity('workload-w','WORKLOAD','PROD','spiffe://go/prod/runtime','workload-w-key','sre')
 c1=trust.register_identity('collector-w1','COLLECTOR','PROD','spiffe://go/prod/collector-1','collector-w1-k1','sre')
 c2=trust.register_identity('collector-w2','COLLECTOR','PROD','spiffe://go/prod/collector-2','collector-w2-k1','sre')
 for ref,val in [('collector-w1-k1','one-old'),('collector-w1-k2','one-new'),('collector-w2-k1','two-old')]:os.environ[env_key(ref)]=val
 s1=telemetry.register_source('prom-w1','PROMETHEUS','PROD','ops',{'max_freshness_seconds':300,'min_request_count':1,'required_metric_fields':['request_count','error_count','slo_target']},'GOVERNED','prom://w1')
 s2=telemetry.register_source('otel-w2','OTEL','PROD','ops',{'max_freshness_seconds':300,'min_request_count':1,'required_metric_fields':['request_count','error_count','slo_target']},'GOVERNED','otel://w2')
 return w,c1,c2,s1,s2

def sign_and_ingest(src,w,c,key_ref,seq,nonce,errors=0,ts=None):
 ts=ts or datetime.now(timezone.utc);m={'request_count':1000,'error_count':errors,'slo_target':.999,'latency_p95_ms':100}
 sig=trust.sign_for_engineering(key_ref,source_id=src['telemetry_source_id'],workload_identity_id=w['runtime_identity_id'],collector_identity_id=c['runtime_identity_id'],environment='PROD',nonce=nonce,sequence_no=seq,observed_at=ts,metrics=m)
 return trust.ingest_signed(src['telemetry_source_id'],w['runtime_identity_id'],c['runtime_identity_id'],'runtime-w',m,nonce,seq,ts,sig,'telemetry')

def test_identity_registration_bootstraps_key_version_one():
 _,c1,_,_,_=setup_env();ks=life.key_versions(c1['runtime_identity_id']);assert len(ks)==1;assert ks[0]['version_no']==1;assert ks[0]['state']=='ACTIVE';assert ks[0]['key_ref']=='collector-w1-k1'

def test_signed_key_rotation_dual_key_overlap_accepts_old_and_new():
 w,c1,_,s1,_=setup_env();old=life.key_versions(c1['runtime_identity_id'])[0];vf=datetime.now(timezone.utc);sig=life.sign_transition_for_engineering('collector-w1-k1',identity_id=c1['runtime_identity_id'],old_key_version_id=old['telemetry_key_version_id'],new_key_ref='collector-w1-k2',valid_from=vf,overlap_seconds=300);r=life.rotate_key(c1['runtime_identity_id'],'collector-w1-k2',sig,'sre',300,vf,'e://rotation');assert r['new_key_version']['version_no']==2
 a=sign_and_ingest(s1,w,c1,'collector-w1-k1',1,'old-overlap');b=sign_and_ingest(s1,w,c1,'collector-w1-k2',2,'new-overlap');assert a['verification_state']==b['verification_state']=='VERIFIED';assert life.status('PROD')['trust_cache_epoch']>=1

def test_invalid_transition_signature_is_blocked():
 _,c1,_,_,_=setup_env();
 with pytest.raises(ValueError,match='KEY_TRANSITION_SIGNATURE_INVALID'):life.rotate_key(c1['runtime_identity_id'],'collector-w1-k2','bad','sre',300,datetime.now(timezone.utc),'e://bad')

def test_revocation_propagates_and_excludes_historical_telemetry_from_quorum():
 prod_release('3w-revoke');w,c1,c2,s1,s2=setup_env();sign_and_ingest(s1,w,c1,'collector-w1-k1',1,'r1',50);sign_and_ingest(s2,w,c2,'collector-w2-k1',1,'r2',50);assert trust.assess_trust('PROD')['state']=='ALLOW_AUTOMATION';rv=life.revoke_identity(c1['runtime_identity_id'],'KEY_COMPROMISE','e://incident','security');assert rv['propagation_state']=='PROPAGATED';t=trust.assess_trust('PROD');assert t['state']=='HUMAN_REVIEW_ONLY';assert t['verified_source_count']==1;assert t['evidence']['excluded_envelopes']>=1

def test_compromised_collector_quarantine_immediately_blocks_ingest_and_automation():
 prod_release('3w-quarantine');w,c1,c2,s1,s2=setup_env();sign_and_ingest(s1,w,c1,'collector-w1-k1',1,'q1',50);sign_and_ingest(s2,w,c2,'collector-w2-k1',1,'q2',50);inc=life.open_security_incident(c1['runtime_identity_id'],'SEV1','COLLECTOR_COMPROMISE',{'ticket':'SEC-1'},'security');assert inc['quarantine_state']=='QUARANTINED';t=trust.assess_trust('PROD');assert t['state']=='HUMAN_REVIEW_ONLY';assert safety.control('PROD')['promotion_frozen'] is False
 with pytest.raises(ValueError,match='RUNTIME_IDENTITY_NOT_ACTIVE|RUNTIME_IDENTITY_QUARANTINED'):sign_and_ingest(s1,w,c1,'collector-w1-k1',2,'q3',50)

def test_revoke_immediately_revokes_all_current_keys_and_invalidates_cache():
 _,c1,_,_,_=setup_env();inc=life.open_security_incident(c1['runtime_identity_id'],'SEV1','CREDENTIAL_EXFILTRATION',{'forensic_ref':'F-1'},'security',True);assert inc['identity_state']=='REVOKED';assert all(k['state']=='REVOKED' for k in life.key_versions(c1['runtime_identity_id']));assert life.status('PROD')['trust_cache_epoch']>=1

def test_containment_keeps_identity_quarantined_until_separate_remediation():
 _,c1,_,_,_=setup_env();inc=life.open_security_incident(c1['runtime_identity_id'],'SEV2','SUSPECTED_COMPROMISE',{},'security');out=life.contain_incident(inc['telemetry_security_incident_id'],{'isolated':True},'security');assert out['state']=='CONTAINED';assert out['quarantine_state']=='QUARANTINED';assert trust.identity(c1['runtime_identity_id'])['state']=='SUSPENDED'

def test_zero_overlap_retires_old_key_immediately_and_old_signature_fails():
 w,c1,_,s1,_=setup_env();old=life.key_versions(c1['runtime_identity_id'])[0];vf=datetime.now(timezone.utc);sig=life.sign_transition_for_engineering('collector-w1-k1',identity_id=c1['runtime_identity_id'],old_key_version_id=old['telemetry_key_version_id'],new_key_ref='collector-w1-k2',valid_from=vf,overlap_seconds=0);life.rotate_key(c1['runtime_identity_id'],'collector-w1-k2',sig,'sre',0,vf,'e://rotation-zero');ks=life.key_versions(c1['runtime_identity_id']);assert ks[0]['state']=='RETIRED';assert ks[1]['state']=='ACTIVE'
 with pytest.raises(ValueError,match='TELEMETRY_SIGNATURE_INVALID'):sign_and_ingest(s1,w,c1,'collector-w1-k1',1,'old-retired')
 assert sign_and_ingest(s1,w,c1,'collector-w1-k2',1,'new-active')['verification_state']=='VERIFIED'
