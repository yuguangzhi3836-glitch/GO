import os
from pathlib import Path
DB=Path('/tmp/go0099_verify.db')
if DB.exists(): DB.unlink()
os.environ['DATABASE_URL']=f'sqlite+pysqlite:///{DB}'
from datetime import datetime,timezone,timedelta
from sqlalchemy import select
from go_hotel.db.models import Base,FlightOrderRow,OmnichannelLedgerEntryRow,OrderSupplierFulfillmentRow,ConsumerUnifiedLifecycleRow
from go_hotel.db.session import engine,SessionLocal
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service as source
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as pay
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as fulfill
Base.metadata.create_all(engine)

def seed(order_id,account='guest99',amount=10000,currency='CNY'):
    with SessionLocal() as s:
        s.add(FlightOrderRow(order_id=order_id,account_id=account,prebook_id='p-'+order_id,status='PENDING_PAYMENT',total_amount_minor=amount,currency=currency,passengers=[],payment_method_id=None,pnr=None,ticket_numbers=[],current_itinerary=[],created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc)));s.commit()
    source.decide('FLIGHT',order_id,[{'source_id':'airline99','source_type':'AIRLINE_OFFICIAL','authorized':True,'available':True,'evidence_reference':'evidence://airline99'}])

def intent(order_id,currency='CNY'):
    seed(order_id,currency=currency)
    return pay.create_intent({'business_type':'FLIGHT_ORDER','business_id':order_id,'channel_priority':['ALIPAY']},'idem-'+order_id,'guest99')

def paid(order_id,currency='CNY'):
    i=intent(order_id,currency);pay.select_channel(i['payment_intent_id'],'ALIPAY','guest99');a=pay.execute(i['payment_intent_id']);pay.simulate_result(a['payment_attempt_id'],'SUCCEEDED');return i

def capture(i):
    iid=i['payment_intent_id'];a=money.create(iid,{'movement_type':'AUTHORIZATION','amount_minor':i['amount_minor'],'evidence':['e://auth'],'mode':'CONTRACT_SIMULATOR'},'auth-'+iid,'finance');money.create(iid,{'movement_type':'CAPTURE','parent_movement_id':a['money_movement_id'],'amount_minor':i['amount_minor'],'evidence':['e://cap'],'mode':'CONTRACT_SIMULATOR'},'cap-'+iid,'finance')

# 1 single order root
one=intent('root-one')
try:
    pay.create_intent({'business_type':'FLIGHT_ORDER','business_id':'root-one','channel_priority':['VISA']},'second-root','guest99')
    raise AssertionError('second payment root was allowed')
except ValueError as e:
    assert 'ORDER_PAYMENT_ROOT_ALREADY_EXISTS' in str(e)

# 2 auth is non-GL; reconciliation requires PSP + bank + capture ledger
p=paid('recon-one');capture(p);iid=p['payment_intent_id']
with SessionLocal() as s:
    assert s.scalar(select(OmnichannelLedgerEntryRow).where(OmnichannelLedgerEntryRow.payment_intent_id==iid,OmnichannelLedgerEntryRow.entry_type=='AUTHORIZATION')) is None
    assert len(s.scalars(select(OmnichannelLedgerEntryRow).where(OmnichannelLedgerEntryRow.payment_intent_id==iid,OmnichannelLedgerEntryRow.entry_type=='CAPTURE')).all())==2
assert pay.reconcile(iid,{'external_transaction_id':'tx99'})['state']=='PENDING_EXTERNAL_FACT'
t=datetime.now(timezone.utc).isoformat()
pay.ingest_psp_line(iid,{'external_transaction_id':'tx99','amount_minor':10000,'currency':'CNY','evidence_reference':'psp://99','occurred_at':t})
pay.ingest_bank_line({'bank_line_identity':'bank99','legal_entity_id':'GO_CN','amount_minor':10000,'currency':'CNY','payment_reference':'tx99','evidence_reference':'bank://99','booked_at':t})
assert pay.reconcile(iid,{'external_transaction_id':'tx99'})['state']=='MATCHED'

# 3 real legal entity/currency/period close scope; missing reconciliation blocks captured money
usd=paid('usd-one','USD');capture(usd)
cutoff=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat();today=datetime.now(timezone.utc).date().isoformat()
c=money.prepare_close({'legal_entity_id':'GO_CN','currency':'CNY','period_start':today,'period_end':today,'cutoff_at':cutoff},'maker')
assert c['movement_count']==2 and c['debit_minor']==10000 and c['credit_minor']==10000 and c['state']=='PENDING_APPROVAL',c

# 4 supplier cannot confirm before full captured money graph; confirmation projects order + Trips atomically
fpay=paid('fulfill-one')
with SessionLocal() as s:
    f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.payment_intent_id==fpay['payment_intent_id']));fid=f.order_supplier_fulfillment_id;assert f.state=='PAYMENT_CONFIRMED_AWAITING_MONEY_GRAPH'
try:
    fulfill.record_supplier_fact(fid,{'state':'SUPPLIER_CONFIRMED','supplier_confirmation_reference':'EARLY','evidence_reference':'supplier://early'})
    raise AssertionError('supplier confirmation accepted before capture')
except ValueError as e:
    assert 'FULL_CAPTURED_MONEY_GRAPH_REQUIRED' in str(e)
capture(fpay)
res=fulfill.record_supplier_fact(fid,{'state':'SUPPLIER_CONFIRMED','external_operation_id':'op99','supplier_confirmation_reference':'PNR99','evidence_reference':'supplier://99'})
assert res['unified_lifecycle']['lifecycle_state']=='CONFIRMED'
with SessionLocal() as s:
    assert s.get(FlightOrderRow,'fulfill-one').status=='CONFIRMED'
    life=s.scalar(select(ConsumerUnifiedLifecycleRow).where(ConsumerUnifiedLifecycleRow.vertical=='FLIGHT',ConsumerUnifiedLifecycleRow.order_id=='fulfill-one'));assert life and life.payment_state=='PAID'
print('P0_0099_ASSERTIONS_PASS=4')
