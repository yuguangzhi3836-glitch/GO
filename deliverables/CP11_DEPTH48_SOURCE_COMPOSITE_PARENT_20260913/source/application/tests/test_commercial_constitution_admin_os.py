import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_commercial_os_test.db'
import pytest
from datetime import datetime,timezone
from go_hotel.db.session import engine
from go_hotel.db.models import Base,JudgmentRuntimeRow,RecommendationDecisionRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.commercial_constitution import commercial_constitution_service as svc
def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def seed_judgment(property_id='p1',status='GO_RECOMMENDED'):
 t=datetime.now(timezone.utc)
 with SessionLocal() as s:
  s.add(JudgmentRuntimeRow(judgment_id='j1',hotel_id=property_id,evidence_package_id='ep1',go_score_milli=4700,dimension_result={},explanation={},confidence_bps=9000,model_version='m1',prompt_version='p1',rule_version='r1',good_hotel_standard_version_id='ghsv1',status='ACTIVE',public_at=t,valid_from=t,valid_to=None,created_at=t))
  s.add(RecommendationDecisionRow(decision_id='rd1',hotel_id=property_id,judgment_id='j1',status=status,reason_codes=['INDEPENDENT_QUALITY_PASS'],public_go_score_milli=4700,rule_version='rr1',good_hotel_standard_version_id='ghsv1',valid_from=t,valid_to=None,created_at=t));s.commit()
 return 'rd1'
def test_admin_cannot_create_recommendation_without_independent_judgment():
 with pytest.raises(ValueError,match='INDEPENDENT_JUDGMENT_DECISION_REQUIRED'):svc.evaluate_pools('p1',None,True,{'verified_value':True},'admin')
def test_recommendation_and_value_are_independent():
 d=svc.evaluate_pools('p1',seed_judgment(status='NOT_RECOMMENDED'),True,{'verified_value':True},'admin');assert d['output_json']=={'recommendation_eligible':False,'value_eligible':True}
def test_recommendation_eligibility_is_derived_only_from_judgment_decision():
 d=svc.evaluate_pools('p1',seed_judgment(),False,{'commission_rate':.5},'admin');assert d['output_json']=={'recommendation_eligible':True,'value_eligible':False} and d['input_json']['judgment_decision_id']=='rd1'
def test_direct_first_and_governed_fallback():
 with pytest.raises(ValueError,match='FALLBACK_AUTHORITY_REQUIRED'):svc.set_distribution('s1','p1',{'fallback_enabled':True},'admin')
 r=svc.set_distribution('s1','p1',{'direct_enabled':True,'fallback_enabled':True,'fallback_connectors':['certified://c1'],'evidence':[{'reference':'contract://1'}]},'admin');assert r['decision']['output_json']['primary']=='DIRECT'
def t20(order_id,source='OFFICIAL_DIRECT',state='COMPLETED'):
 return svc.record_order_evidence('s1','p1',{'order_id':order_id,'source_type':source,'order_state':state,'evidence':[{'reference':f'order://{order_id}'}]},'system')
def test_t20_is_evidence_driven_fallback_excluded_and_idempotent():
 x=t20('fallback-1','AUTHORIZED_FALLBACK');assert not x['order']['qualifies'] and x['subscription']['qualifying_order_count']==0
 assert t20('fallback-1','AUTHORIZED_FALLBACK')['idempotent_replay']
 r=None
 for i in range(20):r=t20(f'direct-{i}')
 assert r['subscription']['qualifying_order_count']==20 and r['subscription']['state']=='SUBSCRIPTION_REQUIRED'
def test_invoice_policy_waiver_and_maker_checker():
 for i in range(20):t20(f'direct-{i}')
 with pytest.raises(ValueError,match='ACTIVE_SUBSCRIPTION_POLICY_REQUIRED'):svc.issue_invoice('s1','2026-09','finance')
 p=svc.create_policy('T20_SUBSCRIPTION','GLOBAL',{'plan':'THREE_DIAMOND','amount_minor':69900,'currency':'CNY'},'maker');svc.approve_policy(p['policy_version_id'],'checker')
 w=svc.request_waiver('s1','2026-09','launch credit','case://1','maker')
 with pytest.raises(ValueError,match='MAKER_CHECKER'):svc.approve_waiver(w['subscription_waiver_id'],'maker')
 svc.approve_waiver(w['subscription_waiver_id'],'checker');inv=svc.issue_invoice('s1','2026-09','finance');assert inv['state']=='WAIVED' and inv['amount_minor']==0
 assert svc.issue_invoice('s1','2026-09','finance')['subscription_invoice_id']==inv['subscription_invoice_id']
def test_hotel_net_guard_blocks_below_authorized_floor():
 r=svc.assess_net_guard('p1',9000,10000,'CNY',[{'reference':'quote://1'}]);assert r['assessment_state']=='BLOCK'
def test_policy_requires_maker_checker_and_rejects_bought_recommendation_rule():
 with pytest.raises(ValueError,match='CANNOT_BUY'):svc.create_policy('RECOMMENDATION','GLOBAL',{'recommendation_advertising_gate':True},'maker')
 p=svc.create_policy('DIRECT_FIRST','GLOBAL',{'primary':'DIRECT'},'maker')
 with pytest.raises(ValueError,match='MAKER_CHECKER'):svc.approve_policy(p['policy_version_id'],'maker')
 assert svc.approve_policy(p['policy_version_id'],'checker')['state']=='ACTIVE'

def test_invoice_policy_amount_is_fail_closed_no_legacy_default():
 for i in range(20):t20(f'direct-missing-{i}')
 p=svc.create_policy('T20_SUBSCRIPTION','GLOBAL',{'plan':'THREE_DIAMOND','currency':'CNY'},'maker');svc.approve_policy(p['policy_version_id'],'checker')
 with pytest.raises(ValueError,match='SUBSCRIPTION_POLICY_AMOUNT_REQUIRED'):svc.issue_invoice('s1','2026-10','finance')
