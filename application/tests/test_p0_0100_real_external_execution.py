from datetime import datetime,timezone,timedelta
import hashlib,hmac,json,os
import httpx
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (OrderRow,ExternalSandboxCredentialBindingRow as Cred,NamedSupplierAdapterRow as Adapter,
 NamedSupplierAdapterBindingRow as Binding,ExternalSandboxExecutionAuthorizationRow as Auth,OrderSupplierFulfillmentRow,
 ConsumerUnifiedLifecycleRow,OmnichannelMoneyMovementRow,ExternalTruthWebhookReceiptRow,BankStatementLineRow,ExternalTruthBankFeedReceiptRow,ExternalTruthOperationRow)
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service as source
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as pay
from go_hotel.services.real_external_execution import real_external_execution_service as real
from go_hotel.services.production_connector_runtime import production_connector_runtime_service as command_center

SECRET='p0-0100-secret'
def sig(payload):return hmac.new(SECRET.encode(),json.dumps(payload,sort_keys=True,separators=(',',':'),default=str).encode(),hashlib.sha256).hexdigest()
class Resp:
 def __init__(self,payload,status=202):self._payload=payload;self.status_code=status;self.content=b'1'
 def json(self):return self._payload

def setup_auth():
 os.environ['GO_EXTERNAL_SANDBOX_NETWORK_ENABLED']='1';os.environ['GO_ALLOW_HTTP_EXTERNAL_SANDBOX']='1';os.environ['GO_P0_0100_SECRET']=SECRET
 with SessionLocal() as s:
  s.add_all([
   Cred(credential_binding_id='cred-h',supplier_intake_id='intake-1',vertical='HOTEL',vault_provider='ENV',secret_reference='env://GO_P0_0100_SECRET',credential_fingerprint='h',access_test_state='PASS',updated_at=datetime.now(timezone.utc)),
   Cred(credential_binding_id='cred-p',supplier_intake_id='intake-1',vertical='PAYMENT',vault_provider='ENV',secret_reference='env://GO_P0_0100_SECRET',credential_fingerprint='p',access_test_state='PASS',updated_at=datetime.now(timezone.utc)),
   Adapter(named_adapter_id='ad-h',supplier_intake_id='intake-1',vertical='HOTEL',supplier_name='Hotel Sandbox',adapter_key='hotel-sandbox-0100',adapter_version=1,capability_manifest_json=['BOOK','QUERY','CANCEL','WEBHOOK'],implementation_reference='test://adapter',state='IMPLEMENTATION_VERIFIED',updated_at=datetime.now(timezone.utc)),
   Adapter(named_adapter_id='ad-p',supplier_intake_id='intake-1',vertical='PAYMENT',supplier_name='PSP Sandbox',adapter_key='psp-sandbox-0100',adapter_version=1,capability_manifest_json=['AUTHORIZE','CAPTURE','REFUND','SETTLEMENT','CALLBACK'],implementation_reference='test://adapter',state='IMPLEMENTATION_VERIFIED',updated_at=datetime.now(timezone.utc)),
   Binding(adapter_binding_id='bind-h',named_adapter_id='ad-h',endpoint_reference='http://supplier.local/execute',credential_binding_id='cred-h',allowlist_reference='test://allow',test_resource_reference='hotel-1',configuration_attested=True,state='BOUND_AND_ATTESTED',updated_at=datetime.now(timezone.utc)),
   Binding(adapter_binding_id='bind-p',named_adapter_id='ad-p',endpoint_reference='http://psp.local/execute',credential_binding_id='cred-p',allowlist_reference='test://allow',test_resource_reference='acct-1',configuration_attested=True,state='BOUND_AND_ATTESTED',updated_at=datetime.now(timezone.utc)),
   Auth(execution_authorization_id='auth-0100',certification_suite_id='suite-1',hotel_adapter_binding_id='bind-h',psp_adapter_binding_id='bind-p',maker_id='maker',checker_id='checker',evidence_reference='approval://0100',state='APPROVED_EXTERNAL_SANDBOX_ONLY',approved_at=datetime.now(timezone.utc),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))])
  s.commit()

