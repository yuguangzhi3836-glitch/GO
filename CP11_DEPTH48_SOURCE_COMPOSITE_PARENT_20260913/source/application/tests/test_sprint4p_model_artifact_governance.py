import os, pytest
from sqlalchemy import delete
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_risk_forecast_calibration import recovery_risk_forecast_calibration_service as cal
from go_hotel.journey.recovery_forecast_model_promotion import recovery_forecast_model_promotion_service as promo
from go_hotel.journey.recovery_forecast_statistical_promotion import recovery_forecast_statistical_promotion_service as stat
from go_hotel.journey.recovery_forecast_training_governance import recovery_forecast_training_governance_service as train
from go_hotel.journey.recovery_forecast_artifact_governance import recovery_forecast_artifact_governance_service as art

KEY_REF='builder://engineering'
os.environ['GO_MODEL_BUILD_SIGNING_KEY_BUILDER___ENGINEERING']='sprint4p-secret'

def clean():
    with SessionLocal() as s:
        for m in [JourneyRecoveryForecastArtifactGovernanceEventRow,JourneyRecoveryForecastArtifactIntegrityAssessmentRow,JourneyRecoveryForecastArtifactPromotionBindingRow,JourneyRecoveryForecastBuildAttestationRow,JourneyRecoveryForecastArtifactSbomRow,JourneyRecoveryForecastModelArtifactRow,JourneyRecoveryForecastArtifactPolicyRow,JourneyRecoveryForecastTrainingGovernanceEventRow,JourneyRecoveryForecastModelBuildEligibilityRow,JourneyRecoveryForecastReproducibilityCheckRow,JourneyRecoveryForecastTrainingManifestRow,JourneyRecoveryForecastTrainingLineageRow,JourneyRecoveryForecastTrainingDataQualityRow,JourneyRecoveryForecastTrainingDatasetSnapshotRow,JourneyRecoveryForecastFeatureVersionRow,JourneyRecoveryForecastTrainingPolicyRow,JourneyRecoveryForecastPromotionPolicyRow,JourneyRecoveryForecastModelRoleRow,JourneyRecoveryRiskForecastModelVersionRow]:
            try:s.execute(delete(m))
            except Exception:pass
        s.commit()

def setup_models():
    champ=cal.create_model('risk-v','PROD','deterministic',{'growth_multiplier':1},{'growth_multiplier':1.5},2,100,1,1,1,100,'maker')
    cal.approve_model(champ['risk_forecast_model_version_id'],'a1');cal.approve_model(champ['risk_forecast_model_version_id'],'a2');promo.assign_role('PROD',champ['risk_forecast_model_version_id'],'CHAMPION')
    chal=cal.create_model('risk-v','PROD','deterministic',{'growth_multiplier':.9},{'growth_multiplier':1.4},2,100,1,1,1,100,'maker2')
    cal.approve_model(chal['risk_forecast_model_version_id'],'b1');cal.approve_model(chal['risk_forecast_model_version_id'],'b2');promo.assign_role('PROD',chal['risk_forecast_model_version_id'],'CHALLENGER')
    return champ,chal

def setup_training(chal_id):
    p=train.create_policy('PROD',2,.1,.1,.1,True,'training-maker');train.approve_policy(p['forecast_training_policy_id'],'t1');train.approve_policy(p['forecast_training_policy_id'],'t2')
    f=train.register_feature('PROD','risk_signal','float',{'source':'kri','transform':'identity'})
    ds=train.snapshot_dataset('PROD','forecast-training',[{'risk_signal':1.0,'label':0},{'risk_signal':2.0,'label':1},{'risk_signal':3.0,'label':1}],[f['forecast_feature_version_id']],['warehouse://risk'])
    train.assess_data_quality(ds['training_dataset_snapshot_id'],0,0,0,{'report':'dq'})
    l=train.create_lineage('PROD',chal_id,ds['training_dataset_snapshot_id'])
    m=train.create_manifest(l['forecast_training_lineage_id'],'git://forecast@abc','a'*64,{'growth_multiplier':.9},42)
    train.check_reproducibility(m['forecast_training_manifest_id'],'a'*64,{'growth_multiplier':.9},42,'artifact://repro')
    train.evaluate_build(chal_id)
    return m

def setup_artifact_policy():
    p=art.create_policy('PROD',True,True,True,['MODEL_BUNDLE'],[KEY_REF],'artifact-maker');art.approve_policy(p['forecast_artifact_policy_id'],'p1');art.approve_policy(p['forecast_artifact_policy_id'],'p2');return p

def register_good(chal_id,manifest):
    a=art.register_artifact('PROD',chal_id,manifest['forecast_training_manifest_id'],'registry://models/challenger-v1','MODEL_BUNDLE','b'*64,4096,'go-forecast-models')
    sb=art.attach_sbom(a['forecast_model_artifact_id'],'SPDX-LITE',[{'name':'numpy','version':'2.0'},{'name':'go-forecast','version':'1'}],{'source':'build://4p'})
    sig=art.sign_for_engineering(a['forecast_model_artifact_id'],'builder-01',KEY_REF)
    at=art.attest_build(a['forecast_model_artifact_id'],'builder-01',KEY_REF,sig,'attestation://verified')
    integ=art.assess_integrity(a['forecast_model_artifact_id'],'b'*64,manifest['build_hash'],'registry-scan://pass')
    bind=art.bind_for_promotion(a['forecast_model_artifact_id'])
    return a,sb,at,integ,bind

