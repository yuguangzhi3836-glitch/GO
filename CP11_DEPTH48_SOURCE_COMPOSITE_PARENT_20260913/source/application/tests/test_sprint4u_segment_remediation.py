import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_sprint4u_test.db'
from datetime import datetime,timezone
import pytest
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_forecast_segment_remediation import recovery_forecast_segment_remediation_service as svc

def now():return datetime.now(timezone.utc)
def setup_function():
 Base.metadata.drop_all(engine);Base.metadata.create_all(engine);seed()
def seed():
 with SessionLocal() as s:
  s.add(JourneyRecoveryRiskForecastModelVersionRow(risk_forecast_model_version_id='champ',model_key='risk',version_no=1,environment='PROD',algorithm_key='x',parameters_json={},conservative_parameters_json={},minimum_samples=2,max_mae_points=10,max_brier_score=.25,max_false_positive_rate=.2,max_false_negative_rate=.2,max_capacity_drift_pct=10,requested_by='x',board_approver_one='a',board_approver_two='b',state='ACTIVE',created_at=now(),supplier_fact_unchanged=True))
  s.add(JourneyRecoveryRiskForecastModelVersionRow(risk_forecast_model_version_id='chall',model_key='risk',version_no=2,environment='PROD',algorithm_key='x',parameters_json={},conservative_parameters_json={},minimum_samples=2,max_mae_points=10,max_brier_score=.25,max_false_positive_rate=.2,max_false_negative_rate=.2,max_capacity_drift_pct=10,requested_by='x',board_approver_one='a',board_approver_two='b',state='ACTIVE',created_at=now(),supplier_fact_unchanged=True))
  s.add(JourneyRecoveryForecastSegmentPerformanceAssessmentRow(forecast_segment_performance_assessment_id='seg_bad',environment='PROD',deployment_key='champ-prod',model_version_id='champ',team_key='TEAM_A',risk_domain='IDENTITY',horizon_hours=24,sample_count=10,mae=100,rmse=120,mean_brier_score=.3,performance_state='DEGRADED',reason_codes_json=['SEGMENT_MAE_BREACH'],assessed_at=now(),supplier_fact_unchanged=True))
  s.add(JourneyRecoveryForecastRetrainingRequestRow(forecast_retraining_request_id='rr1',environment='PROD',source_drift_assessment_id='seg_bad',champion_model_version_id='champ',requested_model_key='risk',refresh_reason_codes_json=['ONLINE_SEGMENT_DEGRADATION'],state='CHALLENGER_GENERATED',requested_at=now(),requested_by='auto',evidence_json={},supplier_fact_unchanged=True))
  s.add(JourneyRecoveryForecastRefreshPipelineRow(forecast_refresh_pipeline_id='pipe1',environment='PROD',retraining_request_id='rr1',source_champion_model_version_id='champ',challenger_model_version_id='chall',pipeline_state='CHALLENGER_GENERATED',governance_next_step='MODEL_APPROVAL_BACKTEST_SHADOW_4L_4M',created_at=now(),updated_at=now(),supplier_fact_unchanged=True));s.commit()
def policy():
 p=svc.create_policy('PROD',15,10,3,'maker');svc.approve_policy(p['policy_id'],'a1');return svc.approve_policy(p['policy_id'],'a2')
def target():policy();return svc.create_target('rr1')
def test_policy_requires_maker_checker():
 p=svc.create_policy('PROD',15,10,3,'maker')
 with pytest.raises(ValueError,match='REMEDIATION_MAKER_CHECKER_REQUIRED'):svc.approve_policy(p['policy_id'],'maker')
def test_target_binds_original_failed_segment():
 t=target();assert (t['team_key'],t['risk_domain'],t['horizon_hours'],t['baseline_mae'])==('TEAM_A','IDENTITY',24,100)
def test_target_not_repaired_is_ineffective():
 t=target();svc.validate_target(t['target_id'],'chall',5,95);a=svc.assess(t['target_id'],'chall');assert a['effectiveness_state']=='REMEDIATION_INEFFECTIVE' and not a['promotion_eligible']
def test_target_repair_without_regression_is_effective():
 t=target();svc.validate_target(t['target_id'],'chall',5,70);svc.register_cross_segment(t['target_id'],'chall','TEAM_B|CAPACITY|24',50,52);a=svc.assess(t['target_id'],'chall');assert a['effectiveness_state']=='REMEDIATION_EFFECTIVE' and a['promotion_eligible']
def test_cross_segment_regression_blocks_promotion():
 t=target();svc.validate_target(t['target_id'],'chall',5,70);svc.register_cross_segment(t['target_id'],'chall','TEAM_B|CAPACITY|24',50,60);a=svc.assess(t['target_id'],'chall');assert a['effectiveness_state']=='REMEDIATION_PARTIALLY_EFFECTIVE' and not a['promotion_eligible']
def test_severe_cross_segment_regression_is_harmful():
 t=target();svc.validate_target(t['target_id'],'chall',5,70);svc.register_cross_segment(t['target_id'],'chall','TEAM_B|CAPACITY|24',50,80);a=svc.assess(t['target_id'],'chall');assert a['effectiveness_state']=='REMEDIATION_HARMFUL'
def test_refresh_challenger_cannot_bypass_remediation_gate():
 policy()
 with SessionLocal() as s:
  with pytest.raises(ValueError,match='SEGMENT_REMEDIATION_TARGET_REQUIRED'):svc.assert_promotion_eligible_in_session(s,'PROD','chall')
def test_effective_remediation_unlocks_promotion_gate_and_preserves_supplier_fact():
 t=target();v=svc.validate_target(t['target_id'],'chall',5,70);a=svc.assess(t['target_id'],'chall',{'evidence':'ok'})
 with SessionLocal() as s:assert svc.assert_promotion_eligible_in_session(s,'PROD','chall') is True
 assert v['supplier_fact_unchanged'] and a['supplier_fact_unchanged']
