import os
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/go_sprint4r_test.db')
os.environ['GO_MODEL_BUILD_SIGNING_KEY_BUILDER___ENGINEERING']='sprint4r-secret'
import pytest
from go_hotel.db.session import engine
from go_hotel.db.models import Base
from test_sprint4q_model_serving_attestation import setup_artifact,activate_serving_policy
from go_hotel.journey.recovery_forecast_serving_governance import recovery_forecast_serving_governance_service as serving
from go_hotel.journey.recovery_forecast_traffic_governance import recovery_forecast_traffic_governance_service as traffic

def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def setup_runtime_pair():
 m,a,mf=setup_artifact();activate_serving_policy()
 for key,pod in [('champion-prod','pod://champion'),('candidate-prod','pod://candidate')]:
  serving.bind_deployment('PROD',m['risk_forecast_model_version_id'],a['forecast_model_artifact_id'],key,'deploy://'+key)
  r=serving.register_runtime_identity('PROD',key,pod,m['risk_forecast_model_version_id'],a['forecast_model_artifact_id'])
  serving.attest_serving(r['forecast_runtime_model_identity_id'],a['artifact_digest'],mf['build_hash'],r['runtime_model_fingerprint'],'attest://'+key)
 return m,a,mf
def active_policy(min_requests=2):
 p=traffic.create_policy('PROD','champion-prod','candidate-prod',min_requests_per_step=min_requests,actor='maker');traffic.approve_policy(p['forecast_traffic_policy_id'],'a1');return traffic.approve_policy(p['forecast_traffic_policy_id'],'a2')

def test_policy_maker_checker_and_zero_canary_start():
 setup_runtime_pair();p=traffic.create_policy('PROD','champion-prod','candidate-prod',actor='maker')
 with pytest.raises(ValueError,match='MAKER_CHECKER'):traffic.approve_policy(p['forecast_traffic_policy_id'],'maker')
 traffic.approve_policy(p['forecast_traffic_policy_id'],'a1');traffic.approve_policy(p['forecast_traffic_policy_id'],'a2');assert traffic.status('PROD')['canary_percentage']==0

def test_request_level_prediction_provenance_binds_runtime_identity_and_artifact():
 setup_runtime_pair();active_policy();x=traffic.record_prediction('PROD','team:tokyo',{'value':100},35)
 assert x['serving_role']=='CHAMPION' and len(x['artifact_digest'])==64 and x['forecast_runtime_model_identity_id']

def test_shadow_prediction_is_comparison_only():
 setup_runtime_pair();active_policy();x=traffic.record_prediction('PROD','team:shadow',{'value':100},20);c=traffic.compare_shadow(x['prediction_request_id'],105,{'mode':'SHADOW'})
 assert c['comparison_state']=='PASS' and c['supplier_fact_unchanged'] is True

def test_canary_progression_is_sequential_and_health_gated():
 setup_runtime_pair();active_policy(2)
 with pytest.raises(ValueError,match='TRAFFIC_HEALTH'):traffic.progress_canary('PROD',1,'gate://early')
 traffic.assess_budget('PROD',2,.001,.001,100);assert traffic.progress_canary('PROD',1,'gate://pass')['canary_percentage']==1
 with pytest.raises(ValueError,match='SEQUENTIAL'):traffic.progress_canary('PROD',10,'gate://skip')

def test_serving_error_budget_breach_freezes_progression():
 setup_runtime_pair();active_policy(2);a=traffic.assess_budget('PROD',10,.5,.1,5000);assert a['assessment_state']=='BREACH'
 with pytest.raises(ValueError,match='TRAFFIC_HEALTH'):traffic.progress_canary('PROD',1,'gate://blocked')

def test_unattested_candidate_gets_zero_canary_traffic():
 m,a,mf=setup_runtime_pair();active_policy(1)
 # supersede candidate binding with a fresh unattested binding
 serving.bind_deployment('PROD',m['risk_forecast_model_version_id'],a['forecast_model_artifact_id'],'candidate-prod','deploy://unattested')
 traffic.assess_budget('PROD',1,0,0,10)
 with pytest.raises(ValueError,match='VERIFIED_MODEL_SERVING_ATTESTATION_REQUIRED'):traffic.progress_canary('PROD',1,'gate://deny')

def test_rollback_changes_future_routing_not_history():
 setup_runtime_pair();active_policy(1);traffic.assess_budget('PROD',1,0,0,10);traffic.progress_canary('PROD',1,'gate://pass');before=traffic.record_prediction('PROD','stable-subject',{'value':7},10);r=traffic.rollback('PROD','rollback://safety');after=traffic.status('PROD')
 assert r['canary_percentage']==0 and after['champion_percentage']==100 and before['prediction_request_id']

def test_supplier_fact_boundary():
 setup_runtime_pair();active_policy();x=traffic.record_prediction('PROD','boundary',{'value':1},5);assert x['supplier_fact_unchanged'] is True
