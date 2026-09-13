import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4m_test.db')
from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import select
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_forecast_model_promotion import recovery_forecast_model_promotion_service as legacy
from go_hotel.journey.recovery_forecast_statistical_promotion import recovery_forecast_statistical_promotion_service as svc
from go_hotel.journey.recovery_risk_forecast_calibration import recovery_risk_forecast_calibration_service as cal

def setup_function(): Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def seed():
    t=datetime.now(timezone.utc)
    with SessionLocal() as s:
        for mid,v in [('champ',1),('chall',2)]:
            s.add(JourneyRecoveryRiskForecastModelVersionRow(risk_forecast_model_version_id=mid,model_key='m',version_no=v,environment='PROD',algorithm_key='A',parameters_json={'growth_multiplier':1},conservative_parameters_json={'growth_multiplier':1.5},minimum_samples=2,max_mae_points=100,max_brier_score=1,max_false_positive_rate=1,max_false_negative_rate=1,max_capacity_drift_pct=100,requested_by='m',board_approver_one='a',board_approver_two='b',state='ACTIVE',created_at=t,supplier_fact_unchanged=True))
        for mid,mae,brier,fp,fn,drift in [('champ',30,.25,.15,.15,12),('chall',10,.10,.10,.10,6)]:
            for h in (24,168):
                s.add(JourneyRecoveryRiskForecastAccuracyAssessmentRow(risk_forecast_accuracy_assessment_id=f'a-{mid}-{h}',environment='PROD',risk_forecast_model_version_id=mid,horizon_hours=h,sample_count=100,mae_points=mae,brier_score=brier,false_positive_rate=fp,false_negative_rate=fn,mean_capacity_drift_pct=drift,calibration_error_pct=5,accuracy_state='PASS',reason_codes_json=[],evaluated_at=t,supplier_fact_unchanged=True))
        run=JourneyRecoveryForecastBacktestRunRow(forecast_backtest_run_id='run',environment='PROD',champion_model_version_id='champ',challenger_model_version_id='chall',window_key='ROLLING_90D',horizons_json=[24,168],segments_json=['ALL','IDENTITY'],state='COMPLETED',created_at=t,supplier_fact_unchanged=True);s.add(run)
        for mid,mae,brier,fp,fn,drift in [('champ',30,.25,.15,.15,12),('chall',10,.10,.10,.10,6)]:
            for h in (24,168):
                for seg in ('ALL','IDENTITY'):
                    s.add(JourneyRecoveryForecastBacktestMetricRow(forecast_backtest_metric_id=f'm-{mid}-{h}-{seg}',forecast_backtest_run_id='run',model_version_id=mid,horizon_hours=h,segment_key=seg,sample_count=100,mae_points=mae,brier_score=brier,false_positive_rate=fp,false_negative_rate=fn,capacity_drift_pct=drift,supplier_fact_unchanged=True))
        s.commit()
    legacy.assign_role('PROD','champ','CHAMPION');legacy.assign_role('PROD','chall','CHALLENGER')

def policy(segments=None,stability=2,probation=3600,minsample=30,effect=5,alpha=.05):
    p=svc.create_policy('PROD',minsample,alpha,effect,stability,segments or ['ALL'],probation,10,10,5,'maker')
    svc.approve_policy(p['forecast_promotion_policy_id'],'board1');return svc.approve_policy(p['forecast_promotion_policy_id'],'board2')
def shadows(segments=('ALL',),count=2):
    for seg in segments:
        for h in (24,168):
            for _ in range(count): legacy.shadow('PROD','chall',h,seg)

def test_policy_requires_two_distinct_approvers():
    seed();p=svc.create_policy('PROD',actor='maker');svc.approve_policy(p['forecast_promotion_policy_id'],'board1')
    with pytest.raises(ValueError,match='TWO_DISTINCT'): svc.approve_policy(p['forecast_promotion_policy_id'],'board1')

def test_legacy_promotion_is_blocked_when_4m_policy_active():
    seed();policy();shadows(count=2)
    with pytest.raises(ValueError,match='STATISTICAL_PROMOTION_GOVERNANCE_REQUIRED'): legacy.promote('PROD','chall',{'e':'old-route'})

def test_significance_and_minimum_effect_size_gate_both_horizons_and_segments():
    seed();policy(['ALL','IDENTITY']);r=svc.assess('PROD','chall')
    assert len(r['assessments'])==4 and all(x['significance_state']=='PASS' and x['p_value']<.05 and x['effect_size_pct']>=5 for x in r['assessments'])

def test_sample_or_effect_shortfall_blocks_statistical_gate():
    seed();policy(minsample=200,effect=90);r=svc.assess('PROD','chall')
    assert all(x['significance_state']=='FAIL' for x in r['assessments'])
    assert 'MINIMUM_SAMPLE_NOT_MET' in r['assessments'][0]['reason_codes'] and 'MINIMUM_EFFECT_SIZE_NOT_MET' in r['assessments'][0]['reason_codes']

def test_stability_window_and_segment_consistency_required_before_promotion():
    seed();policy(['ALL','IDENTITY'],stability=2);svc.assess('PROD','chall');shadows(('ALL','IDENTITY'),count=1)
    d=svc.promote('PROD','chall',{'e':'gate'});assert d['decision']=='BLOCKED' and any('STABILITY_WINDOW_NOT_MET' in x for x in d['reason_codes'])

def test_full_gate_promotes_into_probation_not_stable_directly():
    seed();policy(['ALL','IDENTITY'],stability=2);svc.assess('PROD','chall');shadows(('ALL','IDENTITY'),2)
    d=svc.promote('PROD','chall',{'e':'gate'});st=svc.status('PROD');assert d['decision']=='PROMOTED_PROBATION' and st['probations'][0]['state']=='PROBATION' and cal.runtime_governance('PROD')['model_version_id']=='chall'

def test_probation_regression_automatically_rolls_back_previous_champion():
    seed();policy(probation=3600);svc.assess('PROD','chall');shadows(count=2);svc.promote('PROD','chall',{'e':'gate'})
    with SessionLocal() as s:
        for h in (24,168):
            s.add(JourneyRecoveryRiskForecastAccuracyAssessmentRow(risk_forecast_accuracy_assessment_id=f'bad-{h}',environment='PROD',risk_forecast_model_version_id='chall',horizon_hours=h,sample_count=100,mae_points=60,brier_score=.6,false_positive_rate=.5,false_negative_rate=.5,mean_capacity_drift_pct=30,calibration_error_pct=20,accuracy_state='DEGRADED',reason_codes_json=['bad'],evaluated_at=datetime.now(timezone.utc)+timedelta(seconds=1),supplier_fact_unchanged=True))
        s.commit()
    r=svc.probation_tick('PROD',{'e':'prod-outcomes'});assert r['state']=='ROLLED_BACK' and cal.runtime_governance('PROD')['model_version_id']=='champ' and svc.status('PROD')['rollback_events'][0]['supplier_fact_unchanged'] is True

def test_probation_becomes_stable_only_after_window_and_no_regression():
    seed();policy(probation=1);svc.assess('PROD','chall');shadows(count=2);svc.promote('PROD','chall',{'e':'gate'})
    with SessionLocal() as s:
        pr=s.execute(select(JourneyRecoveryForecastPromotionProbationRow)).scalars().first();pr.probation_until=datetime.now(timezone.utc)-timedelta(seconds=1);s.commit()
    r=svc.probation_tick('PROD',{'e':'stable'});assert r['state']=='STABLE' and cal.runtime_governance('PROD')['model_version_id']=='chall' and r['supplier_fact_unchanged'] is True
