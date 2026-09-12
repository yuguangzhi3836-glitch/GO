from datetime import datetime,timezone,timedelta
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightOrderRow, PaymentOrderFactBindingRow
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service as source
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as pay
from go_hotel.services.unified_money_movement import unified_money_movement_service as money

def seed_flight(order_id='fo_0098',account='guest_0098',amount=10000):
    with SessionLocal() as s:
        r=FlightOrderRow(order_id=order_id,account_id=account,prebook_id='fpb_0098',status='PENDING_PAYMENT',total_amount_minor=amount,currency='CNY',passengers=[],payment_method_id=None,pnr=None,ticket_numbers=[],current_itinerary=[],created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc))
        s.add(r);s.commit()

def make_paid_intent():
    seed_flight()
    d=source.decide('FLIGHT','fo_0098',[{'source_id':'airline_official_1','source_type':'AIRLINE_OFFICIAL','authorized':True,'available':True,'evidence_reference':'evidence://airline/authority'}])
    i=pay.create_intent({'business_type':'FLIGHT_ORDER','business_id':'fo_0098','payee_id':'evil-client-payee','operation':'REFUND','amount_minor':1,'currency':'USD','channel_priority':['ALIPAY']},'idem_0098','guest_0098')
    assert i['amount_minor']==10000 and i['currency']=='CNY' and i['payee_id']=='airline_official_1' and i['operation']=='PAY'
    with SessionLocal() as s:
        b=s.query(PaymentOrderFactBindingRow).filter_by(payment_intent_id=i['payment_intent_id']).one()
        assert b.source_decision_id==d['vertical_source_decision_id']
    pay.select_channel(i['payment_intent_id'],'ALIPAY','guest_0098')
    a=pay.execute(i['payment_intent_id'])
    pay.simulate_result(a['payment_attempt_id'],'SUCCEEDED')
    return i

def test_0097_persists_direct_first_and_0098_server_resolves_payment_truth():
    i=make_paid_intent()
    with pytest.raises(ValueError,match='IDEMPOTENCY_KEY_REQUEST_FINGERPRINT_MISMATCH'):
        pay.create_intent({'business_type':'FLIGHT_ORDER','business_id':'fo_0098','channel_priority':['VISA']},'idem_0098','guest_0098')
    with pytest.raises(ValueError,match='PAYMENT_PAYER_ORDER_MISMATCH'):
        pay.create_intent({'business_type':'FLIGHT_ORDER','business_id':'fo_0098','channel_priority':['ALIPAY']},'idem_other','other_guest')

def test_0098_cumulative_money_guards_and_scoped_close_revalidation():
    i=make_paid_intent();iid=i['payment_intent_id']
    auth=money.create(iid,{'movement_type':'AUTHORIZATION','amount_minor':10000,'evidence':['e://auth'],'mode':'CONTRACT_SIMULATOR'},'m_auth','finance')
    cap=money.create(iid,{'movement_type':'CAPTURE','parent_movement_id':auth['money_movement_id'],'amount_minor':8000,'evidence':['e://cap'],'mode':'CONTRACT_SIMULATOR'},'m_cap','finance')
    with pytest.raises(ValueError,match='CUMULATIVE_CAPTURE_EXCEEDS_AUTHORIZATION'):
        money.create(iid,{'movement_type':'CAPTURE','parent_movement_id':auth['money_movement_id'],'amount_minor':3000,'evidence':['e://cap2'],'mode':'CONTRACT_SIMULATOR'},'m_cap2','finance')
    money.create(iid,{'movement_type':'REFUND','parent_movement_id':cap['money_movement_id'],'amount_minor':2000,'evidence':['e://refund'],'mode':'CONTRACT_SIMULATOR'},'m_ref','finance')
    # Finance close remains reconciliation fail-closed. Seed durable PSP + bank evidence
    # for the confirmed gross capture before asking the close engine to proceed.
    recon_at=datetime.now(timezone.utc).isoformat()
    pay.ingest_psp_line(iid,{'external_transaction_id':'psp-tx-0098','amount_minor':8000,'currency':'CNY','evidence_reference':'psp://0098/settlement','occurred_at':recon_at})
    pay.ingest_bank_line({'bank_line_identity':'bank-line-0098','legal_entity_id':'GO_CN','amount_minor':8000,'currency':'CNY','payment_reference':'psp-tx-0098','evidence_reference':'bank://0098/statement','booked_at':recon_at})
    assert pay.reconcile(iid,{'external_transaction_id':'psp-tx-0098'})['state']=='MATCHED'
    with pytest.raises(ValueError,match='CUMULATIVE_PAYOUT_EXCEEDS_NET_CAPTURE'):
        money.create(iid,{'movement_type':'PAYOUT','parent_movement_id':cap['money_movement_id'],'amount_minor':7000,'evidence':['e://payout'],'mode':'CONTRACT_SIMULATOR'},'m_pay','finance')
    today=datetime.now(timezone.utc).date().isoformat()
    cutoff=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
    close=money.prepare_close({'legal_entity_id':'GO_CN','currency':'CNY','period_start':today,'period_end':today,'cutoff_at':cutoff},'maker')
    assert close['state']=='PENDING_APPROVAL'
    money.create(iid,{'movement_type':'PAYOUT','parent_movement_id':cap['money_movement_id'],'amount_minor':1000,'evidence':['e://payout-ok'],'mode':'CONTRACT_SIMULATOR'},'m_pay_ok','finance')
    with pytest.raises(ValueError,match='FINANCE_CLOSE_SCOPE_CHANGED_REPREPARE_REQUIRED'):
        money.approve_close(close['finance_scoped_close_batch_id'],'checker')
