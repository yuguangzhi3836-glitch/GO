import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_sprint4v_test.db'
from datetime import datetime,timezone
import pytest
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_forecast_segment_remediation import recovery_forecast_segment_remediation_service as rem
from go_hotel.journey.recovery_forecast_generalization import recovery_forecast_generalization_service as svc

def now():return datetime.now(timezone.utc)
def setup_function():
 Base.metadata.drop_all(engine);Base.metadata.create_all(engine);seed()
def seed():
 with SessionLocal() as s:
  for mid,v in [('champ',1),('chall',2)]:s.add(JourneyRecoveryRiskForecastModelVersionRow(risk_forecast_model_version_id=mid,model_key='risk',version_no=v,environment='PROD',algorithm_key='x',parameters_json={},conservative_parameters_json={},minimum_samples=2,max_mae_points=10,max_brier_score=.25,max_false_positive_rate=.2,max_false_negative_rate=.2,max_capacity_drift_pct=10,requested_by='x',board_approver_one='a',board_approver_two='b',state='ACTIVE',created_at=now(),supplier_fact_unchanged=True))
  s.add(JourneyRecoveryForecastSegmentPerformanceAssessmentRow(forecast_segment_performance_assessment_id='seg_bad',environment='PROD',deployment_key='champ-prod',model_version_id='champ',team_key='TEAM_A',risk_domain='IDENTITY',horizon_hours=24,sample_count=10,mae=100,rmse=120,mean_brier_score=.3,performance_state='DEGRADED',reason_codes_json=['SEGMENT_MAE_BREACH'],assessed_at=now(),supplier_fact_unchanged=True))
  s.add(JourneyRecoveryForecastRetrainingRequestRow(forecast_retraining_request_id='rr1',environment='PROD',source_drift_assessment_id='seg_bad',champion_model_version_id='champ',requested_model_key='risk',refresh_reason_codes_json=['ONLINE_SEGMENT_DEGRADATION'],state='CHALLENGER_GENERATED',requested_at=now(),requested_by='auto',evidence_json={},supplier_fact_unchanged=True))
  s.add(JourneyRecoveryForecastRefreshPipelineRow(forecast_refresh_pipeline_id='pipe1',environment='PROD',retraining_request_id='rr1',source_champion_model_version_id='champ',challenger_model_version_id='chall',pipeline_state='CHALLENGER_GENERATED',governance_next_step='MODEL_APPROVAL_BACKTEST_SHADOW_4L_4M',created_at=now(),updated_at=now(),supplier_fact_unchanged=True));s.commit()
def prepare_effective():
 p=rem.create_policy('PROD',15,10,3,'maker-rem');rem.approve_policy(p['policy_id'],'ra1');rem.approve_policy(p['policy_id'],'ra2');t=rem.create_target('rr1');rem.validate_target(t['target_id'],'chall',5,70);rem.assess(t['target_id'],'chall',{'evidence':'4u'});return t
def policy():
 p=svc.create_policy('PROD',3,10,8,10,'maker-v');svc.approve_policy(p['policy_id'],'va1');svc.approve_policy(p['policy_id'],'va2');return p
def test_policy_maker_checker():
 p=svc.create_policy(actor='maker')
 with pytest.raises(ValueError,match='GENERALIZATION_MAKER_CHECKER_REQUIRED'):svc.approve_policy(p['policy_id'],'maker')
def test_adjacent_generalization_detects_regression():
 t=prepare_effective();policy();x=svc.validate_adjacent(t['target_id'],'chall','TEAM_B|IDENTITY|24',5,50,60);assert x['state']=='FAIL' and 'ADJACENT_SEGMENT_REGRESSION' in x['reason_codes']
def test_holdout_safety_detects_regression():
 t=prepare_effective();policy();x=svc.validate_holdout(t['target_id'],'chall','HOLDOUT|REGION_X|24',5,50,56);assert x['state']=='FAIL' and 'HOLDOUT_SEGMENT_REGRESSION' in x['reason_codes']
def test_pre_promotion_requires_generalization_and_holdout():
 t=prepare_effective();policy()
 with SessionLocal() as s:
  with pytest.raises(ValueError,match='REMEDIATION_GENERALIZATION_GATE_REQUIRED'):svc.assert_pre_promotion_eligible_in_session(s,'PROD','chall')
def test_passed_generalization_and_holdout_unlock_gate():
 t=prepare_effective();policy();svc.validate_adjacent(t['target_id'],'chall','TEAM_B|IDENTITY|24',5,50,51);svc.validate_holdout(t['target_id'],'chall','HOLDOUT|REGION_X|24',5,50,51)
 with SessionLocal() as s:assert svc.assert_pre_promotion_eligible_in_session(s,'PROD','chall') is True
def test_post_promotion_proof_can_be_proven():
 t=prepare_effective();policy();x=svc.post_promotion_proof(t['target_id'],'chall',20,2,2,'PASS',{'live':'ok'});assert x['proof_state']=='REMEDIATION_PROVEN_IN_PRODUCTION' and not x['rollback_required']
def test_post_promotion_regression_requires_governed_rollback():
 t=prepare_effective();policy();x=svc.post_promotion_proof(t['target_id'],'chall',20,2,20,'PASS',{'live':'bad-holdout'});assert x['proof_state']=='POST_PROMOTION_REGRESSION' and x['rollback_required']
def test_probation_requires_current_production_proof_and_preserves_supplier_fact():
 t=prepare_effective();policy()
 with SessionLocal() as s:assert svc.probation_reason_in_session(s,'PROD','chall')=='PROBATION_4V_PROOF_EVIDENCE_REQUIRED'
 x=svc.post_promotion_proof(t['target_id'],'chall',18,1,1,'PASS')
 with SessionLocal() as s:assert svc.probation_reason_in_session(s,'PROD','chall') is None
 assert x['supplier_fact_unchanged'] is True
