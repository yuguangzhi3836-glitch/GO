"""Independent supplier fault and separately funded compensation in isolation."""
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (HostedSupplierDisruptionRow as Disruption,SupplierFinancialAccountRow as Account,
    SupplierLiabilityRow as Liability,CompensationPaymentRow as Compensation,OmnichannelPaymentIntentRow as Intent,
    HostedFaultDebitMandateRow as Mandate,HostedDirectRoomOfferRow as Offer)
from go_hotel.services import hosted_supplier_disruption as fault,hosted_fault_funding as funding
from go_hotel.compensation.service import compensation_service as legacy_finance
from tests.test_depth09_stay_credit import booked,issued,redemption,redeem,summary,inventory,Credit,value,Reservation,Ledger,Authorization
from tests.test_depth07_hosted_money import funds,money

EVIDENCE={'type':'HOTEL_RECORD','reference':'isolated-evidence://stock-log','sha256':'a'*64}


def start(r,account,cause='OVERBOOKING',evidence=None):
    with SessionLocal() as s:hotel=s.get(Offer,r['hosted_offer_id']).hosted_hotel_id
    request=fault.request(r['hosted_reservation_id'],hotel,cause,[EVIDENCE] if evidence is None else evidence,'hotel-maker','fault-request')
    return hotel,request


def approved(r,account,cause='OVERBOOKING'):
    hotel,c=start(r,account,cause)
    reviewed=fault.review(c['case_id'],cause,c['evidence_ids'],'isolated-review://independent-fault','go-checker')
    return hotel,reviewed


def credited(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c,100000);new=redeem(r,account,c,q)
    with SessionLocal() as s:row=s.get(Reservation,new['reservation_id']);newr={x:getattr(row,x) for x in ['hosted_reservation_id','hosted_offer_id','check_in','check_out','amount_minor','currency']}
    return r,newr,account,c


def test_request_does_not_cancel_and_needs_evidence_independent_checker_and_ownership(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch);hotel,c=start(r,account,evidence=[])
    assert c['state']=='EVIDENCE_REQUIRED' and inventory(r)==[('HELD',7),('HELD',7)] and summary(r)['held_minor']==162000
    with pytest.raises(ValueError,match='SUPPLIER_RESERVATION_NOT_FOUND'):fault.request(r['hosted_reservation_id'],'other-hotel','OVERBOOKING',[EVIDENCE],'other','key')
    with pytest.raises(ValueError,match='AWAITING_REVIEW'):fault.review(c['case_id'],'OVERBOOKING',[],'test://review','checker')
    c=fault.add_evidence(c['case_id'],EVIDENCE,'hotel-maker')
    assert fault.add_evidence(c['case_id'],EVIDENCE,'hotel-maker')['evidence_ids']==c['evidence_ids']
    with pytest.raises(ValueError,match='MAKER_CHECKER'):fault.review(c['case_id'],'OVERBOOKING',c['evidence_ids'],'test://review','hotel-maker')
    with pytest.raises(ValueError,match='ACCEPTED.*EVIDENCE'):fault.review(c['case_id'],'OVERBOOKING',['foreign-evidence'],'test://review','checker')
    assert fault.status(c['case_id'],account)['state']=='INDEPENDENT_REVIEW_REQUIRED'
    with pytest.raises(ValueError,match='NOT_FOUND'):fault.status(c['case_id'],'other-account')


def test_uncaptured_authorization_is_released_and_never_used_as_double_compensation_basis(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch);hotel,c=approved(r,account)
    assert c['actual_paid_minor']==c['refund_due_minor']==c['compensation_due_minor']==0
    result=fault.execute(c['case_id']);assert result['state']=='COMPLETED' and result['compensation_state']=='NOT_REQUIRED'
    assert fault.execute(c['case_id'])==result
    x=summary(r);assert x['release_minor']==162000 and x['capture_minor']==x['refund_minor']==0
    with SessionLocal() as s:assert not s.scalars(select(Ledger)).all() and not s.scalars(select(Compensation)).all()
    assert inventory(r)==[('RELEASED',8),('RELEASED',8)]


