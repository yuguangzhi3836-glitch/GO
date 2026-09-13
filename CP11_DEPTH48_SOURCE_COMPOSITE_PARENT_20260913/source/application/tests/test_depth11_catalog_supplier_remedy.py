import asyncio
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (OrderRow,PaymentRow,PaymentOrderRootRow as Root,OmnichannelPaymentIntentRow as Intent,
    OmnichannelMoneyMovementRow as Movement,OmnichannelLedgerEntryRow as Ledger,CatalogSupplierRemedyRow as Plan,
    SupplierFaultCaseRow as Case,SupplierFinancialAccountRow as Account,CompensationPaymentRow as Compensation)
from go_hotel.services import catalog_supplier_remedy as remedy,catalog_fault_funding as funding
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.services.hotel_money_bridge import hotel_money_bridge as bridge
from go_hotel.compensation.service import compensation_service as finance
from go_hotel.connectors.mock_hotel import connector
from tests.test_sprint1n_supplier_compensation import booked_order,admin_headers,supplier_headers

EVIDENCE={'reference':'test://independent-stock-file','sha256':'a'*64,'type':'HOTEL_RECORD'}


def approved(oid,reason='OVERBOOKING'):
    c=remedy.request(oid,'sup_mock',reason,['unverified-reference'],'maker')
    c=remedy.add_evidence(c['case_id'],EVIDENCE,'maker')
    return remedy.review(c['case_id'],reason,c['evidence_ids'],'test://independent-decision','checker',c['evidence_hash'])


def configure(supplier,settlement=0,reserve=0,bank=0,active=False):return finance.configure_supplier_finance(supplier,settlement,reserve,bank,active)


def mandate(supplier='sup_mock',maximum=2000000):
    return funding.register_mandate(supplier,'CNY',maximum,(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),'test://scoped-signed-bank','b'*64,'finance')


def run(c):return asyncio.run(remedy.execute(c['case_id'],c['decision_hash']))


def movements(oid,kind):
    with SessionLocal() as s:
        root=s.scalar(select(Root).where(Root.business_type=='HOTEL_ORDER',Root.business_id==oid))
        return s.scalars(select(Movement).where(Movement.root_payment_intent_id==root.payment_intent_id,Movement.movement_type==kind)).all()


def test_request_keeps_order_and_funds_and_cannot_self_approve(client):
    oid,paid=booked_order(client,'independent')
    c=remedy.request(oid,'sup_mock','OVERBOOKING',['unverified-reference'],'maker')
    assert c['state']=='EVIDENCE_REQUIRED' and not c['financial_decision_approved'] and connector.cancel_calls==0
    assert remedy.request(oid,'sup_mock','OVERBOOKING',['unverified-reference'],'maker')==c
    with pytest.raises(ValueError,match='SUPPLIER_ORDER_NOT_FOUND'):remedy.request(oid,'wrong-supplier','NO_ROOM',[],'someone')
    with pytest.raises(ValueError,match='NOT_AWAITING_REVIEW'):remedy.review(c['case_id'],'OVERBOOKING',[],'test://r','checker',c['evidence_hash'])
    c=remedy.add_evidence(c['case_id'],EVIDENCE,'maker')
    with pytest.raises(ValueError,match='MAKER_CHECKER'):remedy.review(c['case_id'],'OVERBOOKING',c['evidence_ids'],'test://r','maker',c['evidence_hash'])
    with SessionLocal() as s:assert s.get(OrderRow,oid).status=='CONFIRMED' and not s.scalars(select(Compensation)).all()
    assert not movements(oid,'REFUND')


def test_actual_paid_instead_of_current_order_total_and_scoped_bank_priority(client):
    oid,paid=booked_order(client,'cash-base')
    with SessionLocal.begin() as s:s.get(OrderRow,oid).total_amount_minor=paid+999999
    c=approved(oid);assert c['actual_paid_minor']==paid
    configure('sup_mock',200000,100000,2000000,True);mandate()
    d=run(c);assert d['state']=='COMPLETED' and d['refund']['amount_minor']==d['compensation']['amount_minor']==paid
    assert d['liability']['bank_debit_minor']==paid-300000 and d['total_return_minor']==paid*2
    with SessionLocal() as s:
        assert len(s.scalars(select(Ledger)).all())==6
        intent=s.get(Intent,s.get(Plan,c['case_id']).compensation_intent_id)
        assert intent.payer_id=='sup_mock' and intent.payee_id=='acct_demo'
    assert connector.cancel_calls==1 and run(c)['state']=='COMPLETED' and connector.cancel_calls==1


def test_no_mandate_and_finite_fund_shortage_do_not_claim_paid(client):
    oid,paid=booked_order(client,'shortage');c=approved(oid)
    configure('sup_mock',200000,0,paid,True);configure(funding.PROTECTION_ACCOUNT,0,1000)
    d=run(c);assert d['state']=='COMPENSATION_PENDING' and d['refund']['status']=='COMPLETED'
    with SessionLocal() as s:
        assert s.get(Account,'sup_mock').settlement_available_minor==200000 and s.get(Account,'sup_mock').bank_available_minor==paid
        assert s.get(Account,funding.PROTECTION_ACCOUNT).reserve_available_minor==1000
        assert not s.scalars(select(Compensation)).all()
    mandate();assert run(c)['state']=='COMPLETED' and len(movements(oid,'REFUND'))==1