def test_artifact_policy_requires_maker_checker():
    clean();p=art.create_policy('PROD',actor='maker')
    with pytest.raises(ValueError):art.approve_policy(p['forecast_artifact_policy_id'],'maker')
    art.approve_policy(p['forecast_artifact_policy_id'],'x');assert art.approve_policy(p['forecast_artifact_policy_id'],'y')['state']=='ACTIVE'

def test_artifact_registry_binds_reproducible_4o_build_and_package_format():
    clean();_,chal=setup_models();m=setup_training(chal['risk_forecast_model_version_id']);setup_artifact_policy()
    with pytest.raises(ValueError,match='MODEL_PACKAGE_FORMAT_NOT_ALLOWED'):art.register_artifact('PROD',chal['risk_forecast_model_version_id'],m['forecast_training_manifest_id'],'registry://x','PICKLE','b'*64,100)
    a=art.register_artifact('PROD',chal['risk_forecast_model_version_id'],m['forecast_training_manifest_id'],'registry://x','MODEL_BUNDLE','b'*64,100)
    assert a['build_hash']==m['build_hash'] and a['artifact_digest']=='b'*64

def test_sbom_and_provenance_are_digest_bound_to_artifact():
    clean();_,chal=setup_models();m=setup_training(chal['risk_forecast_model_version_id']);setup_artifact_policy();a=art.register_artifact('PROD',chal['risk_forecast_model_version_id'],m['forecast_training_manifest_id'],'registry://x','MODEL_BUNDLE','b'*64,100)
    sb=art.attach_sbom(a['forecast_model_artifact_id'],'SPDX-LITE',[{'name':'lib','version':'1'}],{'builder':'ci'})
    assert len(sb['sbom_digest'])==64 and sb['forecast_model_artifact_id']==a['forecast_model_artifact_id']

def test_invalid_signed_build_attestation_is_rejected_from_promotion_binding():
    clean();_,chal=setup_models();m=setup_training(chal['risk_forecast_model_version_id']);setup_artifact_policy();a=art.register_artifact('PROD',chal['risk_forecast_model_version_id'],m['forecast_training_manifest_id'],'registry://x','MODEL_BUNDLE','b'*64,100);art.attach_sbom(a['forecast_model_artifact_id'],'SPDX-LITE',[{'name':'lib'}])
    at=art.attest_build(a['forecast_model_artifact_id'],'builder-01',KEY_REF,'0'*64,'attestation://bad');assert at['verification_state']=='INVALID'
    art.assess_integrity(a['forecast_model_artifact_id'],'b'*64,m['build_hash'],'scan://pass')
    with pytest.raises(ValueError,match='VERIFIED_BUILD_ATTESTATION_REQUIRED'):art.bind_for_promotion(a['forecast_model_artifact_id'])

def test_signed_attestation_integrity_and_promotion_binding_form_supply_chain():
    clean();_,chal=setup_models();m=setup_training(chal['risk_forecast_model_version_id']);setup_artifact_policy();a,sb,at,integ,bind=register_good(chal['risk_forecast_model_version_id'],m)
    assert at['verification_state']=='VERIFIED' and integ['integrity_state']=='PASS' and bind['binding_state']=='ACTIVE'
    assert bind['build_hash']==m['build_hash'] and bind['artifact_digest']==a['artifact_digest']

def test_tamper_detection_invalidates_4l_backtest_even_after_previous_pass():
    clean();champ,chal=setup_models();m=setup_training(chal['risk_forecast_model_version_id']);setup_artifact_policy();a,_,_,_,_=register_good(chal['risk_forecast_model_version_id'],m)
    assert promo.backtest('PROD',champ['risk_forecast_model_version_id'],chal['risk_forecast_model_version_id'])['state']=='COMPLETED'
    bad=art.assess_integrity(a['forecast_model_artifact_id'],'c'*64,m['build_hash'],'scan://tampered');assert bad['integrity_state']=='TAMPERED'
    with pytest.raises(ValueError,match='MODEL_ARTIFACT_INTEGRITY_PASS_REQUIRED'):promo.backtest('PROD',champ['risk_forecast_model_version_id'],chal['risk_forecast_model_version_id'])

def test_4l_and_4m_cannot_bypass_signed_artifact_gate_when_policy_active():
    clean();champ,chal=setup_models();m=setup_training(chal['risk_forecast_model_version_id']);setup_artifact_policy()
    with pytest.raises(ValueError,match='SIGNED_MODEL_ARTIFACT_PROMOTION_BINDING_REQUIRED'):promo.backtest('PROD',champ['risk_forecast_model_version_id'],chal['risk_forecast_model_version_id'])
    sp=stat.create_policy('PROD',2,.5,0,1,['ALL'],10,100,100,100,'stat-maker');stat.approve_policy(sp['forecast_promotion_policy_id'],'s1');stat.approve_policy(sp['forecast_promotion_policy_id'],'s2')
    with pytest.raises(ValueError,match='SIGNED_MODEL_ARTIFACT_PROMOTION_BINDING_REQUIRED'):stat.promote('PROD',chal['risk_forecast_model_version_id'],{'ticket':'MRM-4P'})

def test_supplier_fact_boundary():
    clean();_,chal=setup_models();m=setup_training(chal['risk_forecast_model_version_id']);setup_artifact_policy();a,sb,at,integ,bind=register_good(chal['risk_forecast_model_version_id'],m)
    assert all(x['supplier_fact_unchanged'] for x in [a,sb,at,integ,bind])