def test_credit_refund_and_compensation_use_distinct_original_and_hotel_roots(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    assert c['actual_paid_minor']==c['refund_due_minor']==c['compensation_due_minor']==162000
    legacy_finance.configure_supplier_finance(hotel,100000,62000,0,False)
    result=fault.execute(c['case_id']);assert result['state']=='COMPLETED' and result['refund_state']=='REFUND_CONFIRMED_SIMULATION'
    assert result['compensation_state']=='COMPLETED' and fault.execute(c['case_id'])==result
    x=summary(r);assert x['release_minor']==38000 and x['credit_refund_minor']==162000 and x['capture_minor']==0
    assert summary(original)['refund_minor']==162000
    with SessionLocal() as s:
        case=s.get(Disruption,c['case_id']);intent=s.get(Intent,case.compensation_intent_id)
        assert intent.payer_id==hotel and intent.payee_id==account and intent.amount_minor==162000
        assert value.checked(s,credit['credit_id']).available_minor==0
        assert len(s.scalars(select(Ledger)).all())==6
        acct=s.get(Account,hotel);assert acct.settlement_available_minor==acct.reserve_available_minor==0
        li=s.scalar(select(Liability));assert li.actual_paid_minor==162000 and li.total_return_minor==324000


def test_finite_funds_keep_compensation_pending_then_resume_without_repeat_refund(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    legacy_finance.configure_supplier_finance(hotel,100000,0,0,False)
    pending=fault.execute(c['case_id']);assert pending['state']=='COMPENSATION_PENDING' and pending['refund_state']=='REFUND_CONFIRMED_SIMULATION'
    with SessionLocal() as s:
        assert s.get(Account,hotel).settlement_available_minor==100000
        assert not s.scalars(select(Compensation)).all() and len(s.scalars(select(Ledger)).all())==4
    legacy_finance.configure_supplier_finance(hotel,100000,62000,0,False)
    assert fault.execute(c['case_id'])['state']=='COMPLETED' and summary(original)['refund_minor']==162000
    with SessionLocal() as s:assert len(s.scalars(select(Ledger)).all())==6


def test_compensation_failure_rolls_back_fund_draw_and_preserves_completed_refund(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    legacy_finance.configure_supplier_finance(hotel,162000,0,0,False);post=money._post
    def fail(s,i,m):
        post(s,i,m)
        if i.business_type==funding.BUSINESS:raise RuntimeError('compensation ledger interrupted')
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError):fault.execute(c['case_id'])
    assert fault.status(c['case_id'])['state']=='COMPENSATION_PENDING' and summary(original)['refund_minor']==162000
    with SessionLocal() as s:assert s.get(Account,hotel).settlement_available_minor==162000 and not s.scalars(select(Compensation)).all()
    monkeypatch.setattr(money,'_post',post);fault.execute(c['case_id'])
    with SessionLocal() as s:assert s.get(Account,hotel).settlement_available_minor==0 and len(s.scalars(select(Ledger)).all())==6


def test_external_cause_refunds_without_debit_or_double_compensation(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account,'FORCE_MAJEURE')
    legacy_finance.configure_supplier_finance(hotel,162000,100000,500000,True)
    result=fault.execute(c['case_id']);assert result['state']=='COMPLETED' and result['compensation_due_minor']==0
    assert summary(original)['refund_minor']==162000
    with SessionLocal() as s:
        assert s.get(Account,hotel).settlement_available_minor==162000 and s.get(Account,hotel).bank_available_minor==500000
        assert not s.scalars(select(Compensation)).all()


def test_bank_requires_current_scoped_mandate_and_protection_is_finite(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    legacy_finance.configure_supplier_finance(hotel,10000,10000,200000,True)
    legacy_finance.configure_supplier_finance(funding.PROTECTION_ACCOUNT,0,5000,0,False)
    assert fault.execute(c['case_id'])['state']=='COMPENSATION_PENDING'
    with SessionLocal() as s:assert s.get(Account,hotel).bank_available_minor==200000 and s.get(Account,funding.PROTECTION_ACCOUNT).reserve_available_minor==5000
    mandate=funding.register_mandate(hotel,'CNY',142000,(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),'isolated-mandate://signed','b'*64,'finance')
    assert fault.execute(c['case_id'])['state']=='COMPLETED'
    with SessionLocal() as s:
        assert s.get(Account,hotel).bank_available_minor==58000 and s.get(Account,funding.PROTECTION_ACCOUNT).reserve_available_minor==5000
        payment=s.scalar(select(Compensation));assert payment.source_breakdown['mandate_id']==mandate['mandate_id']


def test_protection_advance_creates_exact_supplier_liability(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    legacy_finance.configure_supplier_finance(hotel,10000,10000,200000,False)
    legacy_finance.configure_supplier_finance(funding.PROTECTION_ACCOUNT,0,200000,0,False)
    assert fault.execute(c['case_id'])['state']=='COMPLETED'
    with SessionLocal() as s:
        assert s.get(Account,hotel).bank_available_minor==200000 and s.get(Account,hotel).negative_balance_minor==142000
        assert s.get(Account,funding.PROTECTION_ACCOUNT).reserve_available_minor==58000
        li=s.scalar(select(Liability));assert li.protection_fund_minor==li.negative_balance_minor==142000


def test_concurrent_execution_does_not_repeat_refund_or_compensation(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    legacy_finance.configure_supplier_finance(hotel,162000,0,0,False)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:fault.execute(c['case_id']),range(4)))
    assert all(x['state']=='COMPLETED' for x in results)
    with SessionLocal() as s:assert len(s.scalars(select(Ledger)).all())==6 and len(s.scalars(select(Compensation)).all())==1


def test_protection_recovery_is_idempotent_by_key_and_source_receipt(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    legacy_finance.configure_supplier_finance(hotel,10000,10000,0,False)
    legacy_finance.configure_supplier_finance(funding.PROTECTION_ACCOUNT,0,200000,0,False);fault.execute(c['case_id'])
    first=funding.recover(hotel,100000,'isolated-settlement://one','receipt-one','finance')
    assert first['recovered_minor']==100000 and first['negative_balance_minor']==42000
    assert funding.recover(hotel,100000,'isolated-settlement://one','receipt-one','finance')==first
    assert funding.recover(hotel,100000,'isolated-settlement://one','different-client-key','finance')==first
    with pytest.raises(ValueError,match='IDEMPOTENCY'):funding.recover(hotel,100001,'isolated-settlement://one','receipt-one','finance')
    second=funding.recover(hotel,70000,'isolated-settlement://two','receipt-two','finance');assert second['recovered_minor']==42000 and second['new_available_minor']==28000
    with SessionLocal() as s:
        assert s.get(Account,hotel).negative_balance_minor==0 and s.get(Account,hotel).settlement_available_minor==28000
        assert s.get(Account,funding.PROTECTION_ACCOUNT).reserve_available_minor==200000
        assert s.scalar(select(Liability)).status=='CLEARED'
        assert len(s.scalars(select(Ledger)).all())==6


def test_small_bank_mandate_caps_only_the_bank_portion(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    legacy_finance.configure_supplier_finance(hotel,10000,10000,200000,True)
    legacy_finance.configure_supplier_finance(funding.PROTECTION_ACCOUNT,0,200000,0,False)
    funding.register_mandate(hotel,'CNY',20000,(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),'isolated-mandate://limited','b'*64,'finance')
    fault.execute(c['case_id'])
    with SessionLocal() as s:
        assert s.get(Account,hotel).bank_available_minor==180000
        assert s.get(Account,hotel).negative_balance_minor==122000
        assert s.get(Account,funding.PROTECTION_ACCOUNT).reserve_available_minor==78000


def test_replaced_and_revoked_mandates_cannot_fall_back_to_old_bank_permission(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    legacy_finance.configure_supplier_finance(hotel,0,0,200000,True)
    expiry=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
    old=funding.register_mandate(hotel,'CNY',200000,expiry,'isolated-mandate://old','b'*64,'finance')
    new=funding.register_mandate(hotel,'CNY',200000,expiry,'isolated-mandate://new','c'*64,'finance')
    funding.revoke_mandate(new['mandate_id'],'finance')
    assert fault.execute(c['case_id'])['state']=='COMPENSATION_PENDING'
    with SessionLocal() as s:
        assert s.get(Mandate,old['mandate_id']).state=='SUPERSEDED' and s.get(Account,hotel).bank_available_minor==200000


def test_customer_retry_runs_approved_cancellation_before_refund(client,monkeypatch):
    from tests.test_depth07_hosted_money import after
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    with SessionLocal() as s:eid=s.get(Disruption,c['case_id']).refund_eligibility_id
    with pytest.raises(ValueError,match='CANCELLATION_BEFORE_REFUND'):funds.execute_refund(eid)
    result=after.retry_refund(account,r['hosted_reservation_id'],eid)
    assert result['state']=='COMPENSATION_PENDING' and summary(original)['refund_minor']==162000
    with SessionLocal() as s:assert s.get(Reservation,r['hosted_reservation_id']).reservation_state=='CANCELLED'
