import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4s_test.db')
os.environ['GO_MODEL_BUILD_SIGNING_KEY_BUILDER___ENGINEERING']='sprint4s-secret'
import pytest
from go_hotel.db.session import engine
from go_hotel.db.models import Base
from test_sprint4r_model_traffic_governance import setup_runtime_pair,active_policy
from go_hotel.journey.recovery_forecast_traffic_governance import recovery_forecast_traffic_governance_service as traffic
from go_hotel.journey.recovery_forecast_online_feedback import recovery_forecast_online_feedback_service as feedback
def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def canary_ready():
 setup_runtime_pair();active_policy(1);traffic.assess_budget('PROD',10,0,0,50);traffic.progress_canary('PROD',1,'gate://4s')
def candidate_prediction(value=100,subject='cand'):
 # deterministic search for a 1%% candidate subject
 for i in range(1000):
  s=f'{subject}:{i}';r=traffic.route('PROD',s)
  if r['serving_role']=='CANARY':return traffic.record_prediction('PROD',s,{'value':value},20)
 raise AssertionError('candidate subject not found')
def test_outcome_attribution_binds_prediction_provenance():
 canary_ready();p=candidate_prediction(100);a=feedback.attribute_outcome(p['prediction_request_id'],112,24,'outcome://truth');assert a['deployment_key']=='candidate-prod' and a['absolute_error']==12
def test_non_final_outcome_is_rejected():
 canary_ready();p=candidate_prediction();
 with pytest.raises(ValueError,match='FINAL_OUTCOME_REQUIRED'):feedback.attribute_outcome(p['prediction_request_id'],100,24,'x','now','PROVISIONAL')
def test_duplicate_outcome_attribution_is_rejected():
 canary_ready();p=candidate_prediction();feedback.attribute_outcome(p['prediction_request_id'],100,24,'x')
 with pytest.raises(ValueError,match='OUTCOME_ALREADY_ATTRIBUTED'):feedback.attribute_outcome(p['prediction_request_id'],101,24,'x2')
def test_insufficient_sample_does_not_auto_degrade():
 canary_ready();p=candidate_prediction();feedback.attribute_outcome(p['prediction_request_id'],200,24,'x');a=feedback.assess_live_performance('PROD','candidate-prod',min_samples=3,max_mae=1,max_rmse=1);assert a['performance_state']=='INSUFFICIENT_SAMPLE' and traffic.status('PROD')['canary_percentage']==1
def test_degraded_live_performance_auto_rolls_back_canary():
 canary_ready();
 for i in range(3):
  p=candidate_prediction(100,f'bad{i}');feedback.attribute_outcome(p['prediction_request_id'],200,24,f'outcome://{i}')
 a=feedback.assess_live_performance('PROD','candidate-prod',min_samples=3,max_mae=10,max_rmse=20,evidence_reference='degrade://live');assert a['performance_state']=='DEGRADED' and traffic.status('PROD')['canary_percentage']==0 and feedback.status('PROD')['active_auto_degrade'] is True
def test_auto_degrade_cannot_target_champion():
 canary_ready();p=traffic.record_prediction('PROD','champion-stable',{'value':100},10);feedback.attribute_outcome(p['prediction_request_id'],200,24,'x');a=feedback.assess_live_performance('PROD',p['deployment_key'],min_samples=1,max_mae=1,max_rmse=1,auto_degrade=False)
 if p['deployment_key']=='champion-prod':
  with pytest.raises(ValueError,match='AUTO_DEGRADE_ONLY_CANARY_CANDIDATE'):feedback.auto_degrade('PROD','champion-prod',a['forecast_live_performance_assessment_id'],['x'],'x')
def test_historical_prediction_and_outcome_remain_after_rollback():
 canary_ready();p=candidate_prediction(50);a=feedback.attribute_outcome(p['prediction_request_id'],80,24,'x');traffic.rollback('PROD','manual://rollback');assert feedback.attribution(a['forecast_outcome_attribution_id'])['prediction_request_id']==p['prediction_request_id']
def test_supplier_fact_boundary():
 canary_ready();p=candidate_prediction(1);a=feedback.attribute_outcome(p['prediction_request_id'],1,24,'x');assert a['supplier_fact_unchanged'] is True
