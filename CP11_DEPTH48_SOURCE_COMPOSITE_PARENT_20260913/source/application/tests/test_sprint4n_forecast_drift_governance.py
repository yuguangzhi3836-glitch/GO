from datetime import datetime,timezone
import pytest
from sqlalchemy import delete
from go_hotel.db.session import SessionLocal,engine
from go_hotel.db.models import *
from go_hotel.journey.recovery_risk_forecast_calibration import recovery_risk_forecast_calibration_service as cal
from go_hotel.journey.recovery_forecast_model_promotion import recovery_forecast_model_promotion_service as promo
from go_hotel.journey.recovery_forecast_drift_governance import recovery_forecast_drift_governance_service as drift

def clean():
    with SessionLocal() as s:
        for m in [JourneyRecoveryForecastDriftEventRow,JourneyRecoveryForecastRefreshPipelineRow,JourneyRecoveryForecastRetrainingRequestRow,JourneyRecoveryForecastDriftAssessmentRow,JourneyRecoveryForecastDriftPolicyRow,JourneyRecoveryForecastModelRoleRow,JourneyRecoveryRiskForecastOutcomeRow,JourneyRecoveryRiskForecastModelVersionRow]:
            try:s.execute(delete(m))
            except Exception:pass
        s.commit()
def setup_champion(samples=4):
    m=cal.create_model('risk-v','PROD','deterministic',{'growth_multiplier':1},{'growth_multiplier':1.5},2,100,1,1,1,100,'maker')
    cal.approve_model(m['risk_forecast_model_version_id'],'a1');cal.approve_model(m['risk_forecast_model_version_id'],'a2')
    promo.assign_role('PROD',m['risk_forecast_model_version_id'],'CHAMPION')
    with SessionLocal() as s:
        for i in range(samples):
            s.add(JourneyRecoveryRiskForecastOutcomeRow(risk_forecast_outcome_id=f'o{i}',environment='PROD',risk_forecast_id=f'f{i}',risk_forecast_model_version_id=m['risk_forecast_model_version_id'],horizon_hours=24,predicted_exposure_points=100,predicted_breach_probability=.1,actual_exposure_points=100+i*10,actual_breach=False,absolute_error_points=float(i*10),squared_probability_error=.01,observed_at=datetime.now(timezone.utc),evidence_json={},supplier_fact_unchanged=True))
        s.commit()
    return m
def setup_policy(min_samples=2,consecutive=2):
    p=drift.create_policy('PROD',min_samples,.05,.05,1,consecutive,actor='maker');drift.approve_policy(p['forecast_drift_policy_id'],'p1');drift.approve_policy(p['forecast_drift_policy_id'],'p2');return p

def test_policy_maker_checker():
    clean();p=drift.create_policy('PROD',actor='maker')
    with pytest.raises(ValueError):drift.approve_policy(p['forecast_drift_policy_id'],'maker')
    drift.approve_policy(p['forecast_drift_policy_id'],'x');assert drift.approve_policy(p['forecast_drift_policy_id'],'y')['state']=='ACTIVE'
def test_insufficient_sample_does_not_trigger_refresh():
    clean();setup_champion(1);setup_policy(3,1);a=drift.assess('PROD',24,.1,.9);assert a['drift_state']=='INSUFFICIENT_DATA'
    with pytest.raises(ValueError):drift.request_refresh(a['forecast_drift_assessment_id'],{'e':'x'})
def test_population_and_segment_drift_detected():
    clean();setup_champion();setup_policy();a=drift.assess('PROD',24,.1,.8,{'TEAM_A':.1},{'TEAM_A':.9});assert a['drift_state']=='DRIFTED';assert 'POPULATION_STABILITY_INDEX_BREACH' in a['reason_codes'];assert 'SEGMENT_DRIFT_BREACH' in a['reason_codes']
def test_residual_drift_detected():
    clean();m=setup_champion(6);setup_policy()
    with SessionLocal() as s:
        rows=s.query(JourneyRecoveryRiskForecastOutcomeRow).order_by(JourneyRecoveryRiskForecastOutcomeRow.risk_forecast_outcome_id).all()
        for i,x in enumerate(rows):x.absolute_error_points=1 if i<3 else 100
        s.commit()
    a=drift.assess('PROD',24,.1,.1);assert 'FORECAST_RESIDUAL_DRIFT_BREACH' in a['reason_codes']
def test_consecutive_breaches_required_before_retraining():
    clean();setup_champion();setup_policy(consecutive=2);a=drift.assess('PROD',24,.1,.9)
    with pytest.raises(ValueError):drift.request_refresh(a['forecast_drift_assessment_id'],{'e':'1'})
    b=drift.assess('PROD',24,.1,.9);r=drift.request_refresh(b['forecast_drift_assessment_id'],{'e':'2'});assert r['state']=='APPROVED_FOR_REFRESH'
def test_auto_generated_candidate_is_challenger_not_champion():
    clean();m=setup_champion();setup_policy(consecutive=1);a=drift.assess('PROD',24,.1,.9);r=drift.request_refresh(a['forecast_drift_assessment_id'],{'e':'1'});c=drift.generate_challenger(r['forecast_retraining_request_id'])
    assert c['state']=='PENDING_APPROVAL' and c['role']=='CHALLENGER'
    with SessionLocal() as s:
        champs=s.query(JourneyRecoveryForecastModelRoleRow).filter_by(environment='PROD',role='CHAMPION',state='ACTIVE').all();assert len(champs)==1 and champs[0].model_version_id==m['risk_forecast_model_version_id']
def test_refresh_pipeline_points_to_4l_4m_governance():
    clean();setup_champion();setup_policy(consecutive=1);a=drift.assess('PROD',24,.1,.9);r=drift.request_refresh(a['forecast_drift_assessment_id'],{'e':'1'});c=drift.generate_challenger(r['forecast_retraining_request_id']);assert c['governance_next_step']=='MODEL_APPROVAL_BACKTEST_SHADOW_4L_4M'
def test_supplier_fact_boundary():
    clean();setup_champion();setup_policy(consecutive=1);a=drift.assess('PROD',24,.1,.9);r=drift.request_refresh(a['forecast_drift_assessment_id'],{'e':'1'});c=drift.generate_challenger(r['forecast_retraining_request_id']);assert a['supplier_fact_unchanged'] and r['supplier_fact_unchanged'] and c['supplier_fact_unchanged']
