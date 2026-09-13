import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4k_test.db')
from datetime import datetime,timezone,timedelta
import pytest
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import Base,JourneyRecoveryRiskAppetiteEnvelopeRow,JourneyRecoveryExecutiveRiskAcceptanceRow,JourneyRecoveryExecutiveRiskPositionRow,JourneyRecoveryRiskForecastOutcomeRow,JourneyRecoveryRiskCapacityAllocationDriftRow
from go_hotel.journey.recovery_enterprise_risk_forecast import recovery_enterprise_risk_forecast_service as forecast
from go_hotel.journey.recovery_risk_forecast_calibration import recovery_risk_forecast_calibration_service as cal

def setup_function(): Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def boot(exposure=100):
    with SessionLocal() as s:
        t=datetime.now(timezone.utc)
        s.add(JourneyRecoveryRiskAppetiteEnvelopeRow(risk_appetite_envelope_id='a',appetite_key='a',version_no=1,environment='PROD',max_current_exposure_points=300,max_stressed_exposure_points=450,min_headroom_points=50,min_capacity_buffer_pct=10,max_sensitivity_pct=150,requested_by='x',board_approver_one='a',board_approver_two='b',state='ACTIVE',created_at=t,supplier_fact_unchanged=True))
        s.add(JourneyRecoveryExecutiveRiskAcceptanceRow(executive_risk_acceptance_id='e',environment='PROD',debt_burn_down_plan_id='p',residual_risk_summary='x',evidence_reference='e',requested_by='r',requested_at=t,executive_approver_one='a',executive_approver_two='b',starts_at=t-timedelta(minutes=1),expires_at=t+timedelta(days=2),state='APPROVED',supplier_fact_unchanged=True))
        s.add(JourneyRecoveryExecutiveRiskPositionRow(risk_position_id='pos',environment='PROD',executive_risk_acceptance_id='e',team_key='team-a',risk_domain='IDENTITY',exposure_points=exposure,correlation_keys_json=['cloud-a'],state='ACTIVE',registered_by='r',registered_at=t,supplier_fact_unchanged=True));s.commit()
def active_forecast_policy():
    x=forecast.create_policy('f','PROD',80,95,10,'maker');forecast.approve_policy(x['risk_forecast_policy_id'],'board-a');forecast.approve_policy(x['risk_forecast_policy_id'],'board-b')
def active_model(minimum=2,max_mae=20,max_brier=.3,max_fp=.5,max_fn=.5,max_drift=40):
    x=cal.create_model('m','PROD','DETERMINISTIC_WEIGHTED_SIGNAL_V1',{'growth_multiplier':1},{'growth_multiplier':1.5,'minimum_growth':.08},minimum,max_mae,max_brier,max_fp,max_fn,max_drift,'maker')
    cal.approve_model(x['risk_forecast_model_version_id'],'board-a');return cal.approve_model(x['risk_forecast_model_version_id'],'board-b')
def make_outcome(h=24,actual=None):
    f=forecast.forecast('PROD',h);cal.record_outcome(f['risk_forecast_id'],f['projected_exposure_points'] if actual is None else actual,{'e':'actual'});return f

def test_model_registry_requires_two_distinct_board_approvers():
    x=cal.create_model('m','PROD','A',{}, {},2,20,.3,.5,.5,40,'maker')
    with pytest.raises(ValueError,match='MAKER_CHECKER'):cal.approve_model(x['risk_forecast_model_version_id'],'maker')
    cal.approve_model(x['risk_forecast_model_version_id'],'board-a')
    with pytest.raises(ValueError,match='TWO_DISTINCT'):cal.approve_model(x['risk_forecast_model_version_id'],'board-a')
    assert cal.approve_model(x['risk_forecast_model_version_id'],'board-b')['state']=='ACTIVE'

