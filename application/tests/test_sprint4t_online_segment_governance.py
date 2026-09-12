import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_sprint4t_test.db'
from datetime import datetime,timezone
from uuid import uuid4
import pytest
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_forecast_online_segment_governance import recovery_forecast_online_segment_governance_service as seg
def now():return datetime.now(timezone.utc)
def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine);seed_model()
def seed_model():
 with SessionLocal() as s:s.add(JourneyRecoveryRiskForecastModelVersionRow(risk_forecast_model_version_id='model_candidate',model_key='enterprise-risk',version_no=2,environment='PROD',algorithm_key='deterministic',parameters_json={},conservative_parameters_json={},minimum_samples=2,max_mae_points=10,max_brier_score=.25,max_false_positive_rate=.2,max_false_negative_rate=.2,max_capacity_drift_pct=10,requested_by='system',board_approver_one='a',board_approver_two='b',state='ACTIVE',created_at=now(),supplier_fact_unchanged=True));s.commit()
def active_policy(samples=3,breaches=2):
 p=seg.create_policy('PROD',samples,10,15,.25,breaches,'maker');seg.approve_policy(p['policy_id'],'approver1');return seg.approve_policy(p['policy_id'],'approver2')
def add_segment(error=100,team='TEAM_A',domain='IDENTITY',h=24):
 aid='jfoa_'+uuid4().hex;pid='pred_'+uuid4().hex
 with SessionLocal() as s:s.add(JourneyRecoveryForecastOutcomeAttributionRow(forecast_outcome_attribution_id=aid,prediction_request_id=pid,environment='PROD',serving_role='CANARY',deployment_key='candidate-prod',model_version_id='model_candidate',predicted_value=100,actual_value=100+error,absolute_error=abs(error),squared_error=error*error,brier_score=None,horizon_hours=h,outcome_state='FINAL',evidence_reference='truth://final',observed_at=now(),attributed_at=now(),supplier_fact_unchanged=True));s.commit()
 return aid,seg.register_attribution_segment(aid,team,domain)
def test_segment_observation_binds_team_domain_horizon():
 active_policy();aid,o=add_segment();assert o['team_key']=='TEAM_A' and o['risk_domain']=='IDENTITY' and o['horizon_hours']==24
def test_duplicate_segment_observation_rejected():
 active_policy();aid,o=add_segment()
 with pytest.raises(ValueError,match='SEGMENT_OBSERVATION_ALREADY_REGISTERED'):seg.register_attribution_segment(aid,'TEAM_A','IDENTITY')
def test_insufficient_segment_sample_is_not_degraded():
 active_policy(3);add_segment();a=seg.assess_segment('PROD','candidate-prod','TEAM_A','IDENTITY',24,False);assert a['performance_state']=='INSUFFICIENT_SAMPLE'
def test_bad_segment_detected_while_other_segment_can_pass():
 active_policy(3)
 for i in range(3):add_segment(100+i,'TEAM_BAD','IDENTITY')
 for i in range(3):add_segment(1+i,'TEAM_GOOD','IDENTITY')
 bad=seg.assess_segment('PROD','candidate-prod','TEAM_BAD','IDENTITY',24,False);good=seg.assess_segment('PROD','candidate-prod','TEAM_GOOD','IDENTITY',24,False);assert bad['performance_state']=='DEGRADED' and good['performance_state']=='PASS'
def test_horizon_isolated_segment_performance():
 active_policy(2)
 for i in range(2):add_segment(100,'TEAM_A','CAPACITY',24);add_segment(1,'TEAM_A','CAPACITY',168)
 a24=seg.assess_segment('PROD','candidate-prod','TEAM_A','CAPACITY',24,False);a168=seg.assess_segment('PROD','candidate-prod','TEAM_A','CAPACITY',168,False);assert a24['performance_state']=='DEGRADED' and a168['performance_state']=='PASS'
def test_consecutive_segment_breach_triggers_retraining_request():
 active_policy(2,2)
 for i in range(2):add_segment(100+i,'TEAM_A','IDENTITY')
 seg.assess_segment('PROD','candidate-prod','TEAM_A','IDENTITY',24,False);second=seg.assess_segment('PROD','candidate-prod','TEAM_A','IDENTITY',24,True,'segment://breach');st=seg.status('PROD');assert second['performance_state']=='DEGRADED' and len(st['automatic_refresh_triggers'])==1
def test_refresh_enters_existing_governed_pipeline_not_direct_promotion():
 active_policy(2,2)
 for i in range(2):add_segment(120+i,'TEAM_A','IDENTITY')
 seg.assess_segment('PROD','candidate-prod','TEAM_A','IDENTITY',24,False);seg.assess_segment('PROD','candidate-prod','TEAM_A','IDENTITY',24,True,'segment://refresh');rid=seg.status('PROD')['automatic_refresh_triggers'][0]['retraining_request_id']
 with SessionLocal() as s:r=s.get(JourneyRecoveryForecastRetrainingRequestRow,rid);assert r.state=='APPROVED_FOR_REFRESH' and 'ONLINE_SEGMENT_DEGRADATION' in r.refresh_reason_codes_json
def test_supplier_fact_boundary():
 active_policy(2);aid,o=add_segment();assert o['supplier_fact_unchanged'] is True
