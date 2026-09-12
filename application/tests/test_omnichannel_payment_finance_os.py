import os,hashlib,hmac,json
from datetime import datetime,timezone
os.environ['DATABASE_URL']='sqlite:////tmp/go_omnichannel_test.db'
import pytest
from go_hotel.db.models import Base
from go_hotel.db.session import engine
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as svc
def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def intent(key='k1'):
 return svc.create_intent({'business_type':'SUBSCRIPTION_INVOICE','business_id':'inv1','payee_id':'GO','operation':'PAY','amount_minor':69900,'currency':'CNY','channel_priority':['ALIPAY','WECHAT_PAY','VISA']},key,'supplier1')
def test_global_idempotency_and_channel_selection():
 a=intent();b=intent();assert a['payment_intent_id']==b['payment_intent_id'];assert svc.select_channel(a['payment_intent_id'],'ALIPAY','supplier1')['state']=='READY'
 r=svc.checkout_readiness(a['payment_intent_id'],'supplier1');assert r['state']=='BLOCKED' and not r['payment_completed'] and not r['booking_confirmed']
 with pytest.raises(ValueError,match='ACCESS_DENIED'):svc.checkout_readiness(a['payment_intent_id'],'other-user')
def test_timeout_blocks_resend_and_channel_fallback():
 i=intent();svc.select_channel(i['payment_intent_id'],'ALIPAY','supplier1');a=svc.execute(i['payment_intent_id']);svc.simulate_result(a['payment_attempt_id'],'TIMEOUT')
 with pytest.raises(ValueError,match='RECONCILE_BEFORE'):svc.fallback(i['payment_intent_id'],'WECHAT_PAY','supplier1')
 with pytest.raises(ValueError,match='NOT_READY'):svc.execute(i['payment_intent_id'])
def test_explicit_failure_allows_consented_switch_without_silent_fallback():
 i=intent();svc.select_channel(i['payment_intent_id'],'ALIPAY','supplier1');a=svc.execute(i['payment_intent_id']);svc.simulate_result(a['payment_attempt_id'],'FAILED');x=svc.fallback(i['payment_intent_id'],'WECHAT_PAY','supplier1');assert x['selected_channel']=='WECHAT_PAY' and x['user_channel_consent_at']
def test_non_order_obligation_cannot_claim_order_reconciliation():
 i=intent();svc.select_channel(i['payment_intent_id'],'VISA','supplier1');a=svc.execute(i['payment_intent_id']);svc.simulate_result(a['payment_attempt_id'],'SUCCEEDED')
 with pytest.raises(ValueError,match='PAYMENT_ORDER_ROOT_REQUIRED'):
  svc.reconcile(i['payment_intent_id'],{'channel_amount_minor':69900,'bank_amount_minor':69900,'evidence':[{'reference':'bank://statement'}]})
def test_plain_credentials_and_real_executor_are_blocked():
 with pytest.raises(ValueError,match='EXTERNAL_CREDENTIAL'):svc.bind({'owner_type':'GO','owner_id':'GO','channel':'ALIPAY','merchant_reference':'m','credential_reference':'secret','webhook_key_reference':'secret'})
 i=intent();svc.select_channel(i['payment_intent_id'],'ALIPAY','supplier1')
 with pytest.raises(ValueError,match='EXTERNAL_PAYMENT_EXECUTOR'):svc.execute(i['payment_intent_id'],'EXTERNAL_SANDBOX')
def test_signed_webhook_converges_once_and_replay_is_idempotent():
 i=intent();svc.select_channel(i['payment_intent_id'],'ALIPAY','supplier1');a=svc.execute(i['payment_intent_id']);os.environ['GO_PAYMENT_WEBHOOK_KEY_ALIPAY']='k'
 b={'external_event_id':'evt1','payment_attempt_id':a['payment_attempt_id'],'external_operation_id':'trade1','state':'SUCCEEDED','occurred_at':datetime.now(timezone.utc).isoformat()};raw=json.dumps(b,sort_keys=True,separators=(',',':'));sig=hmac.new(b'k',raw.encode(),hashlib.sha256).hexdigest();x=svc.webhook('ALIPAY',b,sig);y=svc.webhook('ALIPAY',b,sig);assert not x['duplicate'] and y['duplicate']
 with pytest.raises(ValueError,match='SIGNATURE_INVALID'):svc.webhook('ALIPAY',{**b,'external_event_id':'evt2'},'bad')
