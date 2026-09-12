import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4q_test.db')
os.environ['GO_MODEL_BUILD_SIGNING_KEY_BUILDER___ENGINEERING']='sprint4q-secret'
from datetime import datetime,timezone
import pytest
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_risk_forecast_calibration import recovery_risk_forecast_calibration_service as cal
from go_hotel.journey.recovery_forecast_model_promotion import recovery_forecast_model_promotion_service as promo
from go_hotel.journey.recovery_forecast_training_governance import recovery_forecast_training_governance_service as train
from go_hotel.journey.recovery_forecast_artifact_governance import recovery_forecast_artifact_governance_service as art
from go_hotel.journey.recovery_forecast_serving_governance import recovery_forecast_serving_governance_service as serving
from go_hotel.journey.recovery_enterprise_risk_forecast import recovery_enterprise_risk_forecast_service as forecast
KEY_REF='builder://engineering'

def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine)

def setup_artifact():
    m=cal.create_model('risk-v','PROD','deterministic',{'growth_multiplier':1},{'growth_multiplier':1.5},2,100,1,1,1,100,'maker');cal.approve_model(m['risk_forecast_model_version_id'],'a1');cal.approve_model(m['risk_forecast_model_version_id'],'a2');promo.assign_role('PROD',m['risk_forecast_model_version_id'],'CHALLENGER')
    tp=train.create_policy('PROD',2,.1,.1,.1,True,'training-maker');train.approve_policy(tp['forecast_training_policy_id'],'t1');train.approve_policy(tp['forecast_training_policy_id'],'t2')
    f=train.register_feature('PROD','risk_signal','float',{'source':'kri','transform':'identity'});ds=train.snapshot_dataset('PROD','forecast-training',[{'risk_signal':1.0,'label':0},{'risk_signal':2.0,'label':1},{'risk_signal':3.0,'label':1}],[f['forecast_feature_version_id']],['warehouse://risk']);train.assess_data_quality(ds['training_dataset_snapshot_id'],0,0,0,{'report':'dq'});l=train.create_lineage('PROD',m['risk_forecast_model_version_id'],ds['training_dataset_snapshot_id']);mf=train.create_manifest(l['forecast_training_lineage_id'],'git://forecast@abc','a'*64,{'growth_multiplier':1},42);train.check_reproducibility(mf['forecast_training_manifest_id'],'a'*64,{'growth_multiplier':1},42,'artifact://repro');train.evaluate_build(m['risk_forecast_model_version_id'])
    ap=art.create_policy('PROD',True,True,True,['MODEL_BUNDLE'],[KEY_REF],'artifact-maker');art.approve_policy(ap['forecast_artifact_policy_id'],'p1');art.approve_policy(ap['forecast_artifact_policy_id'],'p2')
    a=art.register_artifact('PROD',m['risk_forecast_model_version_id'],mf['forecast_training_manifest_id'],'registry://models/model-v1','MODEL_BUNDLE','b'*64,4096);art.attach_sbom(a['forecast_model_artifact_id'],'SPDX-LITE',[{'name':'go-forecast','version':'1'}]);sig=art.sign_for_engineering(a['forecast_model_artifact_id'],'builder-01',KEY_REF);art.attest_build(a['forecast_model_artifact_id'],'builder-01',KEY_REF,sig,'attestation://verified');art.assess_integrity(a['forecast_model_artifact_id'],'b'*64,mf['build_hash'],'scan://pass');art.bind_for_promotion(a['forecast_model_artifact_id'])
    promo.assign_role('PROD',m['risk_forecast_model_version_id'],'CHAMPION')
    return m,a,mf

def activate_serving_policy():
    p=serving.create_policy('PROD',actor='maker');serving.approve_policy(p['forecast_serving_policy_id'],'q1');return serving.approve_policy(p['forecast_serving_policy_id'],'q2')

def good_runtime(m,a,mf,deployment='forecast-prod'):
    b=serving.bind_deployment('PROD',m['risk_forecast_model_version_id'],a['forecast_model_artifact_id'],deployment,'deploy://ticket')
    r=serving.register_runtime_identity('PROD',deployment,'pod://forecast-1',m['risk_forecast_model_version_id'],a['forecast_model_artifact_id'])
    at=serving.attest_serving(r['forecast_runtime_model_identity_id'],a['artifact_digest'],mf['build_hash'],r['runtime_model_fingerprint'],'serving://verified')
    return b,r,at

def setup_forecast_prereqs():
    with SessionLocal() as s:
        s.add(JourneyRecoveryRiskAppetiteEnvelopeRow(risk_appetite_envelope_id='app',appetite_key='app',version_no=1,environment='PROD',max_current_exposure_points=300,max_stressed_exposure_points=450,min_headroom_points=50,min_capacity_buffer_pct=10,max_sensitivity_pct=150,requested_by='x',board_approver_one='a',board_approver_two='b',state='ACTIVE',created_at=datetime.now(timezone.utc),supplier_fact_unchanged=True));s.commit()
    p=forecast.create_policy('f','PROD',80,95,10,'maker');forecast.approve_policy(p['risk_forecast_policy_id'],'b1');forecast.approve_policy(p['risk_forecast_policy_id'],'b2')

