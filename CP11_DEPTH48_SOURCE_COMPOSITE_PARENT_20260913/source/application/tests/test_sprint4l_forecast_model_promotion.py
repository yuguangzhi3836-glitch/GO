import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4l_test.db')
from datetime import datetime,timezone
import pytest
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_forecast_model_promotion import recovery_forecast_model_promotion_service as svc
from go_hotel.journey.recovery_risk_forecast_calibration import recovery_risk_forecast_calibration_service as cal

def setup_function(): Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def seed():
    t=datetime.now(timezone.utc)
    with SessionLocal() as s:
        for mid,v in [('champ',1),('chall',2)]:
            s.add(JourneyRecoveryRiskForecastModelVersionRow(risk_forecast_model_version_id=mid,model_key='m',version_no=v,environment='PROD',algorithm_key='A',parameters_json={'growth_multiplier':1},conservative_parameters_json={'growth_multiplier':1.5},minimum_samples=2,max_mae_points=100,max_brier_score=1,max_false_positive_rate=1,max_false_negative_rate=1,max_capacity_drift_pct=100,requested_by='m',board_approver_one='a',board_approver_two='b',state='ACTIVE' if mid=='chall' else 'SUPERSEDED',created_at=t,supplier_fact_unchanged=True))
        for mid,mae,brier,fp,fn,drift in [('champ',20,.2,.2,.2,10),('chall',10,.1,.1,.1,5)]:
            for h in (24,168):
                s.add(JourneyRecoveryRiskForecastAccuracyAssessmentRow(risk_forecast_accuracy_assessment_id=f'a-{mid}-{h}',environment='PROD',risk_forecast_model_version_id=mid,horizon_hours=h,sample_count=30,mae_points=mae,brier_score=brier,false_positive_rate=fp,false_negative_rate=fn,mean_capacity_drift_pct=drift,calibration_error_pct=5,accuracy_state='PASS',reason_codes_json=[],evaluated_at=t,supplier_fact_unchanged=True))
        s.commit()
    svc.assign_role('PROD','champ','CHAMPION');svc.assign_role('PROD','chall','CHALLENGER')

def test_champion_role_controls_runtime_even_if_newer_model_exists():
    seed(); assert cal.runtime_governance('PROD')['model_version_id']=='champ'
def test_shadow_24h_requires_improvement_without_safety_degradation():
    seed(); x=svc.shadow('PROD','chall',24); assert x['evaluation_state']=='PASS' and x['improvement_pct']>0 and x['safety_delta_pct']<=0
def test_shadow_7d_is_separate_horizon_gate():
    seed(); assert svc.shadow('PROD','chall',168)['evaluation_state']=='PASS'
def test_promotion_blocked_until_both_horizons_pass():
    seed();svc.shadow('PROD','chall',24);d=svc.promote('PROD','chall',{'e':'gate'});assert d['decision']=='BLOCKED' and 'HORIZON_168_SHADOW_PASS_REQUIRED' in d['reason_codes']
def test_promotion_switches_champion_only_after_full_gate():
    seed();svc.shadow('PROD','chall',24);svc.shadow('PROD','chall',168);d=svc.promote('PROD','chall',{'e':'gate'});assert d['decision']=='PROMOTED' and cal.runtime_governance('PROD')['model_version_id']=='chall'
def test_safety_degradation_blocks_challenger_even_with_lower_mae():
    seed()
    with SessionLocal() as s:
        x=s.get(JourneyRecoveryRiskForecastAccuracyAssessmentRow,'a-chall-24');x.false_negative_rate=.8;s.commit()
    x=svc.shadow('PROD','chall',24);assert x['evaluation_state']=='FAIL' and x['safety_delta_pct']>0
def test_backtest_persists_horizon_and_segment_metrics():
    seed();r=svc.backtest('PROD','champ','chall','ROLLING_30D',['ALL','IDENTITY']); assert r['state']=='COMPLETED' and len(r['metrics'])==8 and {m['horizon_hours'] for m in r['metrics']}=={24,168}
def test_governance_evidence_never_changes_supplier_fact():
    seed();svc.shadow('PROD','chall',24);svc.shadow('PROD','chall',168);d=svc.promote('PROD','chall',{'e':'audit'});assert d['supplier_fact_unchanged'] is True
