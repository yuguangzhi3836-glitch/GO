from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import SupplierLiabilityRow, CompensationPaymentRow, PaymentOrderRootRow, OmnichannelMoneyMovementRow
from go_hotel.payments.mock import payment_provider
from go_hotel.security.service import identity_service

def admin_headers():
    token=identity_service.login('go_admin','change-me-admin');return {'Authorization':'Bearer '+token['access_token']}
def supplier_headers(extra=None):
    token=identity_service.login('supplier_owner','change-me-supplier');return {'Authorization':'Bearer '+token['access_token']}|(extra or {})


def booked_order(client, idem='n', account_id='acct_demo'):
    ci=(datetime.now(timezone.utc)+timedelta(days=20)).date().isoformat(); co=(datetime.now(timezone.utc)+timedelta(days=24)).date().isoformat()
    s=client.post('/v1/search/hotels',json={'destination':{'city_code':'TYO'},'stay':{'check_in':ci,'check_out':co},'occupancy':{'rooms':1,'adults':2,'children':0},'currency':'CNY'})
    off=s.json()['data']['hotels'][0]['best_offer']
    pb=client.post(f"/v1/offers/{off['offer_id']}/prebook",json={'currency':'CNY'}).json()['data']
    o=client.post('/v1/orders',headers={'Idempotency-Key':f'ord-{idem}'},json={'prebook_id':pb['prebook_id'],'account_id':account_id}).json()['data']
    client.post(f"/v1/orders/{o['order_id']}/payments",headers={'Idempotency-Key':f'pay-{idem}'},json={'payment_method_token':'pm_success','amount_minor':o['total_amount_minor'],'currency':'CNY'})
    c=client.post(f"/internal/v1/orders/{o['order_id']}/confirm")
    assert c.status_code==200 and c.json()['data']['status']=='CONFIRMED'
    return o['order_id'], o['total_amount_minor']


def finish_independently_reviewed_fault(client,response):
    """The original money assertions now require V7's separate evidence/checker steps."""
    assert response.status_code==200,response.text
    requested=response.json()['data'];assert requested['state']=='EVIDENCE_REQUIRED' and not requested['financial_decision_approved']
    oid=requested['order_id'];supplier=requested['supplier_id'];cid=requested['case_id'];admin=admin_headers()
    from go_hotel.compensation.service import compensation_service
    from go_hotel.services import catalog_fault_funding as funding
    with SessionLocal() as s:
        from go_hotel.db.models import OrderRow,SupplierFinancialAccountRow
        amount=s.get(OrderRow,oid).total_amount_minor;acct=s.get(SupplierFinancialAccountRow,supplier)
        active=bool(acct and acct.debit_mandate_active)
    compensation_service.configure_supplier_finance(funding.PROTECTION_ACCOUNT,0,amount,0,False)
    if active:
        funding.register_mandate(supplier,'CNY',amount,(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),'test://signed-'+oid,'b'*64,'test-finance')
    base='/internal/v1/supplier-fault-cases/'+cid
    proof=client.post(base+'/evidence',headers=admin,json={'reference':'test://verified-'+oid,'sha256':'a'*64,'type':'HOTEL_RECORD'})
    assert proof.status_code==200,proof.text
    c=proof.json()['data']
    review=client.post(base+'/review',headers=admin,json={'confirmed_cause':requested['reason_code'],'accepted_evidence_ids':c['evidence_ids'],'decision_reference':'test://independent-'+oid,'expected_evidence_hash':c['evidence_hash']})
    assert review.status_code==200,review.text
    result=client.post(base+'/execute',headers=admin,json={'expected_decision_hash':review.json()['data']['decision_hash']})
    assert result.status_code==200,result.text
    return result


def test_supplier_fault_double_compensation_with_bank_debit(client):
    oid,paid=booked_order(client,'bank')
    supplier='sup_mock'
    client.put(f'/internal/v1/suppliers/{supplier}/financial-account',headers=admin_headers(),json={'settlement_available_minor':200_000,'reserve_available_minor':100_000,'bank_available_minor':2_000_000,'debit_mandate_active':True})
    r=finish_independently_reviewed_fault(client,client.post(f'/v1/supplier/orders/{oid}/unable-to-fulfill',headers=supplier_headers({'Idempotency-Key':'sf-bank'}),json={'reason_code':'OVERBOOKING','evidence_ids':['evd_overbooking']}))
    assert r.status_code==200
    d=r.json()['data']
    assert d['fault_party']=='SUPPLIER' and d['double_compensation'] is True
    assert d['refund']['amount_minor']==paid
    assert d['compensation']['amount_minor']==paid
    assert d['total_return_minor']==paid*2
    li=d['liability']
    assert li['settlement_offset_minor']==200_000
    assert li['reserve_offset_minor']==100_000
    assert li['bank_debit_minor']==paid-300_000
    assert li['protection_fund_minor']==0 and li['negative_balance_minor']==0
    assert li['status']=='CLEARED'
    assert payment_provider.refund_calls==0
    with SessionLocal() as s:
        root=s.scalar(select(PaymentOrderRootRow).where(PaymentOrderRootRow.business_type=='HOTEL_ORDER',PaymentOrderRootRow.business_id==oid))
        refunds=s.scalars(select(OmnichannelMoneyMovementRow).where(OmnichannelMoneyMovementRow.root_payment_intent_id==root.payment_intent_id,OmnichannelMoneyMovementRow.movement_type=='REFUND',OmnichannelMoneyMovementRow.state=='CONFIRMED')).all()
        assert len(refunds)==1


