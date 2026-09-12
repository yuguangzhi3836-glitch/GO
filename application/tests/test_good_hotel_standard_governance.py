import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_good_hotel_standard_test.db'
import pytest
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import Base,GoodHotelStandardVersionRow,JudgmentRuntimeRow,RecommendationDecisionRow
from go_hotel.judgment.good_hotel_standard import good_hotel_standard_service as svc
from go_hotel.services.commercial_constitution import commercial_constitution_service as commercial
def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def payload():return {'dimensions':['CLEANLINESS','SAFETY','FULFILLMENT_TRUTH'],'thresholds':{'recommended_score_milli':4200},'disqualifiers':['UNRESOLVED_CONFIRMED_SERIOUS_RISK'],'evidence_requirements':{'required':['GO_TRUTH']}}
def test_initial_go_good_hotel_standard_is_active_and_versioned():
 r=svc.active();assert r.state=='ACTIVE' and r.standard_key=='GO_GOOD_HOTEL_STANDARD' and r.content_hash
def test_standard_change_requires_maker_checker():
 r=svc.create(payload(),'maker')
 with pytest.raises(ValueError,match='MAKER_CHECKER'):svc.approve(r['good_hotel_standard_version_id'],'maker')
 assert svc.approve(r['good_hotel_standard_version_id'],'checker')['state']=='ACTIVE'
def test_commercial_and_popularity_fields_are_forbidden_from_standard():
 b=payload();b['thresholds']['commission']=.1
 with pytest.raises(ValueError,match='COMMERCIAL_OR_POPULARITY'):svc.create(b,'maker')
def test_commercial_os_requires_same_standard_binding_on_judgment_and_recommendation():
 from datetime import datetime,timezone
 t=datetime.now(timezone.utc)
 with SessionLocal() as s:
  s.add(JudgmentRuntimeRow(judgment_id='j',hotel_id='h',evidence_package_id='e',go_score_milli=4500,dimension_result={},explanation={},confidence_bps=9000,model_version='m',prompt_version='p',rule_version='r',good_hotel_standard_version_id='standard-a',status='ACTIVE',public_at=t,valid_from=t,created_at=t))
  s.add(RecommendationDecisionRow(decision_id='d',hotel_id='h',judgment_id='j',status='GO_RECOMMENDED',reason_codes=[],public_go_score_milli=4500,rule_version='rr',good_hotel_standard_version_id='standard-b',valid_from=t,created_at=t));s.commit()
 with pytest.raises(ValueError,match='GOOD_HOTEL_STANDARD_BINDING_REQUIRED'):commercial.evaluate_pools('h','d',False,{},'admin')