def seed_order():
 with SessionLocal() as s:
  s.add(OrderRow(order_id='hotel-order-0100',prebook_id='pb-0100',hotel_id='hotel-1',account_id='guest-0100',total_amount_minor=12000,currency='CNY',status='PENDING_PAYMENT',supplier_confirmation_no=None,supplier_id=None,version=1,created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc)));s.commit()
 source.decide('HOTEL','hotel-order-0100',[{'source_id':'hotel-supplier-0100','source_type':'HOTEL_OFFICIAL_DIRECT','authorized':True,'available':True,'evidence_reference':'supplier-authority://0100'}])
 i=pay.create_intent({'business_type':'HOTEL_ORDER','business_id':'hotel-order-0100','channel_priority':['ALIPAY']},'idem-0100','guest-0100');pay.select_channel(i['payment_intent_id'],'ALIPAY','guest-0100');return i

def test_0100_real_transport_is_fail_closed_without_network_enable():
 setup_auth();i=seed_order();os.environ['GO_EXTERNAL_SANDBOX_NETWORK_ENABLED']='0'
 try:real.execute_payment(i['payment_intent_id'],'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'real-auth-0100'})
 except ValueError as e:assert str(e)=='REAL_EXTERNAL_NETWORK_EXECUTION_NOT_ENABLED'
 else:assert False

def test_0100_signed_psp_and_supplier_callbacks_drive_0099_truth_chain(monkeypatch):
 setup_auth();i=seed_order();iid=i['payment_intent_id']
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:Resp({'external_operation_id':'ext-'+payload['operation'].lower()}))
 op=real.execute_payment(iid,'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'real-auth-0100'})
 p={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-authorize','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()};r=real.payment_callback(op['external_truth_operation_id'],'pay-delivery-auth',p,sig(p));assert r['intent']['state']=='SUCCEEDED' and r['money_movement']['movement_type']=='AUTHORIZATION'
 capop=real.execute_payment(iid,'auth-0100',{'operation':'CAPTURE','idempotency_key':'real-cap-0100','amount_minor':12000})
 cp={'state':'SUCCEEDED','operation':'CAPTURE','external_operation_id':'ext-capture','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()};cr=real.payment_callback(capop['external_truth_operation_id'],'pay-delivery-cap',cp,sig(cp));assert cr['money_movement']['movement_type']=='CAPTURE'
 with SessionLocal() as s:
  f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.payment_intent_id==iid));assert f.state=='CAPTURE_CONFIRMED_READY_FOR_SUPPLIER';fid=f.order_supplier_fulfillment_id
 sop=real.execute_supplier(fid,'auth-0100',{'operation':'BOOK','idempotency_key':'real-book-0100','facts':{'room':'DLX'}})
 sp={'state':'CONFIRMED','external_operation_id':'ext-book','supplier_confirmation_reference':'HC-0100'};sr=real.supplier_callback(sop['external_truth_operation_id'],'hotel-delivery-1',sp,sig(sp));assert sr['result']['unified_lifecycle']['lifecycle_state']=='CONFIRMED'
 with SessionLocal() as s:
  assert s.get(OrderRow,'hotel-order-0100').status=='CONFIRMED'
  life=s.scalar(select(ConsumerUnifiedLifecycleRow).where(ConsumerUnifiedLifecycleRow.vertical=='HOTEL',ConsumerUnifiedLifecycleRow.order_id=='hotel-order-0100'));assert life and life.payment_state=='PAID'
  assert len(s.scalars(select(ExternalTruthWebhookReceiptRow)).all())==3


