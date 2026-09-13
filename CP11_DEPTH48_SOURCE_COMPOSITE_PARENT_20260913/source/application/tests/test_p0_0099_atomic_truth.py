from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightOrderRow,OmnichannelLedgerEntryRow,OrderSupplierFulfillmentRow,ConsumerUnifiedLifecycleRow
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service as source
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as pay
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as fulfill

def seed(order_id='fo99',account='guest99',amount=10000,currency='CNY'):
    with SessionLocal() as s:
        s.add(FlightOrderRow(order_id=order_id,account_id=account,prebook_id='fpb99'+order_id,status='PENDING_PAYMENT',total_amount_minor=amount,currency=currency,passengers=[],payment_method_id=None,pnr=None,ticket_numbers=[],current_itinerary=[],created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc)));s.commit()
    source.decide('FLIGHT',order_id,[{'source_id':'airline99','source_type':'AIRLINE_OFFICIAL','authorized':True,'available':True,'evidence_reference':'evidence://airline99'}])

def paid(order_id='fo99',currency='CNY'):
    seed(order_id=order_id,currency=currency)
    i=pay.create_intent({'business_type':'FLIGHT_ORDER','business_id':order_id,'channel_priority':['ALIPAY']},'idem-'+order_id,'guest99')
    pay.select_channel(i['payment_intent_id'],'ALIPAY','guest99');a=pay.execute(i['payment_intent_id']);pay.simulate_result(a['payment_attempt_id'],'SUCCEEDED');return i

def capture(i,amount=10000):
    iid=i['payment_intent_id'];a=money.create(iid,{'movement_type':'AUTHORIZATION','amount_minor':amount,'evidence':['e://auth'],'mode':'CONTRACT_SIMULATOR'},'auth-'+iid,'finance')
    c=money.create(iid,{'movement_type':'CAPTURE','parent_movement_id':a['money_movement_id'],'amount_minor':amount,'evidence':['e://cap'],'mode':'CONTRACT_SIMULATOR'},'cap-'+iid,'finance');return a,c

def test_order_has_single_payment_root_even_with_different_idempotency_and_channel_request():
    seed()
    first=pay.create_intent({'business_type':'FLIGHT_ORDER','business_id':'fo99','channel_priority':['ALIPAY']},'first-key','guest99')
    with pytest.raises(ValueError,match='ORDER_PAYMENT_ROOT_ALREADY_EXISTS'):
        pay.create_intent({'business_type':'FLIGHT_ORDER','business_id':'fo99','channel_priority':['VISA']},'second-key','guest99')
    assert first['business_id']=='fo99'

def test_authorization_does_not_post_gl_capture_does_and_reconciliation_requires_durable_external_lines():
    i=paid();iid=i['payment_intent_id'];auth,cap=capture(i)
    with SessionLocal() as s:
        assert s.scalar(select(OmnichannelLedgerEntryRow).where(OmnichannelLedgerEntryRow.payment_intent_id==iid,OmnichannelLedgerEntryRow.entry_type=='AUTHORIZATION')) is None
        assert len(s.scalars(select(OmnichannelLedgerEntryRow).where(OmnichannelLedgerEntryRow.payment_intent_id==iid,OmnichannelLedgerEntryRow.entry_type=='CAPTURE')).all())==2
    assert pay.reconcile(iid,{'external_transaction_id':'psp-tx-99'})['state']=='PENDING_EXTERNAL_FACT'
    t=datetime.now(timezone.utc).isoformat()
    pay.ingest_psp_line(iid,{'external_transaction_id':'psp-tx-99','amount_minor':10000,'currency':'CNY','evidence_reference':'psp://line/99','occurred_at':t})
    assert pay.reconcile(iid,{'external_transaction_id':'psp-tx-99'})['state']=='PENDING_EXTERNAL_FACT'
    pay.ingest_bank_line({'bank_line_identity':'bank-line-99','legal_entity_id':'GO_CN','amount_minor':10000,'currency':'CNY','payment_reference':'psp-tx-99','evidence_reference':'bank://statement/99','booked_at':t})
    r=pay.reconcile(iid,{'external_transaction_id':'psp-tx-99'});assert r['state']=='MATCHED' and r['ledger_amount_minor']==10000

def test_close_scope_uses_legal_entity_currency_and_period():
    i=paid('fo99-cn');capture(i)
    t=datetime.now(timezone.utc).isoformat();iid=i['payment_intent_id']
    pay.ingest_psp_line(iid,{'external_transaction_id':'psp-cn-close','amount_minor':10000,'currency':'CNY','evidence_reference':'psp://cn-close','occurred_at':t})
    pay.ingest_bank_line({'bank_line_identity':'bank-cn-close','legal_entity_id':'GO_CN','amount_minor':10000,'currency':'CNY','payment_reference':'psp-cn-close','evidence_reference':'bank://cn-close','booked_at':t});pay.reconcile(iid,{'external_transaction_id':'psp-cn-close'})
    # A different legal entity/currency must not enter GO_CN/CNY close.
    j=paid('fo99-usd','USD');capture(j)
    cutoff=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
    c=money.prepare_close({'legal_entity_id':'GO_CN','currency':'CNY','period_start':datetime.now(timezone.utc).date().isoformat(),'period_end':datetime.now(timezone.utc).date().isoformat(),'cutoff_at':cutoff},'maker')
    assert c['movement_count']==2 and c['debit_minor']==10000 and c['credit_minor']==10000

def test_payment_success_creates_supplier_fulfillment_and_only_supplier_confirmation_confirms_order_and_trips():
    i=paid('fo99-fulfill')
    with SessionLocal() as s:
        f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.payment_intent_id==i['payment_intent_id']))
        assert f and f.state=='PAYMENT_CONFIRMED_AWAITING_MONEY_GRAPH'
        fid=f.order_supplier_fulfillment_id
        order=s.get(FlightOrderRow,'fo99-fulfill');assert order.status=='PENDING_PAYMENT'
        assert s.scalar(select(ConsumerUnifiedLifecycleRow).where(ConsumerUnifiedLifecycleRow.vertical=='FLIGHT',ConsumerUnifiedLifecycleRow.order_id=='fo99-fulfill')) is None
    with pytest.raises(ValueError,match='FULL_CAPTURED_MONEY_GRAPH_REQUIRED'):
        fulfill.record_supplier_fact(fid,{'state':'SUPPLIER_CONFIRMED','external_operation_id':'too-early','supplier_confirmation_reference':'PNR-EARLY','evidence_reference':'supplier://early'})
    capture(i)
    res=fulfill.record_supplier_fact(fid,{'state':'SUPPLIER_CONFIRMED','external_operation_id':'air-op-99','supplier_confirmation_reference':'PNR99','evidence_reference':'supplier://confirmation/99'})
    assert res['unified_lifecycle']['lifecycle_state']=='CONFIRMED'
    with SessionLocal() as s:
        assert s.get(FlightOrderRow,'fo99-fulfill').status=='TICKETED'
        life=s.scalar(select(ConsumerUnifiedLifecycleRow).where(ConsumerUnifiedLifecycleRow.vertical=='FLIGHT',ConsumerUnifiedLifecycleRow.order_id=='fo99-fulfill'));assert life and life.payment_state=='PAID'