def test_supplier_fault_insufficient_funds_uses_protection_fund_and_negative_balance(client):
    oid,paid=booked_order(client,'fund')
    supplier='sup_mock'
    client.put(f'/internal/v1/suppliers/{supplier}/financial-account',headers=admin_headers(),json={'settlement_available_minor':0,'reserve_available_minor':0,'bank_available_minor':100_000,'debit_mandate_active':True})
    d=finish_independently_reviewed_fault(client,client.post(f'/v1/supplier/orders/{oid}/unable-to-fulfill',headers=supplier_headers(),json={'reason_code':'NO_ROOM','evidence_ids':['evd_no_room']})).json()['data']
    li=d['liability']
    assert li['bank_debit_minor']==100_000
    assert li['protection_fund_minor']==paid-100_000
    assert li['negative_balance_minor']==paid-100_000
    assert li['status']=='NEGATIVE_BALANCE'
    acct=client.get(f'/internal/v1/suppliers/{supplier}/financial-account',headers=admin_headers()).json()['data']
    assert acct['negative_balance_minor']==paid-100_000


def test_no_mandate_never_debits_bank(client):
    oid,paid=booked_order(client,'nomandate')
    supplier='sup_mock'
    client.put(f'/internal/v1/suppliers/{supplier}/financial-account',headers=admin_headers(),json={'bank_available_minor':paid,'debit_mandate_active':False})
    d=finish_independently_reviewed_fault(client,client.post(f'/v1/supplier/orders/{oid}/unable-to-fulfill',headers=supplier_headers(),json={'reason_code':'HOTEL_OPERATIONAL_ERROR','evidence_ids':['evd_ops']})).json()['data']
    assert d['liability']['bank_debit_minor']==0
    assert d['liability']['protection_fund_minor']==paid


def test_external_cause_full_refund_no_double_compensation(client):
    oid,paid=booked_order(client,'external')
    d=finish_independently_reviewed_fault(client,client.post(f'/v1/supplier/orders/{oid}/unable-to-fulfill',headers=supplier_headers(),json={'reason_code':'NATURAL_DISASTER','evidence_ids':['evd_weather']})).json()['data']
    assert d['fault_party']=='EXTERNAL'
    assert d['double_compensation'] is False
    assert d['refund']['amount_minor']==paid
    with SessionLocal() as s:
        assert s.scalar(select(SupplierLiabilityRow).where(SupplierLiabilityRow.order_id==oid)) is None


def test_unknown_reason_requires_evidence_and_does_not_cancel(client):
    oid,_=booked_order(client,'unknown')
    d=client.post(f'/v1/supplier/orders/{oid}/unable-to-fulfill',headers=supplier_headers(),json={'reason_code':'OTHER','evidence_ids':[]}).json()['data']
    assert d['status']=='EVIDENCE_REQUIRED'
    assert d['fault_party']=='UNRESOLVED'


def test_idempotent_supplier_cancel_does_not_double_refund_or_compensate(client):
    oid,paid=booked_order(client,'idem')
    supplier='sup_mock'
    client.put(f'/internal/v1/suppliers/{supplier}/financial-account',headers=admin_headers(),json={'bank_available_minor':paid,'debit_mandate_active':True})
    body={'reason_code':'OVERBOOKING','evidence_ids':['evd']}
    a=client.post(f'/v1/supplier/orders/{oid}/unable-to-fulfill',headers=supplier_headers({'Idempotency-Key':'same'}),json=body)
    b=client.post(f'/v1/supplier/orders/{oid}/unable-to-fulfill',headers=supplier_headers({'Idempotency-Key':'same'}),json=body)
    assert a.json()==b.json()
    finish_independently_reviewed_fault(client,a)
    assert payment_provider.refund_calls==0
    with SessionLocal() as s:
        root=s.scalar(select(PaymentOrderRootRow).where(PaymentOrderRootRow.business_type=='HOTEL_ORDER',PaymentOrderRootRow.business_id==oid))
        refunds=s.scalars(select(OmnichannelMoneyMovementRow).where(OmnichannelMoneyMovementRow.root_payment_intent_id==root.payment_intent_id,OmnichannelMoneyMovementRow.movement_type=='REFUND',OmnichannelMoneyMovementRow.state=='CONFIRMED')).all()
        assert len(refunds)==1
    with SessionLocal() as s:
        assert len(s.scalars(select(CompensationPaymentRow).where(CompensationPaymentRow.order_id==oid)).all())==1


def test_future_settlement_recovers_protection_fund_before_supplier_payout(client):
    oid,paid=booked_order(client,'recovery')
    supplier='sup_mock'
    client.put(f'/internal/v1/suppliers/{supplier}/financial-account',headers=admin_headers(),json={'bank_available_minor':0,'debit_mandate_active':True})
    d=finish_independently_reviewed_fault(client,client.post(f'/v1/supplier/orders/{oid}/unable-to-fulfill',headers=supplier_headers(),json={'reason_code':'OVERBOOKING','evidence_ids':['evd']})).json()['data']
    assert d['liability']['negative_balance_minor']==paid
    r=client.post(f'/internal/v1/suppliers/{supplier}/future-settlement',headers=admin_headers()|{'Idempotency-Key':'verified-settlement'},json={'amount_minor':paid+50_000,'settlement_reference':'test://verified-settlement'}).json()['data']
    assert r['recovered_minor']==paid
    assert r['negative_balance_minor']==0
    assert r['remaining_available_minor']==50_000
    li=client.get(f"/internal/v1/supplier-liabilities/{d['liability']['liability_id']}",headers=admin_headers()).json()['data']
    assert li['negative_balance_minor']==0 and li['status']=='CLEARED'