def test_0100_callback_fact_mutations_are_refused_before_money_movement(monkeypatch):
 setup_auth();i=seed_order();iid=i['payment_intent_id']
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:Resp({'external_operation_id':'ext-'+payload['operation'].lower()}))
 op=real.execute_payment(iid,'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'real-auth-mutations'})
 base={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-authorize','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 cases=[({'operation':'CAPTURE'},'OPERATION_MISMATCH'),({'amount_minor':1},'AMOUNT_MISMATCH'),({'currency':'USD'},'CURRENCY_MISMATCH'),({'external_operation_id':'forged'},'OPERATION_REFERENCE_MISMATCH')]
 for n,(mutation,reason) in enumerate(cases):
  body={**base,**mutation}
  with pytest.raises(ValueError,match=reason):
   real.payment_callback(op['external_truth_operation_id'],f'mutation-{n}',body,sig(body))
 with SessionLocal() as s:
  assert not s.scalars(select(ExternalTruthWebhookReceiptRow)).all()
  assert not s.scalars(select(OmnichannelMoneyMovementRow)).all()

def test_0100_payment_callback_requires_external_operation_and_rejects_delivery_conflict(monkeypatch):
 setup_auth();i=seed_order();iid=i['payment_intent_id']
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:Resp({'external_operation_id':'ext-'+payload['operation'].lower()}))
 op=real.execute_payment(iid,'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'real-auth-delivery'})
 missing={'state':'SUCCEEDED','operation':'AUTHORIZE','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 with pytest.raises(ValueError,match='CALLBACK_FACTS_REQUIRED'):
  real.payment_callback(op['external_truth_operation_id'],'payment-delivery-missing',missing,sig(missing))
 body={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-authorize','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 first=real.payment_callback(op['external_truth_operation_id'],'payment-delivery-conflict',body,sig(body))
 assert first['money_movement']['movement_type']=='AUTHORIZATION'
 changed={**body,'state':'FAILED'}
 with pytest.raises(ValueError,match='DELIVERY_PAYLOAD_CONFLICT'):
  real.payment_callback(op['external_truth_operation_id'],'payment-delivery-conflict',changed,sig(changed))
 with SessionLocal() as s:
  assert len(s.scalars(select(ExternalTruthWebhookReceiptRow)).all())==1
  assert len(s.scalars(select(OmnichannelMoneyMovementRow)).all())==1

def test_0100_signed_settlement_bank_feed_and_reconciliation(monkeypatch):
 setup_auth();i=seed_order();iid=i['payment_intent_id'];monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:Resp({'external_operation_id':'ext-'+payload['operation'].lower()}))
 op=real.execute_payment(iid,'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'real-auth-0100'});p={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-authorize','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()};real.payment_callback(op['external_truth_operation_id'],'d-a',p,sig(p))
 cap=real.execute_payment(iid,'auth-0100',{'operation':'CAPTURE','idempotency_key':'real-cap-0100'});cp={'state':'SUCCEEDED','operation':'CAPTURE','external_operation_id':'ext-capture','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()};real.payment_callback(cap['external_truth_operation_id'],'d-c',cp,sig(cp))
 t=datetime.now(timezone.utc).isoformat();sett={'external_transaction_id':'psp-tx-0100','amount_minor':12000,'currency':'CNY','evidence_reference':'psp://settlement/0100','occurred_at':t};real.psp_settlement_callback(cap['external_truth_operation_id'],'d-settle',sett,sig(sett))
 os.environ['GO_BANK_FEED_KEY_TESTBANK']=SECRET
 feed={'evidence_reference':'bank://feed/0100','lines':[{'bank_line_identity':'bank-line-0100','legal_entity_id':'GO_CN','amount_minor':12000,'currency':'CNY','payment_reference':'psp-tx-0100','evidence_reference':'bank://line/0100','booked_at':t}]};real.bank_feed('testbank','bank-delivery-0100',feed,sig(feed))
 rec=real.reconcile(iid,'psp-tx-0100');assert rec['state']=='MATCHED' and rec['ledger_amount_minor']==12000


def test_0100_capture_and_refund_are_blocked_before_external_dispatch(monkeypatch):
 setup_auth();i=seed_order();iid=i['payment_intent_id']
 dispatched=[]
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:dispatched.append(payload) or Resp({'external_operation_id':'unexpected'}))
 with pytest.raises(ValueError,match='PAYMENT_SUCCESS_REQUIRED_FOR_EXTERNAL_MONEY_OPERATION'):
  real.execute_payment(iid,'auth-0100',{'operation':'CAPTURE','idempotency_key':'cap-before-auth'})
 with pytest.raises(ValueError,match='PAYMENT_SUCCESS_REQUIRED_FOR_EXTERNAL_MONEY_OPERATION'):
  real.execute_payment(iid,'auth-0100',{'operation':'REFUND','idempotency_key':'refund-before-capture'})
 assert dispatched==[]

def test_0100_stale_payment_callback_is_rejected_without_receipt_or_movement(monkeypatch):
 setup_auth();i=seed_order()
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:Resp({'external_operation_id':'ext-authorize'}))
 op=real.execute_payment(i['payment_intent_id'],'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'stale-callback'})
 stale={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-authorize','amount_minor':12000,'currency':'CNY','occurred_at':(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()}
 with pytest.raises(ValueError,match='OUTSIDE_REPLAY_WINDOW'):
  real.payment_callback(op['external_truth_operation_id'],'stale-delivery',stale,sig(stale))
 with SessionLocal() as s:
  assert not s.scalars(select(ExternalTruthWebhookReceiptRow)).all()
  assert not s.scalars(select(OmnichannelMoneyMovementRow)).all()

def test_0100_settlement_requires_confirmed_capture_and_stays_atomic(monkeypatch):
 setup_auth();i=seed_order()
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:Resp({'external_operation_id':'ext-authorize'}))
 op=real.execute_payment(i['payment_intent_id'],'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'settle-before-capture'})
 payload={'external_transaction_id':'psp-before-capture','amount_minor':12000,'currency':'CNY','evidence_reference':'psp://settlement/before-capture','occurred_at':datetime.now(timezone.utc).isoformat()}
 with pytest.raises(ValueError,match='PSP_SETTLEMENT_CAPTURE_OPERATION_REQUIRED'):
  real.psp_settlement_callback(op['external_truth_operation_id'],'settle-before-capture',payload,sig(payload))
 with SessionLocal() as s:
  assert not s.scalars(select(ExternalTruthWebhookReceiptRow)).all()


def test_0100_accepted_capture_without_provider_operation_id_blocks_resend(monkeypatch):
 setup_auth();i=seed_order();iid=i['payment_intent_id']
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:Resp({'external_operation_id':'ext-'+payload['operation'].lower()}))
 auth=real.execute_payment(iid,'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'missing-op-auth'})
 body={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-authorize','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 real.payment_callback(auth['external_truth_operation_id'],'missing-op-auth-callback',body,sig(body))
 dispatched=[]
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:dispatched.append(payload) or Resp({}))
 first=real.execute_payment(iid,'auth-0100',{'operation':'CAPTURE','idempotency_key':'missing-op-capture'})
 assert first['state']=='UNKNOWN_EXTERNAL_STATE' and dispatched
 with pytest.raises(ValueError,match='OPERATION_RECONCILIATION_REQUIRED'):
  real.execute_payment(iid,'auth-0100',{'operation':'CAPTURE','idempotency_key':'missing-op-capture-retry'})
 assert len(dispatched)==1


def test_0100_bank_feed_batch_is_atomic_and_conflicting_delivery_is_rejected():
 setup_auth();os.environ['GO_BANK_FEED_KEY_TESTBANK']=SECRET
 timestamp=datetime.now(timezone.utc).isoformat()
 good={'bank_line_identity':'atomic-line-1','legal_entity_id':'GO_CN','amount_minor':12000,'currency':'CNY','payment_reference':'atomic-psp','evidence_reference':'bank://atomic/1','booked_at':timestamp}
 invalid={'bank_line_identity':'atomic-line-2','legal_entity_id':'GO_CN','amount_minor':12000,'currency':'CNY','payment_reference':'atomic-psp','evidence_reference':'bank://atomic/2'}
 broken={'evidence_reference':'bank://atomic/feed','lines':[good,invalid]}
 with pytest.raises(ValueError,match='BANK_STATEMENT_FACT_REQUIRED'):
  real.bank_feed('testbank','atomic-batch',broken,sig(broken))
 with SessionLocal() as s:
  assert not s.scalars(select(BankStatementLineRow)).all()
  assert not s.scalars(select(ExternalTruthBankFeedReceiptRow)).all()
 valid={'evidence_reference':'bank://atomic/feed','lines':[good]}
 first=real.bank_feed('testbank','atomic-batch',valid,sig(valid))
 assert first['receipt']['imported_line_count']==1
 changed={**valid,'evidence_reference':'bank://atomic/changed'}
 with pytest.raises(ValueError,match='BANK_FEED_DELIVERY_PAYLOAD_CONFLICT'):
  real.bank_feed('testbank','atomic-batch',changed,sig(changed))
 with SessionLocal() as s:
  assert len(s.scalars(select(BankStatementLineRow)).all())==1
  assert len(s.scalars(select(ExternalTruthBankFeedReceiptRow)).all())==1


def test_0100_identical_external_facts_are_idempotent_and_mutations_are_refused(monkeypatch):
 setup_auth();i=seed_order();iid=i['payment_intent_id']
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:Resp({'external_operation_id':'ext-'+payload['operation'].lower()}))
 auth=real.execute_payment(iid,'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'fact-replay-auth'})
 ap={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-authorize','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 real.payment_callback(auth['external_truth_operation_id'],'fact-replay-auth-callback',ap,sig(ap))
 cap=real.execute_payment(iid,'auth-0100',{'operation':'CAPTURE','idempotency_key':'fact-replay-cap'})
 cp={'state':'SUCCEEDED','operation':'CAPTURE','external_operation_id':'ext-capture','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 real.payment_callback(cap['external_truth_operation_id'],'fact-replay-cap-callback',cp,sig(cp))
 settlement={'external_transaction_id':'fact-replay-psp','amount_minor':12000,'currency':'CNY','evidence_reference':'psp://fact/replay','occurred_at':datetime.now(timezone.utc).isoformat()}
 real.psp_settlement_callback(cap['external_truth_operation_id'],'fact-replay-settle-1',settlement,sig(settlement))
 same=real.psp_settlement_callback(cap['external_truth_operation_id'],'fact-replay-settle-2',settlement,sig(settlement))
 assert same['psp_line']['external_transaction_id']=='fact-replay-psp'
 changed={**settlement,'evidence_reference':'psp://fact/mutated'}
 with pytest.raises(ValueError,match='PSP_SETTLEMENT_TRANSACTION_FACT_CONFLICT'):
  real.psp_settlement_callback(cap['external_truth_operation_id'],'fact-replay-settle-3',changed,sig(changed))
 os.environ['GO_BANK_FEED_KEY_TESTBANK']=SECRET
 line={'bank_line_identity':'fact-replay-bank','legal_entity_id':'GO_CN','amount_minor':12000,'currency':'CNY','payment_reference':'fact-replay-psp','evidence_reference':'bank://fact/replay','booked_at':settlement['occurred_at']}
 feed={'evidence_reference':'bank://fact/feed','lines':[line]}
 real.bank_feed('testbank','fact-replay-bank-1',feed,sig(feed))
 same_feed=real.bank_feed('testbank','fact-replay-bank-2',feed,sig(feed))
 assert same_feed['lines'][0]['bank_line_identity']=='fact-replay-bank'
 mutated_feed={'evidence_reference':'bank://fact/feed','lines':[{**line,'amount_minor':1}]}
 with pytest.raises(ValueError,match='BANK_STATEMENT_LINE_FACT_CONFLICT'):
  real.bank_feed('testbank','fact-replay-bank-3',mutated_feed,sig(mutated_feed))
 with SessionLocal() as s:
  assert len(s.scalars(select(BankStatementLineRow).where(BankStatementLineRow.bank_line_identity=='fact-replay-bank')).all())==1


def test_0100_capture_dispatch_claim_exists_before_network_and_blocks_replay(monkeypatch):
 setup_auth();i=seed_order();iid=i['payment_intent_id']
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:Resp({'external_operation_id':'ext-authorize'}))
 auth=real.execute_payment(iid,'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'claim-auth'})
 body={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-authorize','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 real.payment_callback(auth['external_truth_operation_id'],'claim-auth-callback',body,sig(body))
 observed=[]
 def crash_window(url,payload,headers):
  with SessionLocal() as s:
   row=s.scalar(select(ExternalTruthOperationRow).where(ExternalTruthOperationRow.payment_intent_id==iid,ExternalTruthOperationRow.operation_type=='CAPTURE'))
   observed.append(row.state if row else None)
  raise httpx.TimeoutException('simulated crash window')
 monkeypatch.setattr(real,'_post_json',crash_window)
 first=real.execute_payment(iid,'auth-0100',{'operation':'CAPTURE','idempotency_key':'claim-capture'})
 assert observed==['DISPATCHING'] and first['state']=='UNKNOWN_EXTERNAL_STATE'
 with pytest.raises(ValueError,match='OPERATION_RECONCILIATION_REQUIRED'):
  real.execute_payment(iid,'auth-0100',{'operation':'CAPTURE','idempotency_key':'claim-capture-retry'})


def test_0100_capture_terminal_callback_cannot_be_reversed_by_late_delivery(monkeypatch):
 setup_auth();i=seed_order();iid=i['payment_intent_id']
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:Resp({'external_operation_id':'ext-'+payload['operation'].lower()}))
 auth=real.execute_payment(iid,'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'terminal-auth'})
 ap={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-authorize','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 real.payment_callback(auth['external_truth_operation_id'],'terminal-auth-callback',ap,sig(ap))
 cap=real.execute_payment(iid,'auth-0100',{'operation':'CAPTURE','idempotency_key':'terminal-capture'})
 success={'state':'SUCCEEDED','operation':'CAPTURE','external_operation_id':'ext-capture','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 real.payment_callback(cap['external_truth_operation_id'],'terminal-capture-success',success,sig(success))
 late_failure={**success,'state':'FAILED'}
 with pytest.raises(ValueError,match='TERMINAL_STATE_CONFLICT'):
  real.payment_callback(cap['external_truth_operation_id'],'terminal-capture-late-failure',late_failure,sig(late_failure))
 with SessionLocal() as s:
  op=s.get(ExternalTruthOperationRow,cap['external_truth_operation_id'])
  assert op.state=='CALLBACK_SUCCEEDED'
  assert len(s.scalars(select(ExternalTruthWebhookReceiptRow).where(ExternalTruthWebhookReceiptRow.external_truth_operation_id==cap['external_truth_operation_id'])).all())==1
  assert len(s.scalars(select(OmnichannelMoneyMovementRow).where(OmnichannelMoneyMovementRow.root_payment_intent_id==iid,OmnichannelMoneyMovementRow.movement_type=='CAPTURE')).all())==1


def test_0100_unknown_payment_dispatch_enters_command_center_lease_queue(monkeypatch):
 setup_auth();i=seed_order()
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:(_ for _ in ()).throw(httpx.TimeoutException('unknown')))
 result=real.execute_payment(i['payment_intent_id'],'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'queue-unknown'})
 case=result['command_center_reconciliation']['reconciliation']
 assert result['state']=='UNKNOWN_EXTERNAL_STATE' and case['state']=='MANUAL_REVIEW'
 claim=command_center.claim(case['reconciliation_id'],'payment-operator',60)
 assert claim['reconciliation']['claimed_by']=='payment-operator'
 replay=command_center.claim(case['reconciliation_id'],'payment-operator',60)
 assert replay['replay'] is True


def test_0100_concurrent_same_delivery_creates_one_receipt_and_movement(monkeypatch):
 setup_auth();i=seed_order();iid=i['payment_intent_id']
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:Resp({'external_operation_id':'ext-authorize'}))
 op=real.execute_payment(iid,'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'concurrent-delivery'})
 body={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-authorize','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 signature=sig(body)
 with ThreadPoolExecutor(max_workers=2) as pool:
  results=list(pool.map(lambda _:real.payment_callback(op['external_truth_operation_id'],'concurrent-delivery',body,signature),range(2)))
 assert sorted(x['duplicate'] for x in results)==[False,True]
 with SessionLocal() as s:
  assert len(s.scalars(select(ExternalTruthWebhookReceiptRow).where(ExternalTruthWebhookReceiptRow.external_truth_operation_id==op['external_truth_operation_id'])).all())==1
  assert len(s.scalars(select(OmnichannelMoneyMovementRow).where(OmnichannelMoneyMovementRow.root_payment_intent_id==iid,OmnichannelMoneyMovementRow.movement_type=='AUTHORIZATION')).all())==1


def test_0100_verified_callback_converges_claimed_command_center_case(monkeypatch):
 setup_auth();i=seed_order()
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:(_ for _ in ()).throw(httpx.TimeoutException('unknown')))
 pending=real.execute_payment(i['payment_intent_id'],'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'queue-converge'})
 case=pending['command_center_reconciliation']['reconciliation']
 command_center.claim(case['reconciliation_id'],'payment-operator',60)
 body={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-recovered','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 resolved=real.payment_callback(pending['external_truth_operation_id'],'queue-converge-callback',body,sig(body))['command_center_reconciliation']
 assert resolved['operation']['state']=='CONFIRMED'
 assert resolved['reconciliation']['state']=='CONVERGED'
 assert resolved['reconciliation']['claimed_by'] is None and resolved['reconciliation']['lease_expires_at'] is None
 with pytest.raises(ValueError,match='INCIDENT_NOT_CLAIMABLE'):
  command_center.claim(case['reconciliation_id'],'another-operator',60)


def test_0100_recovery_sweep_converges_case_after_post_commit_worker_crash(monkeypatch):
 setup_auth();i=seed_order()
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:(_ for _ in ()).throw(httpx.TimeoutException('unknown')))
 pending=real.execute_payment(i['payment_intent_id'],'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'queue-recovery'})
 original=command_center.converge_payment_truth_from_callback
 monkeypatch.setattr(command_center,'converge_payment_truth_from_callback',lambda operation_id:(_ for _ in ()).throw(RuntimeError('simulated post-commit crash')))
 body={'state':'SUCCEEDED','operation':'AUTHORIZE','external_operation_id':'ext-recovery','amount_minor':12000,'currency':'CNY','occurred_at':datetime.now(timezone.utc).isoformat()}
 with pytest.raises(RuntimeError,match='post-commit crash'):
  real.payment_callback(pending['external_truth_operation_id'],'queue-recovery-callback',body,sig(body))
 with SessionLocal() as s:
  assert s.get(ExternalTruthOperationRow,pending['external_truth_operation_id']).state=='CALLBACK_SUCCEEDED'
  assert len(s.scalars(select(OmnichannelMoneyMovementRow).where(OmnichannelMoneyMovementRow.root_payment_intent_id==i['payment_intent_id'])).all())==1
 monkeypatch.setattr(command_center,'converge_payment_truth_from_callback',original)
 recovered=command_center.recover_verified_payment_truth_cases()
 assert any(x['reconciliation']['reconciliation_id']==pending['command_center_reconciliation']['reconciliation']['reconciliation_id'] for x in recovered)


def test_0100_checker_cannot_replace_verified_payment_truth(monkeypatch):
 setup_auth();i=seed_order()
 monkeypatch.setattr(real,'_post_json',lambda url,payload,headers:(_ for _ in ()).throw(httpx.TimeoutException('unknown')))
 pending=real.execute_payment(i['payment_intent_id'],'auth-0100',{'operation':'AUTHORIZE','idempotency_key':'queue-checker-guard'})
 case=pending['command_center_reconciliation']['reconciliation']
 command_center.claim(case['reconciliation_id'],'maker',60)
 command_center.submit_resolution(case['reconciliation_id'],'maker',{'terminal_state':'CONFIRMED','evidence':{'provider':'unverified'},'evidence_reference':'operator://claim'})
 with pytest.raises(ValueError,match='REQUIRES_VERIFIED_SIGNED_CALLBACK'):
  command_center.review_resolution(case['reconciliation_id'],'checker','APPROVE','checker://review')
