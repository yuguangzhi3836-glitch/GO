import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_money_movement_test.db'
import pytest
from datetime import datetime,timezone
from go_hotel.db.models import Base,OrderRow,VerticalSourceDecisionRow
from go_hotel.db.session import engine,SessionLocal
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as pay
from go_hotel.services.unified_money_movement import unified_money_movement_service as svc
def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def root():
 t=datetime.now(timezone.utc)
 with SessionLocal() as s:
  s.add(OrderRow(order_id='o1',prebook_id='pb1',hotel_id='hotel1',account_id='guest',total_amount_minor=10000,currency='CNY',status='PENDING_PAYMENT',supplier_confirmation_no=None,supplier_id='hotel1',version=1,created_at=t,updated_at=t))
  s.add(VerticalSourceDecisionRow(vertical_source_decision_id='vsd1',vertical='HOTEL',business_id='o1',selected_source_id='hotel1',selected_source_type='DIRECT',route='DIRECT',authority_reference='contract://hotel/authority',evidence_reference='contract://hotel/o1',candidate_snapshot_json=[],reason_codes_json=['DIRECT_FIRST'],decision_hash='decision-hash',created_at=t))
  s.commit()
 i=pay.create_intent({'business_type':'HOTEL_ORDER','business_id':'o1','payee_id':'hotel1','operation':'AUTHORIZE','amount_minor':10000,'currency':'CNY','channel_priority':['ALIPAY']},'root','guest');pay.select_channel(i['payment_intent_id'],'ALIPAY','guest');attempt=pay.execute(i['payment_intent_id']);pay.simulate_result(attempt['payment_attempt_id'],'SUCCEEDED');return i
def move(i,t,k,amount=10000):return svc.create(i['payment_intent_id'],{'movement_type':t,'amount_minor':amount,'mode':'CONTRACT_SIMULATOR','evidence':[{'reference':f'contract://{t}'}]},k,'finance')
def test_authorize_capture_refund_chain_and_idempotency():
 i=root();move(i,'AUTHORIZATION','a');move(i,'CAPTURE','c');r=move(i,'REFUND','r',4000);assert r['state']=='CONFIRMED' and move(i,'REFUND','r',4000)['money_movement_id']==r['money_movement_id']
 with pytest.raises(ValueError,match='EXCEEDS_CAPTURE'):move(i,'COMPENSATION','too-much',7000)
def test_capture_requires_authorization():
 i=root()
 with pytest.raises(ValueError,match='CUMULATIVE_CAPTURE_EXCEEDS_AUTHORIZATION'):move(i,'CAPTURE','c')
def close_scope():
 day=datetime.now(timezone.utc).date()
 return {'legal_entity_id':'GO_CN','currency':'CNY','period_start':day.isoformat(),'period_end':day.isoformat(),'cutoff_at':datetime.combine(day,datetime.max.time(),tzinfo=timezone.utc).isoformat()}
def test_close_blocks_when_capture_reconciliation_is_missing():
 i=root();move(i,'AUTHORIZATION','a');move(i,'CAPTURE','c');c=svc.prepare_close(close_scope(),'maker');assert c['state']=='BLOCKED' and any(x.startswith('RECON_MISSING:') for x in c['blockers_json'])
def test_external_executor_required_blocks_close():
 i=root();svc.create(i['payment_intent_id'],{'movement_type':'AUTHORIZATION','mode':'EXTERNAL_SANDBOX','evidence':[{'reference':'sandbox://pending'}]},'external','finance');c=svc.prepare_close(close_scope(),'maker');assert c['state']=='BLOCKED' and c['blockers_json']
