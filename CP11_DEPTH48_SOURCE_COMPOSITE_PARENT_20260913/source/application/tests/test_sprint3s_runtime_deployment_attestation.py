import pytest
from go_hotel.journey.recovery_release_governance import recovery_release_governance_service as rel
from go_hotel.journey.recovery_runtime_verification import recovery_runtime_verification_service as svc

def prod_release(key='runtime.policy',rollback=None):
 c=rel.create_config_version(key,'GENERIC','GLOBAL','*','a',{'max_attempts':8})
 m=rel.create_manifest('DEV','STAGING',[c['config_version_id']],'a');rel.dry_run(m['release_manifest_id'],'a');rel.approve(m['release_manifest_id'],'b');rel.promote(m['release_manifest_id'],'c')
 p=rel.create_manifest('STAGING','PROD',[c['config_version_id']],'a',rollback);rel.dry_run(p['release_manifest_id'],'a');rel.attach_staging_evidence(p['release_manifest_id'],'e://pass','pass','a');rel.approve(p['release_manifest_id'],'b');return rel.promote(p['release_manifest_id'],'c')
def test_runtime_fingerprint_attestation_matches_governed_prod_binding():
 p=prod_release();fp=svc.expected_fingerprint('PROD');a=svc.attest(p['release_manifest_id'],'PROD','runtime-1',fp,'ops');assert a['state']=='MATCHED' and a['expected_fingerprint']==a['observed_fingerprint']
def test_fingerprint_mismatch_fails_health_verification():
 p=prod_release('runtime.mismatch');a=svc.attest(p['release_manifest_id'],'PROD','runtime-2','bad','ops');v=svc.verify(a['deployment_attestation_id'],{'passed':True},{'passed':True},'ops');assert v['state']=='FAILED' and v['action']=='CONTROLLED_ROLLBACK_REQUIRED'
def test_smoke_failure_blocks_release_verification_even_with_matching_fingerprint():
 p=prod_release('runtime.smoke');a=svc.attest(p['release_manifest_id'],'PROD','runtime-3',svc.expected_fingerprint('PROD'),'ops');v=svc.verify(a['deployment_attestation_id'],{'passed':False,'failed':['recovery-read']},{'passed':True},'ops');assert v['state']=='FAILED'
def test_health_slo_failure_requires_controlled_rollback_not_supplier_rollback():
 p=prod_release('runtime.slo');a=svc.attest(p['release_manifest_id'],'PROD','runtime-4',svc.expected_fingerprint('PROD'),'ops');v=svc.verify(a['deployment_attestation_id'],{'passed':True},{'passed':False,'error_rate':0.2},'ops');assert v['action']=='CONTROLLED_ROLLBACK_REQUIRED' and v['supplier_fact_unchanged'] is True
def test_failed_prod_verification_can_trigger_existing_release_rollback():
 v1=prod_release('runtime.rollback');v2=prod_release('runtime.rollback',v1['release_manifest_id']);a=svc.attest(v2['release_manifest_id'],'PROD','runtime-5','bad','ops');v=svc.verify(a['deployment_attestation_id'],{'passed':True},{'passed':True},'ops');out=svc.rollback_on_failure(v['release_verification_id'],'ops2');assert out['rollback_state']=='ROLLED_BACK' and out['supplier_fact_unchanged'] is True
def test_passed_verification_can_be_evidence_sealed_but_failed_cannot():
 p=prod_release('runtime.seal');a=svc.attest(p['release_manifest_id'],'PROD','runtime-6',svc.expected_fingerprint('PROD'),'ops');v=svc.verify(a['deployment_attestation_id'],{'passed':True,'checks':3},{'passed':True,'availability':.999},'ops');seal=svc.seal(v['release_verification_id'],'auditor');assert len(seal['seal_hash'])==64 and seal['supplier_fact_unchanged'] is True
 bad=svc.attest(p['release_manifest_id'],'PROD','runtime-7','bad','ops');fv=svc.verify(bad['deployment_attestation_id'],{'passed':True},{'passed':True},'ops')
 with pytest.raises(ValueError,match='PASSED_VERIFICATION_REQUIRED'):svc.seal(fv['release_verification_id'],'auditor')
