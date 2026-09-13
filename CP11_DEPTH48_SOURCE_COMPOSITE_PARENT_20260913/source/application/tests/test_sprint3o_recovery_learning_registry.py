from datetime import datetime,timezone,timedelta
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryReliabilityProfileRow,JourneyRecoveryCalibrationProfileRow,JourneyRecoveryStrategyVersionRow,JourneyRecoveryExperimentRow,JourneyRecoveryLearningRegistryRow,JourneyRecoveryBenchmarkProfileRow
from go_hotel.journey.recovery_learning_registry import recovery_learning_registry_service as svc
from go_hotel.security.service import identity_service

def ah():
    t=identity_service.login('go_admin','change-me-admin');return {'Authorization':'Bearer '+t['access_token']}

def seed(adapter,confirmation=.9,timeout=.05,manual=.02,cal_confirmation=.9,cal_timeout=.05,cal_manual=.02,updated=None):
    t=datetime.now(timezone.utc);updated=updated or t
    rid='rel_'+adapter;sid='strat_'+adapter;eid='exp_'+adapter;cid='cal_'+adapter
    with SessionLocal() as s:
        s.add(JourneyRecoveryReliabilityProfileRow(reliability_profile_id=rid,vertical='RAIL',adapter_key=adapter,sample_count=100,async_count=5,unknown_count=5,confirmed_count=int(confirmation*100),failed_count=5,manual_review_count=int(manual*100),avg_confirmation_seconds=90,avg_webhook_lag_seconds=20,avg_poll_attempts=2,timeout_rate=timeout,manual_review_rate=manual,confirmation_rate=confirmation,confidence=.95,risk_band='LOW',recommended_initial_poll_seconds=30,recommended_max_poll_seconds=300,recommended_max_attempts=8,recommended_ack_multiplier=1,recommended_resolution_multiplier=1,metrics_json={},calculated_at=t))
        s.add(JourneyRecoveryStrategyVersionRow(strategy_version_id=sid,name=sid,state='ACTIVE',min_sample_count=20,min_confidence=.8,confidence_level=.95,rollout_percent=100,parameter_bounds_json={},rollback_thresholds_json={},requires_approval=True,approved_by='admin',approved_at=t,activated_at=t,created_at=t,updated_at=t))
        s.add(JourneyRecoveryExperimentRow(experiment_id=eid,name=eid,state='PROMOTED',control_strategy_version_id=sid,candidate_strategy_version_id=sid,allocation_percent=10,min_sample_per_arm=30,significance_alpha=.05,primary_metric='confirmation_rate',stratification_json={},promotion_gate_json={},approved_by='admin',approved_at=t,started_at=t,ended_at=t,created_at=t,updated_at=t))
        s.add(JourneyRecoveryCalibrationProfileRow(calibration_profile_id=cid,vertical='RAIL',adapter_key=adapter,sample_count=100,source_experiment_id=eid,calibrated_parameters_json={'observed_confirmation_rate':cal_confirmation,'observed_timeout_rate':cal_timeout,'observed_manual_review_rate':cal_manual},confidence_json={'sample_count':100,'production_calibrated':True},state='CALIBRATED',created_at=updated,updated_at=updated))
        s.commit()
    return rid,sid,eid,cid

def test_k_anonymized_cross_supplier_benchmark_withholds_small_cohort():
    seed('rail_a');seed('rail_b')
    x=svc.rebuild_benchmarks(anonymization_k=3)[0]
    assert x['state']=='WITHHELD_K_ANONYMITY' and x['supplier_count']==2
    seed('rail_c')
    x=svc.rebuild_benchmarks(anonymization_k=3)[0]
    assert x['state']=='AVAILABLE' and x['supplier_count']==3

def test_registry_builds_provenance_graph_and_freshness():
    seed('rail_a');seed('rail_b');seed('rail_c');svc.rebuild_benchmarks();regs=svc.rebuild_registry(ttl_days=30)
    r=[x for x in regs if x['adapter_key']=='rail_a'][0]
    assert r['state']=='VALID' and r['revalidation_required'] is False
    g=svc.graph(r['learning_registry_id']);kinds=[e['from_kind'] for e in g['edges']]+[e['to_kind'] for e in g['edges']]
    assert 'RELIABILITY_PROFILE' in kinds and 'EXPERIMENT' in kinds and 'CALIBRATION_PROFILE' in kinds and 'LEARNING_REGISTRY' in kinds

def test_expired_calibration_forces_revalidation():
    seed('rail_old',updated=datetime.now(timezone.utc)-timedelta(days=90));svc.rebuild_benchmarks();regs=svc.rebuild_registry(ttl_days=30)
    r=[x for x in regs if x['adapter_key']=='rail_old'][0]
    assert r['state']=='REVALIDATION_REQUIRED' and r['freshness_state']=='STALE'

def test_concept_drift_forces_revalidation_without_supplier_fact_mutation():
    seed('rail_drift',confirmation=.70,timeout=.20,manual=.15,cal_confirmation=.95,cal_timeout=.02,cal_manual=.01);svc.rebuild_benchmarks(anonymization_k=2);regs=svc.rebuild_registry();rid=[x for x in regs if x['adapter_key']=='rail_drift'][0]['learning_registry_id']
    d=[x for x in svc.assess_drift() if x['learning_registry_id']==rid][0]
    assert d['drift_detected'] is True and d['action']=='REVALIDATE' and d['supplier_fact_unchanged'] is True
    with SessionLocal() as s:
        r=s.get(JourneyRecoveryLearningRegistryRow,rid);assert r.revalidation_required is True and r.state=='REVALIDATION_REQUIRED'

def test_admin_registry_benchmark_drift_and_revalidation_api(client):
    H=ah();seed('rail_a');seed('rail_b');seed('rail_c')
    rr=client.post('/internal/v1/recovery/learning/rebuild',headers=H,json={'ttl_days':30,'anonymization_k':3});assert rr.status_code==200
    items=client.get('/internal/v1/recovery/learning/registry',headers=H).json()['data']['items'];assert items
    rid=items[0]['learning_registry_id']
    assert client.get(f'/internal/v1/recovery/learning/registry/{rid}/provenance',headers=H).status_code==200
    assert client.get('/internal/v1/recovery/learning/benchmarks',headers=H).status_code==200
    assert client.post('/internal/v1/recovery/learning/drift/tick',headers=H).status_code==200
    assert client.get('/internal/v1/recovery/learning/drift',headers=H).status_code==200
    rv=client.post(f'/internal/v1/recovery/learning/registry/{rid}/revalidate',headers=H);assert rv.status_code==200 and rv.json()['data']['supplier_fact_unchanged'] is True
    paths=client.app.openapi()['paths'];assert not any('supplier-fact' in p and ('override' in p or 'mutate' in p) for p in paths)