def test_serving_policy_requires_maker_checker():
    p=serving.create_policy('PROD',actor='maker')
    with pytest.raises(ValueError,match='MAKER_CHECKER'):serving.approve_policy(p['forecast_serving_policy_id'],'maker')
    serving.approve_policy(p['forecast_serving_policy_id'],'a');assert serving.approve_policy(p['forecast_serving_policy_id'],'b')['state']=='ACTIVE'

def test_deployment_binding_requires_4p_signed_artifact_binding():
    m,a,mf=setup_artifact();activate_serving_policy()
    b=serving.bind_deployment('PROD',m['risk_forecast_model_version_id'],a['forecast_model_artifact_id'],'forecast-prod','deploy://ticket')
    assert b['expected_artifact_digest']==a['artifact_digest'] and b['expected_build_hash']==mf['build_hash']

def test_runtime_model_fingerprint_is_bound_to_deployment_and_artifact():
    m,a,mf=setup_artifact();activate_serving_policy();b,r,at=good_runtime(m,a,mf)
    assert len(r['runtime_model_fingerprint'])==64 and at['attestation_state']=='VERIFIED'

def test_wrong_loaded_artifact_digest_immediately_blocks_serving():
    m,a,mf=setup_artifact();activate_serving_policy();b=serving.bind_deployment('PROD',m['risk_forecast_model_version_id'],a['forecast_model_artifact_id'],'forecast-prod','deploy://ticket');r=serving.register_runtime_identity('PROD','forecast-prod','pod://forecast-1',m['risk_forecast_model_version_id'],a['forecast_model_artifact_id'])
    at=serving.attest_serving(r['forecast_runtime_model_identity_id'],'c'*64,mf['build_hash'],r['runtime_model_fingerprint'],'serving://mismatch');assert at['attestation_state']=='MISMATCH' and 'LOADED_ARTIFACT_DIGEST_MISMATCH' in at['reason_codes']
    with SessionLocal() as s:
        with pytest.raises(ValueError,match='SERVING_BLOCKED'):serving.assert_runtime_model_eligible_in_session(s,'PROD',m['risk_forecast_model_version_id'])

def test_wrong_runtime_fingerprint_is_fail_safe_blocked():
    m,a,mf=setup_artifact();activate_serving_policy();b=serving.bind_deployment('PROD',m['risk_forecast_model_version_id'],a['forecast_model_artifact_id'],'forecast-prod','deploy://ticket');r=serving.register_runtime_identity('PROD','forecast-prod','pod://forecast-1',m['risk_forecast_model_version_id'],a['forecast_model_artifact_id'])
    at=serving.attest_serving(r['forecast_runtime_model_identity_id'],a['artifact_digest'],mf['build_hash'],'d'*64,'serving://bad-fingerprint');assert 'RUNTIME_MODEL_FINGERPRINT_MISMATCH' in at['reason_codes']

def test_verified_serving_attestation_allows_forecast_runtime_and_mismatch_stops_it():
    m,a,mf=setup_artifact();activate_serving_policy();setup_forecast_prereqs();b,r,at=good_runtime(m,a,mf)
    assert forecast.forecast('PROD',24)['supplier_fact_unchanged'] is True
    serving.attest_serving(r['forecast_runtime_model_identity_id'],'c'*64,mf['build_hash'],r['runtime_model_fingerprint'],'serving://tampered')
    with pytest.raises(ValueError,match='SERVING_BLOCKED'):forecast.forecast('PROD',24)

def test_rollback_lineage_requires_new_verified_runtime_before_release():
    m,a,mf=setup_artifact();activate_serving_policy();b,r,at=good_runtime(m,a,mf)
    serving.attest_serving(r['forecast_runtime_model_identity_id'],'c'*64,mf['build_hash'],r['runtime_model_fingerprint'],'serving://tampered')
    with pytest.raises(ValueError,match='RECOVERY_ATTESTATION_REQUIRED'):serving.release_safety_control('PROD','forecast-prod','release://attempt')
    b2=serving.bind_deployment('PROD',m['risk_forecast_model_version_id'],a['forecast_model_artifact_id'],'forecast-prod','rollback://same-good','ROLLBACK');r2=serving.register_runtime_identity('PROD','forecast-prod','pod://forecast-2',m['risk_forecast_model_version_id'],a['forecast_model_artifact_id']);serving.attest_serving(r2['forecast_runtime_model_identity_id'],a['artifact_digest'],mf['build_hash'],r2['runtime_model_fingerprint'],'serving://recovered')
    assert serving.release_safety_control('PROD','forecast-prod','release://verified')['control_state']=='RELEASED'

def test_supplier_fact_boundary():
    m,a,mf=setup_artifact();activate_serving_policy();b,r,at=good_runtime(m,a,mf)
    assert all(x['supplier_fact_unchanged'] for x in [b,r,at])
