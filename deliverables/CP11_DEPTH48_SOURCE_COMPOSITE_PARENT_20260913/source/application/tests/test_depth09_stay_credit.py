from copy import deepcopy
from datetime import date,timedelta
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedStayCreditRow as Credit,HostedCreditAllocationRow as Allocation,HostedCreditValueEventRow as CreditEvent,HostedFareQuoteRow as Quote,GuestStayLifecycleRow as Guest
from go_hotel.services import hosted_stay_credit as credit,hosted_credit_value as value,hosted_fare_rules as fare
from tests.test_depth08_hosted_fare import booked,RULES,quote as cancel_quote,execute as cancel_execute
from tests.test_depth08_hosted_change import rate
from tests.test_depth07_hosted_money import summary,inventory,guest,payment,PROOF,Reservation,Ledger,Authorization,ops,trips


def issued(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch,rules={**deepcopy(RULES),'credit_terms':value.TERMS})
    q=credit.conversion_quote(r['hosted_reservation_id'],account)
    result=credit.convert(r['hosted_reservation_id'],account,q['quote_id'],q['retained_value_minor'],'CNY')
    return r,account,h,a,q,result['credit']


def redemption(r,account,c,nightly=81000):
    cin=(date.fromisoformat(r['check_in'])+timedelta(days=2)).isoformat();cout=(date.fromisoformat(r['check_out'])+timedelta(days=2)).isoformat()
    rate(r,cin,cout,nightly)
    return credit.redemption_quote(c['credit_id'],account,r['hosted_offer_id'],cin,cout)


def redeem(r,account,c,q):return credit.redeem(c['credit_id'],account,q['quote_id'],q['amount_due_minor'],'CNY','TEST GUEST','13800000000')


def test_conversion_is_funded_single_issue_and_preserves_original_expiry_on_replay(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch)
    result=credit.convert(r['hosted_reservation_id'],account,q['quote_id'],q['retained_value_minor'],'CNY')
    assert result['credit']==c and c['available_minor']==162000
    assert summary(r)['capture_minor']==162000 and summary(r)['held_minor']==0
    assert inventory(r)==[('RELEASED',8),('RELEASED',8)]
    assert trips.list(account)[0]['lifecycle_state']=='CONVERTED_TO_CREDIT'
    with SessionLocal() as s:
        assert len(s.scalars(select(Credit)).all())==1 and len(s.scalars(select(Ledger)).all())==2
        assert value.checked(s,c['credit_id']).available_minor==162000
        original=s.scalar(select(Guest).where(Guest.hosted_reservation_id==r['hosted_reservation_id']))
        assert original.actual_check_in_at is None and original.actual_check_out_at is None


