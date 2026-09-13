import pytest
from sqlalchemy import delete
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_risk_forecast_calibration import recovery_risk_forecast_calibration_service as cal
from go_hotel.journey.recovery_forecast_model_promotion import recovery_forecast_model_promotion_service as promo
from go_hotel.journey.recovery_forecast_training_governance import recovery_forecast_training_governance_service as train

def clean():
    with SessionLocal() as s:
        for m in [JourneyRecoveryForecastTrainingGovernanceEventRow,JourneyRecoveryForecastModelBuildEligibilityRow,JourneyRecoveryForecastReproducibilityCheckRow,JourneyRecoveryForecastTrainingManifestRow,JourneyRecoveryForecastTrainingLineageRow,JourneyRecoveryForecastTrainingDataQualityRow,JourneyRecoveryForecastTrainingDatasetSnapshotRow,JourneyRecoveryForecastFeatureVersionRow,JourneyRecoveryForecastTrainingPolicyRow,JourneyRecoveryForecastModelRoleRow,JourneyRecoveryRiskForecastModelVersionRow]:
            try:s.execute(delete(m))
            except Exception:pass
        s.commit()

def setup_models():
    champ=cal.create_model('risk-v','PROD','deterministic',{'growth_multiplier':1},{'growth_multiplier':1.5},2,100,1,1,1,100,'maker')
    cal.approve_model(champ['risk_forecast_model_version_id'],'a1');cal.approve_model(champ['risk_forecast_model_version_id'],'a2');promo.assign_role('PROD',champ['risk_forecast_model_version_id'],'CHAMPION')
    chal=cal.create_model('risk-v','PROD','deterministic',{'growth_multiplier':.9},{'growth_multiplier':1.4},2,100,1,1,1,100,'maker2')
    cal.approve_model(chal['risk_forecast_model_version_id'],'b1');cal.approve_model(chal['risk_forecast_model_version_id'],'b2');promo.assign_role('PROD',chal['risk_forecast_model_version_id'],'CHALLENGER')
    return champ,chal

def setup_policy(min_rows=2):
    p=train.create_policy('PROD',min_rows,.1,.1,.1,True,'policy-maker');train.approve_policy(p['forecast_training_policy_id'],'p1');train.approve_policy(p['forecast_training_policy_id'],'p2');return p

def setup_build(chal_id,quality=True,repro=True):
    f=train.register_feature('PROD','risk_signal','float',{'source':'kri','transform':'identity'})
    records=[{'risk_signal':1.0,'label':0},{'risk_signal':2.0,'label':1},{'risk_signal':3.0,'label':1}]
    ds=train.snapshot_dataset('PROD','forecast-training',records,[f['forecast_feature_version_id']],['warehouse://risk'])
    q=train.assess_data_quality(ds['training_dataset_snapshot_id'],0,0,0 if quality else .5,{'report':'dq'})
    l=train.create_lineage('PROD',chal_id,ds['training_dataset_snapshot_id'])
    m=train.create_manifest(l['forecast_training_lineage_id'],'git://forecast@abc','a'*64,{'growth_multiplier':.9},42)
    r=train.check_reproducibility(m['forecast_training_manifest_id'],('a'*64 if repro else 'b'*64),{'growth_multiplier':.9},42,'artifact://repro')
    return ds,q,l,m,r

def test_policy_maker_checker():
    clean();p=train.create_policy('PROD',actor='maker')
    with pytest.raises(ValueError):train.approve_policy(p['forecast_training_policy_id'],'maker')
    train.approve_policy(p['forecast_training_policy_id'],'x');assert train.approve_policy(p['forecast_training_policy_id'],'y')['state']=='ACTIVE'

def test_feature_registry_and_dataset_snapshot_are_versioned_and_hashed():
    clean();f1=train.register_feature('PROD','risk_signal','float',{'transform':'identity'});f2=train.register_feature('PROD','risk_signal','float',{'transform':'clip'})
    assert f2['version_no']==f1['version_no']+1 and f1['transform_hash']!=f2['transform_hash']
    d=train.snapshot_dataset('PROD','train',[{'risk_signal':1},{'risk_signal':2}],[f2['forecast_feature_version_id']],['warehouse://v1']);assert d['row_count']==2 and len(d['content_hash'])==64 and len(d['schema_hash'])==64

def test_training_data_quality_gate_blocks_bad_data():
    clean();_,chal=setup_models();setup_policy();ds,q,_,_,_=setup_build(chal['risk_forecast_model_version_id'],quality=False,repro=True)
    assert q['quality_state']=='FAIL' and 'INVALID_RATE_EXCEEDED' in q['reason_codes']
    e=train.evaluate_build(chal['risk_forecast_model_version_id']);assert e['eligibility_state']=='BLOCKED' and 'TRAINING_DATA_QUALITY_PASS_REQUIRED' in e['reason_codes']

def test_lineage_and_manifest_bind_dataset_features_code_and_seed():
    clean();_,chal=setup_models();setup_policy();ds,q,l,m,r=setup_build(chal['risk_forecast_model_version_id'])
    assert l['lineage_state']=='COMPLETE' and len(l['lineage_hash'])==64
    assert m['manifest_state']=='READY_FOR_REPRODUCTION' and len(m['build_hash'])==64 and m['random_seed']==42

def test_reproducibility_mismatch_blocks_model_build():
    clean();_,chal=setup_models();setup_policy();_,_,_,_,r=setup_build(chal['risk_forecast_model_version_id'],repro=False)
    assert r['reproducibility_state']=='MISMATCH'
    e=train.evaluate_build(chal['risk_forecast_model_version_id']);assert e['eligibility_state']=='BLOCKED' and 'REPRODUCIBILITY_MATCH_REQUIRED' in e['reason_codes']

def test_reproducible_build_becomes_eligible():
    clean();_,chal=setup_models();setup_policy();_,q,l,m,r=setup_build(chal['risk_forecast_model_version_id'])
    assert q['quality_state']=='PASS' and r['reproducibility_state']=='MATCHED'
    e=train.evaluate_build(chal['risk_forecast_model_version_id']);assert e['eligibility_state']=='ELIGIBLE'

def test_4l_backtest_requires_4o_reproducible_build_when_policy_active():
    clean();champ,chal=setup_models();setup_policy()
    with pytest.raises(ValueError,match='REPRODUCIBLE_MODEL_BUILD_ELIGIBILITY_REQUIRED'):promo.backtest('PROD',champ['risk_forecast_model_version_id'],chal['risk_forecast_model_version_id'])
    setup_build(chal['risk_forecast_model_version_id']);train.evaluate_build(chal['risk_forecast_model_version_id'])
    run=promo.backtest('PROD',champ['risk_forecast_model_version_id'],chal['risk_forecast_model_version_id']);assert run['state']=='COMPLETED'

def test_supplier_fact_boundary():
    clean();_,chal=setup_models();setup_policy();ds,q,l,m,r=setup_build(chal['risk_forecast_model_version_id']);e=train.evaluate_build(chal['risk_forecast_model_version_id'])
    assert all(x['supplier_fact_unchanged'] for x in [ds,q,l,m,r,e])