def test_predicted_vs_actual_outcome_is_version_bound_and_persisted():
    boot();active_forecast_policy();m=active_model();f=make_outcome(24)
    with SessionLocal() as s:
        o=s.query(JourneyRecoveryRiskForecastOutcomeRow).one();assert o.risk_forecast_model_version_id==m['risk_forecast_model_version_id'] and o.risk_forecast_id==f['risk_forecast_id'] and o.absolute_error_points==0

def test_24h_and_7d_calibration_are_separate():
    boot();active_forecast_policy();active_model()
    make_outcome(24);make_outcome(24);make_outcome(168);make_outcome(168)
    a=cal.assess('PROD',24);b=cal.assess('PROD',168)
    assert a['accuracy_state']=='PASS' and b['accuracy_state']=='PASS' and a['horizon_hours']==24 and b['horizon_hours']==168

def test_mae_degradation_auto_activates_conservative_baseline():
    boot();active_forecast_policy();active_model(minimum=2,max_mae=10)
    make_outcome(24,220);make_outcome(24,220)
    a=cal.assess('PROD',24);g=cal.runtime_governance('PROD')
    assert a['accuracy_state']=='DEGRADED' and 'FORECAST_MAE_LIMIT_EXCEEDED' in a['reason_codes'] and g['mode']=='CONSERVATIVE_BASELINE'

def test_conservative_baseline_changes_future_forecast_strategy_not_supplier_fact():
    boot();active_forecast_policy();active_model(minimum=2,max_mae=10)
    before=forecast.forecast('PROD',24);cal.record_outcome(before['risk_forecast_id'],220,{'e':'bad'})
    f2=forecast.forecast('PROD',24);cal.record_outcome(f2['risk_forecast_id'],220,{'e':'bad2'});cal.assess('PROD',24)
    after=forecast.forecast('PROD',24)
    assert after['projected_exposure_points']>before['projected_exposure_points'] and after['supplier_fact_unchanged'] is True

def test_false_positive_false_negative_and_brier_are_explicit_metrics():
    boot(260);active_forecast_policy();active_model(minimum=2,max_mae=999,max_brier=.01,max_fp=0,max_fn=0,max_drift=999)
    forecast.observe_indicator('PROD','burn','EWI','GLOBAL',None,2,1,'HIGH_BAD',1,{})
    make_outcome(24,100);make_outcome(24,100)
    a=cal.assess('PROD',24)
    assert a['brier_score']>0 and a['false_positive_rate']>0 and 'FORECAST_BRIER_LIMIT_EXCEEDED' in a['reason_codes']

def test_capacity_allocation_drift_is_observed_and_governed():
    boot();active_forecast_policy();active_model(minimum=2,max_mae=999,max_brier=1,max_fp=1,max_fn=1,max_drift=5)
    make_outcome(24,280);make_outcome(24,280)
    a=cal.assess('PROD',24)
    with SessionLocal() as s: assert s.query(JourneyRecoveryRiskCapacityAllocationDriftRow).count()>0
    assert a['mean_capacity_drift_pct']>5 and 'CAPACITY_ALLOCATION_DRIFT_LIMIT_EXCEEDED' in a['reason_codes']

def test_conservative_baseline_release_requires_recovered_24h_and_7d_accuracy():
    boot();active_forecast_policy();active_model(minimum=2,max_mae=60,max_brier=1,max_fp=1,max_fn=1,max_drift=999)
    make_outcome(24,220);make_outcome(24,220);cal.assess('PROD',24)
    with pytest.raises(ValueError,match='ACCURACY_NOT_RECOVERED'):cal.release_conservative('PROD','e://recover','risk')
    for _ in range(4):make_outcome(24);make_outcome(168)
    assert cal.assess('PROD',24)['accuracy_state']=='PASS';assert cal.assess('PROD',168)['accuracy_state']=='PASS'
    assert cal.release_conservative('PROD','e://recover','risk')['state']=='RELEASED' and cal.runtime_governance('PROD')['mode']=='GOVERNED_MODEL'