@pytest.mark.parametrize('nightly,due,applied,forfeited',[(100000,38000,162000,0),(81000,0,162000,0),(40000,0,80000,82000)])
def test_redemption_higher_equal_lower_and_final_fulfillment_without_duplicate_cash(client,monkeypatch,nightly,due,applied,forfeited):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c,nightly)
    assert (q['amount_due_minor'],q['applied_credit_minor'],q['forfeited_difference_minor'])==(due,applied,forfeited)
    new=redeem(r,account,c,q);assert redeem(r,account,c,q)==new
    newr={'hosted_reservation_id':new['reservation_id']};x=summary(newr)
    assert x['held_minor']==due and x['capture_minor']==0 and x['prepaid_credit_minor']==applied
    with SessionLocal() as s:
        assert s.get(Credit,c['credit_id']).available_minor==0
        auth=s.scalar(select(Authorization).where(Authorization.hosted_reservation_id==new['reservation_id']));aid=auth.authorization_id
        assert len(s.scalars(select(Ledger)).all())==2
    sid=guest.create(new['reservation_id'],'hotel')['stay_lifecycle_id']
    guest.identity(sid,{'identity_evidence_hash':'a'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'},'hotel');guest.arrive(sid,'hotel')
    guest.assign_room(sid,{'room_reference':'SIM-101'},'hotel');guest.check_in(sid,{'registration_evidence_reference':'test://reg'},'hotel')
    guest.checkout(sid,PROOF,'hotel');payment.fulfill(aid,PROOF,'hotel');payment.capture(aid,{'mode':'CONTRACT_DRY_RUN'})
    x=summary(newr);assert x['capture_minor']==due and x['prepaid_credit_minor']==applied and x['held_minor']==0
    with SessionLocal() as s:assert len(s.scalars(select(Ledger)).all())==(4 if due else 2)


def test_cancel_returns_only_unused_credit_not_lower_price_forfeiture(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c,40000);new=redeem(r,account,c,q)
    from datetime import datetime,timezone
    monkeypatch.setattr(fare,'now',lambda:datetime.fromisoformat(q['check_in']).replace(hour=5,tzinfo=timezone.utc))
    newr={'hosted_reservation_id':new['reservation_id'],'currency':'CNY'};cancel=cancel_quote(newr,account)
    assert cancel['fee_minor']==40000 and cancel['prepaid_fee_minor']==40000 and cancel['cash_fee_minor']==0 and cancel['restored_credit_minor']==40000
    result=cancel_execute(newr,account,cancel)
    assert result['fee_captured_minor']==0 and result['prepaid_fee_minor']==result['restored_credit_minor']==40000
    with SessionLocal() as s:
        current=value.checked(s,c['credit_id']);assert current.available_minor==40000 and current.expires_at.isoformat().startswith(c['expires_at'][:19])
        assert len(s.scalars(select(Ledger)).all())==2


def test_cancelled_credit_fee_refund_does_not_refund_restored_credit_twice(client,monkeypatch):
    from tests.test_depth07_hosted_money import approve,after,dispute
    from datetime import datetime,timezone
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c,40000);new=redeem(r,account,c,q)
    monkeypatch.setattr(fare,'now',lambda:datetime.fromisoformat(q['check_in']).replace(hour=5,tzinfo=timezone.utc))
    newr={'hosted_reservation_id':new['reservation_id'],'currency':'CNY'};cancel_execute(newr,account,cancel_quote(newr,account))
    case=after.open_case(account,new['reservation_id'],'CANCELLATION','取消费用复核','credit-fee-case')
    with SessionLocal() as s:sid=s.scalar(select(Guest).where(Guest.hosted_reservation_id==new['reservation_id'])).stay_lifecycle_id
    with pytest.raises(ValueError,match='REFUND_EXCEEDS'):approve(sid,40001,case['case_id'])
    _,e=approve(sid,40000,case['case_id']);result=after.retry_refund(account,new['reservation_id'],e['refund_eligibility_id'])
    assert after.retry_refund(account,new['reservation_id'],e['refund_eligibility_id'])==result
    assert summary(newr)['total_refund_minor']==40000 and summary(newr)['credit_refund_minor']==40000
    with SessionLocal() as s:assert value.checked(s,c['credit_id']).available_minor==40000
    dispute.close(case['case_id'],{'closure_evidence_reference':'test://closed'},'manager')


def test_unused_credit_refund_freezes_redemption_and_survives_executor_failure(client,monkeypatch):
    from tests.test_depth07_hosted_money import approve,after,money
    r,account,h,a,q,c=issued(client,monkeypatch);redeem_q=redemption(r,account,c)
    case=after.open_case(account,r['hosted_reservation_id'],'CANCELLATION','申请核验未使用额度','credit-unused-case')
    with SessionLocal() as s:sid=s.scalar(select(Guest).where(Guest.hosted_reservation_id==r['hosted_reservation_id'])).stay_lifecycle_id
    with pytest.raises(ValueError,match='CLOSE_UNUSED'):approve(sid,1000,case['case_id'])
    _,e=approve(sid,162000,case['case_id'])
    with pytest.raises(ValueError,match='NOT_AVAILABLE'):redeem(r,account,c,redeem_q)
    post=money._post
    def fail(*args):post(*args);raise RuntimeError('refund interrupted')
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError):after.retry_refund(account,r['hosted_reservation_id'],e['refund_eligibility_id'])
    assert summary(r)['refund_state']=='REFUND_PROCESSING' and summary(r)['refund_minor']==0
    with SessionLocal() as s:assert s.get(Credit,c['credit_id']).state=='FROZEN_REFUND'
    monkeypatch.setattr(money,'_post',post);after.retry_refund(account,r['hosted_reservation_id'],e['refund_eligibility_id'])
    assert summary(r)['refund_minor']==162000
    with SessionLocal() as s:assert value.checked(s,c['credit_id']).available_minor==0 and s.get(Credit,c['credit_id']).state=='REFUNDED'


def test_redeemed_stay_refund_spans_cash_and_credit_original_captures(client,monkeypatch):
    from tests.test_depth07_hosted_money import approve,after
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c,100000);new=redeem(r,account,c,q)
    sid=guest.create(new['reservation_id'],'hotel')['stay_lifecycle_id']
    guest.identity(sid,{'identity_evidence_hash':'a'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'},'hotel');guest.arrive(sid,'hotel')
    guest.assign_room(sid,{'room_reference':'SIM-101'},'hotel');guest.check_in(sid,{'registration_evidence_reference':'test://reg'},'hotel')
    guest.checkout(sid,PROOF,'hotel')
    with SessionLocal() as s:aid=s.scalar(select(Authorization).where(Authorization.hosted_reservation_id==new['reservation_id'])).authorization_id
    payment.fulfill(aid,PROOF,'hotel');payment.capture(aid,{'mode':'CONTRACT_DRY_RUN'})
    _,e=approve(sid,200000);result=after.retry_refund(account,new['reservation_id'],e['refund_eligibility_id'])
    assert len(result['money_movement_ids'])==len(result['original_capture_ids'])==2
    x=summary({'hosted_reservation_id':new['reservation_id']});assert x['refund_minor']==38000 and x['credit_refund_minor']==162000 and x['total_refund_minor']==200000