def test_exact_protection_liability_and_durable_idempotent_recovery(client):
    oid,paid=booked_order(client,'recovery');c=approved(oid)
    configure('sup_mock',100000);configure(funding.PROTECTION_ACCOUNT,0,paid)
    d=run(c);assert d['liability']['negative_balance_minor']==paid-100000
    first=funding.recover('sup_mock',paid,'test://settlement-one','receipt-one','finance')
    assert first['new_available_minor']==100000 and first['negative_balance_minor']==0
    assert funding.recover('sup_mock',paid,'test://settlement-one','other-key','finance')==first
    with SessionLocal() as s:assert s.get(Account,funding.PROTECTION_ACCOUNT).reserve_available_minor==paid


def test_prior_original_refund_is_not_repeated_but_compensation_uses_actual_gross_paid(client):
    oid,paid=booked_order(client,'partial')
    bridge.refund(oid,10000,'test://prior-partial','prior-partial')
    c=approved(oid);assert c['actual_paid_minor']==paid and c['refund_due_minor']==paid-10000
    configure('sup_mock',paid);run(c)
    assert sum(m.amount_minor for m in movements(oid,'REFUND'))==paid


def test_approved_remedy_prevents_unrelated_refund_or_change_spending_reserved_funds(client):
    oid,paid=booked_order(client,'reserved');c=approved(oid)
    with pytest.raises(ValueError,match='FUNDS_RESERVED'):bridge.refund(oid,1000,'test://unrelated-refund','unrelated')
    with pytest.raises(ValueError,match='ORDER_FROZEN'):bridge.prepare_adjustment(oid,'HOTEL_CHANGE','other-quote',1000,'test://change','other-change')
    configure('sup_mock',paid);assert run(c)['state']=='COMPLETED'


def test_supplier_timeout_queries_status_without_resending_or_refunding_early(client,monkeypatch):
    oid,paid=booked_order(client,'unknown');c=approved(oid);configure('sup_mock',paid);original=connector.cancel
    async def lost(confirmation):
        await original(confirmation);raise TimeoutError('reply lost')
    monkeypatch.setattr(connector,'cancel',lost)
    result=run(c);assert result['state']=='UNKNOWN_SUPPLIER_CANCEL' and not movements(oid,'REFUND') and connector.cancel_calls==1
    assert run(c)['state']=='UNKNOWN_SUPPLIER_CANCEL' and connector.cancel_calls==1
    rec=asyncio.run(remedy.reconcile(c['case_id'],'finance'));assert rec['state']=='CANCELLED_REFUND_PENDING'
    assert run(c)['state']=='COMPLETED' and connector.cancel_calls==1


def test_refund_fault_rolls_back_all_money_and_resumes_after_confirmed_cancel(client,monkeypatch):
    oid,paid=booked_order(client,'refund-fault');c=approved(oid);configure('sup_mock',paid);post=money._post
    def fail(s,i,m):
        post(s,i,m)
        if m.movement_type=='REFUND':raise RuntimeError('ledger interrupted')
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError):run(c)
    assert remedy.status(c['case_id'])['state']=='CANCELLED_REFUND_PENDING' and not movements(oid,'REFUND')
    monkeypatch.setattr(money,'_post',post);assert run(c)['state']=='COMPLETED' and connector.cancel_calls==1


def test_compensation_fault_cannot_repeat_completed_refund(client,monkeypatch):
    oid,paid=booked_order(client,'comp-fault');c=approved(oid);configure('sup_mock',paid);post=money._post
    def fail(s,i,m):
        post(s,i,m)
        if i.business_type=='HOTEL_COMP':raise RuntimeError('compensation interrupted')
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError):run(c)
    assert remedy.status(c['case_id'])['state']=='COMPENSATION_PENDING' and len(movements(oid,'REFUND'))==1
    with SessionLocal() as s:assert s.get(Account,'sup_mock').settlement_available_minor==paid and not s.scalars(select(Compensation)).all()
    monkeypatch.setattr(money,'_post',post);run(c);assert len(movements(oid,'REFUND'))==1 and connector.cancel_calls==1


def test_four_concurrent_executions_produce_one_supplier_cancel_refund_and_compensation(client):
    oid,paid=booked_order(client,'concurrent');c=approved(oid);configure('sup_mock',paid)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:run(c),range(4)))
    assert all(x['state'] in {'SUPPLIER_CANCEL_PENDING','CANCELLED_REFUND_PENDING','COMPENSATION_PENDING','COMPLETED'} for x in results)
    assert run(c)['state']=='COMPLETED' and connector.cancel_calls==1 and len(movements(oid,'REFUND'))==1
    with SessionLocal() as s:assert len(s.scalars(select(Compensation)).all())==1


def test_external_fault_refunds_without_extra_supplier_debit(client):
    oid,paid=booked_order(client,'external-independent');c=approved(oid,'FORCE_MAJEURE');configure('sup_mock',paid)
    d=run(c);assert not d['double_compensation'] and d['refund']['amount_minor']==paid and d['compensation'] is None
    with SessionLocal() as s:assert s.get(Account,'sup_mock').settlement_available_minor==paid
