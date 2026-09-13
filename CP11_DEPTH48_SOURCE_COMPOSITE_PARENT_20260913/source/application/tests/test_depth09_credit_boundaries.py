"""Credit source conservation, failure rollback and competing customer actions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta,timezone
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectRoomOfferRow as Offer,HostedReservationNightRow as Night,HostedInventoryDayRow as Inventory,GuestStayLifecycleRow as Guest
from go_hotel.services import hosted_fare_change as change
from tests.test_depth09_stay_credit import issued,redemption,redeem,booked,RULES,credit,value,fare,rate,summary,inventory,guest,payment,PROOF,Reservation,Ledger,Authorization,ops,trips,Credit,Allocation,CreditEvent,Quote
from tests.test_depth07_hosted_money import funds,money,after,dispute,approve,Movement,Refund


def finish(new,amount=None):
    rid=new['reservation_id'];sid=guest.create(rid,'hotel')['stay_lifecycle_id']
    guest.identity(sid,{'identity_evidence_hash':'a'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'},'hotel');guest.arrive(sid,'hotel')
    guest.assign_room(sid,{'room_reference':'SIM-101'},'hotel');guest.check_in(sid,{'registration_evidence_reference':'test://registration'},'hotel')
    guest.checkout(sid,PROOF if amount is None else {**PROOF,'fulfilled_amount_minor':amount},'hotel')
    with SessionLocal() as s:aid=s.scalar(select(Authorization).where(Authorization.hosted_reservation_id==rid)).authorization_id
    payment.fulfill(aid,PROOF,'hotel');payment.capture(aid,{'mode':'CONTRACT_DRY_RUN'})
    return sid,aid


def test_missing_historical_credit_terms_are_never_retrofitted(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch)
    with pytest.raises(ValueError,match='COMPLETE_ORDER'):credit.conversion_quote(r['hosted_reservation_id'],account)
    fare.publish(r['hosted_offer_id'],{**RULES,'credit_terms':value.TERMS},'test://new-explicit-terms','hotel')
    with pytest.raises(ValueError,match='COMPLETE_ORDER'):credit.conversion_quote(r['hosted_reservation_id'],account)
    assert summary(r)['capture_minor']==0


def test_conversion_failure_rolls_back_capture_inventory_credit_and_trip(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch,rules={**RULES,'credit_terms':value.TERMS})
    q=credit.conversion_quote(r['hosted_reservation_id'],account);release=ops._release
    def fail(*args):release(*args);raise RuntimeError('inventory release interrupted')
    monkeypatch.setattr(ops,'_release',fail)
    with pytest.raises(RuntimeError):credit.convert(r['hosted_reservation_id'],account,q['quote_id'],162000,'CNY')
    assert summary(r)['capture_minor']==0 and inventory(r)==[('HELD',7),('HELD',7)]
    with SessionLocal() as s:assert not s.scalars(select(Credit)).all() and not s.scalars(select(Ledger)).all() and s.get(Quote,q['quote_id']).state=='QUOTED'
    monkeypatch.setattr(ops,'_release',release);credit.convert(r['hosted_reservation_id'],account,q['quote_id'],162000,'CNY')
    assert summary(r)['capture_minor']==162000


def test_owner_property_currency_amount_and_ledger_boundaries(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c)
    assert credit.list_credits('other')==[]
    with pytest.raises(ValueError,match='NOT_FOUND'):redeem(r,'other',c,q)
    for amount,currency in [(True,'CNY'),(1,'CNY'),(0,'USD')]:
        with pytest.raises(ValueError,match='RECONFIRM'):credit.redeem(c['credit_id'],account,q['quote_id'],amount,currency,'guest','mobile')
    with SessionLocal.begin() as s:s.get(Offer,r['hosted_offer_id']).hosted_hotel_id='different-property'
    with pytest.raises(ValueError,match='ORIGINAL_PROPERTY'):redemption(r,account,c)
    with SessionLocal.begin() as s:
        s.get(Offer,r['hosted_offer_id']).hosted_hotel_id=c['hosted_hotel_id'];s.get(Offer,r['hosted_offer_id']).currency='USD'
    with pytest.raises(ValueError,match='ORIGINAL_PROPERTY'):redemption(r,account,c)
    with SessionLocal.begin() as s:
        s.get(Offer,r['hosted_offer_id']).currency='CNY';s.scalar(select(CreditEvent)).delta_minor=162001
    with pytest.raises(ValueError,match='LEDGER_MISMATCH'):redeem(r,account,c,q)
    assert credit.list_credits(account)[0]['reconciliation_required']


def test_expiry_is_check_in_based_and_job_is_idempotent_without_refund(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch)
    last=(datetime.fromisoformat(c['expires_at'])+timedelta(days=1)).date().isoformat()
    with pytest.raises(ValueError,match='WITHIN_VALIDITY|ONE_YEAR_VALIDITY'):credit.redemption_quote(c['credit_id'],account,r['hosted_offer_id'],last,(date.fromisoformat(last)+timedelta(days=1)).isoformat())
    q=redemption(r,account,c);monkeypatch.setattr(fare,'now',lambda:datetime.fromisoformat(c['expires_at']))
    assert credit.list_credits(account)[0]['state']=='EXPIRED' and not credit.list_credits(account)[0]['can_redeem']
    with pytest.raises(ValueError,match='EXPIRED'):redeem(r,account,c,q)
    assert credit.expire()=={'expired_count':1} and credit.expire()=={'expired_count':0}
    with SessionLocal() as s:assert value.checked(s,c['credit_id']).available_minor==0
    assert summary(r)['refund_minor']==0 and summary(r)['capture_minor']==162000


def test_concurrent_distinct_quotes_consume_one_credit_once(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);quotes=[redemption(r,account,c) for _ in range(4)]
    def attempt(q):
        try:return redeem(r,account,c,q)
        except ValueError as error:return str(error)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(attempt,quotes))
    assert len([x for x in results if isinstance(x,dict)])==1
    assert all(isinstance(x,dict) or x=='STAY_CREDIT_NOT_AVAILABLE' for x in results)
    with SessionLocal() as s:
        assert len(s.scalars(select(Allocation)).all())==1 and s.get(Credit,c['credit_id']).available_minor==0
        assert len(s.scalars(select(Ledger)).all())==2


def test_redemption_failure_after_cash_authorization_restores_inventory_and_value(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c,100000);ensure=funds.ensure_authorization
    def fail(*args):ensure(*args);raise RuntimeError('redemption interrupted')
    monkeypatch.setattr(funds,'ensure_authorization',fail)
    with pytest.raises(RuntimeError):redeem(r,account,c,q)
    with SessionLocal() as s:
        assert not s.scalars(select(Allocation)).all() and value.checked(s,c['credit_id']).available_minor==162000
        assert all(s.get(Inventory,n['inventory_day_id']).capacity_available==8 for n in q['nights'])
        assert len(s.scalars(select(Authorization)).all())==1
    monkeypatch.setattr(funds,'ensure_authorization',ensure);new=redeem(r,account,c,q)
    assert summary({'hosted_reservation_id':new['reservation_id']})['held_minor']==38000


def test_source_unknown_blocks_child_refund_retry_and_reports_reconciliation(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c);new=redeem(r,account,c,q);sid,aid=finish(new)
    _,e=approve(sid,1000)
    with SessionLocal.begin() as s:s.get(Authorization,a['authorization_id']).state='UNKNOWN_EXTERNAL_STATE'
    with SessionLocal() as s:
        info=after.status(s,account,new['reservation_id']);assert info['funds']['reconciliation_required'] and not info['cases'][0]['retry_allowed']
    with pytest.raises(ValueError,match='RECONCILIATION'):after.retry_refund(account,new['reservation_id'],e['refund_eligibility_id'])
    assert summary({'hosted_reservation_id':new['reservation_id']})['total_refund_minor']==0


def test_partial_fulfillment_restores_only_unused_credit_without_extending_expiry(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c,100000);new=redeem(r,account,c,q);sid,aid=finish(new,100000)
    x=summary({'hosted_reservation_id':new['reservation_id']});assert x['capture_minor']==0 and x['release_minor']==38000 and x['prepaid_credit_minor']==100000
    with SessionLocal() as s:
        current=value.checked(s,c['credit_id']);assert current.available_minor==62000
        assert current.expires_at.isoformat().startswith(c['expires_at'][:19])
    payment.capture(aid,{'mode':'CONTRACT_DRY_RUN'})
    cid,e=approve(sid,100000);assert dispute.reconcile(cid)['decision']=='CONTRACT_RECONCILED'
    after.retry_refund(account,new['reservation_id'],e['refund_eligibility_id'])
    with SessionLocal() as s:assert value.checked(s,c['credit_id']).available_minor==62000


def test_credit_change_reauthorizes_cash_only_and_cannot_extend_credit_validity(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c);new=redeem(r,account,c,q)
    start=(date.fromisoformat(q['check_in'])+timedelta(days=1)).isoformat();end=(date.fromisoformat(q['check_out'])+timedelta(days=1)).isoformat()
    rate(r,start,end,100000)
    cq=change.create_quote(new['reservation_id'],account,'CHANGE_DATE',start,end)
    assert cq['new_amount_minor']==200000 and cq['authorization_replacement_minor']==38000 and cq['prepaid_credit_minor']==162000
    change.execute(new['reservation_id'],account,cq['quote_id'],200000,38000,'CNY')
    x=summary({'hosted_reservation_id':new['reservation_id']});assert x['held_minor']==38000 and x['capture_minor']==0
    last=(datetime.fromisoformat(c['expires_at'])+timedelta(days=1)).date().isoformat()
    with pytest.raises(ValueError,match='WITHIN_VALIDITY|ONE_YEAR_VALIDITY'):change.create_quote(new['reservation_id'],account,'CHANGE_DATE',last,(date.fromisoformat(last)+timedelta(days=1)).isoformat())
    finish(new);assert summary({'hosted_reservation_id':new['reservation_id']})['capture_minor']==38000


def test_two_capture_refund_failure_is_atomic_and_retry_has_no_duplicate_ledger(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c,100000);new=redeem(r,account,c,q);sid,aid=finish(new)
    case,e=approve(sid,200000);post=money._post;calls=[]
    def fail(*args):
        post(*args);calls.append(1)
        if len(calls)==2:raise RuntimeError('second refund source interrupted')
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError):after.retry_refund(account,new['reservation_id'],e['refund_eligibility_id'])
    assert summary({'hosted_reservation_id':new['reservation_id']})['total_refund_minor']==0 and summary(r)['refund_minor']==0
    monkeypatch.setattr(money,'_post',post);result=after.retry_refund(account,new['reservation_id'],e['refund_eligibility_id'])
    assert after.retry_refund(account,new['reservation_id'],e['refund_eligibility_id'])==result
    assert dispute.reconcile(case)['decision']=='CONTRACT_RECONCILED'
    with SessionLocal() as s:assert len(s.scalars(select(Ledger)).all())==8
    original=next(t for t in trips.list(account) if t['order_id']==r['hosted_reservation_id']);assert original['facts_json']['funds']['refund_minor']==162000


def test_last_night_exhaustion_and_changed_price_leave_credit_untouched(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c)
    with SessionLocal.begin() as s:s.get(Inventory,q['nights'][-1]['inventory_day_id']).capacity_available=0
    with pytest.raises(ValueError,match='NO_DATED_INVENTORY'):redeem(r,account,c,q)
    with SessionLocal.begin() as s:
        assert value.checked(s,c['credit_id']).available_minor==162000
        assert s.get(Inventory,q['nights'][0]['inventory_day_id']).capacity_available==8
        s.get(Inventory,q['nights'][-1]['inventory_day_id']).capacity_available=8
    rate(r,q['check_in'],q['check_out'],100000)
    with pytest.raises(ValueError,match='RATE_CHANGED'):redeem(r,account,c,q)
    with SessionLocal() as s:assert not s.scalars(select(Allocation)).all() and value.checked(s,c['credit_id']).available_minor==162000


def test_repeated_redemption_cancellation_refunds_conserve_original_value(client,monkeypatch):
    from tests.test_depth09_stay_credit import cancel_quote,cancel_execute
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c);first=redeem(r,account,c,q)
    monkeypatch.setattr(fare,'now',lambda:datetime.fromisoformat(q['check_in']).replace(hour=5,tzinfo=timezone.utc))
    r1={'hosted_reservation_id':first['reservation_id'],'currency':'CNY'};cancel_execute(r1,account,cancel_quote(r1,account))
    q2=redemption(r,account,c,40000);assert q2['forfeited_difference_minor']==1000
    second=redeem(r,account,c,q2);r2={'hosted_reservation_id':second['reservation_id'],'currency':'CNY'};cancel_execute(r2,account,cancel_quote(r2,account))
    amounts=[(r1,81000),(r2,40000),(r,40000)];elig=[]
    for reservation,amount in amounts:
        with SessionLocal() as s:sid=s.scalar(select(Guest).where(Guest.hosted_reservation_id==reservation['hosted_reservation_id'])).stay_lifecycle_id
        case,e=approve(sid,amount);elig.append((reservation,e))
    for reservation,e in elig:after.retry_refund(account,reservation['hosted_reservation_id'],e['refund_eligibility_id'])
    with SessionLocal() as s:
        current=value.checked(s,c['credit_id']);assert current.available_minor==0 and current.state=='REFUNDED'
        assert sum(a.forfeited_minor for a in s.scalars(select(Allocation)))==1000
    assert summary(r)['refund_minor']==161000


def test_credit_refund_approval_and_redemption_cannot_spend_the_same_source(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c)
    case=after.open_case(account,r['hosted_reservation_id'],'CANCELLATION','请求核验','competing-refund')
    d=dispute.request_decision(case['case_id'],{'outcome':'PARTIAL_REFUND','refund_amount_minor':162000},'maker')
    def attempt(kind):
        try:
            return ('success',kind,redeem(r,account,c,q) if kind=='REDEEM' else dispute.approve_decision(d['post_stay_decision_id'],{'evidence_reference':'test://review'},'checker'))
        except ValueError as error:return ('blocked',kind,str(error))
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,['REDEEM','REFUND']))
    assert len([x for x in results if x[0]=='success'])==1
    with SessionLocal() as s:
        current=value.checked(s,c['credit_id']);assert (current.state,current.available_minor) in {('ALLOCATED',0),('FROZEN_REFUND',162000)}


def test_credit_no_show_uses_prepaid_then_cash_and_keeps_independent_review(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c,120000);new=redeem(r,account,c,q)
    sid=guest.create(new['reservation_id'],'hotel')['stay_lifecycle_id']
    monkeypatch.setattr(fare,'now',lambda:datetime.fromisoformat(q['check_in']).replace(hour=16,tzinfo=timezone.utc))
    fee=fare.create_quote(new['reservation_id'],'NO_SHOW');assert fee['fee_minor']==192000 and fee['prepaid_fee_minor']==162000 and fee['cash_fee_minor']==30000
    approval=fare.request_no_show(new['reservation_id'],fee['quote_id'],'hotel')
    with pytest.raises(ValueError,match='MAKER_CHECKER'):payment.approve_adjustment(approval['adjustment_approval_id'],{'evidence_reference':'test://review'},'hotel')
    payment.approve_adjustment(approval['adjustment_approval_id'],{'evidence_reference':'test://review'},'checker')
    body={'fare_quote_id':fee['quote_id'],'expected_fee_minor':192000,'currency':'CNY','approval_id':approval['adjustment_approval_id'],'hotel_no_show_evidence':'test://desk'}
    result=guest.no_show(sid,body,'hotel');assert guest.no_show(sid,body,'hotel')==result
    x=summary({'hosted_reservation_id':new['reservation_id']});assert x['capture_minor']==30000 and x['release_minor']==48000 and x['prepaid_credit_minor']==162000
    with SessionLocal() as s:assert value.checked(s,c['credit_id']).available_minor==0


def test_unused_credit_refund_expiry_does_not_depend_on_background_job_timing(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch)
    with SessionLocal() as s:sid=s.scalar(select(Guest).where(Guest.hosted_reservation_id==r['hosted_reservation_id'])).stay_lifecycle_id
    expiry=datetime.fromisoformat(c['expires_at']);monkeypatch.setattr(fare,'now',lambda:expiry)
    with pytest.raises(ValueError,match='REFUND_EXCEEDS'):approve(sid,162000)
    credit.expire()
    with pytest.raises(ValueError,match='REFUND_EXCEEDS'):approve(sid,162000)
    assert summary(r)['refund_minor']==0


def test_unused_credit_refund_approved_before_expiry_remains_payable_after_expiry(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch)
    with SessionLocal() as s:sid=s.scalar(select(Guest).where(Guest.hosted_reservation_id==r['hosted_reservation_id'])).stay_lifecycle_id
    case,e=approve(sid,162000)
    monkeypatch.setattr(fare,'now',lambda:datetime.fromisoformat(c['expires_at'])+timedelta(seconds=1))
    assert credit.expire()=={'expired_count':0}
    result=after.retry_refund(account,r['hosted_reservation_id'],e['refund_eligibility_id']);assert result['amount_minor']==162000
    with SessionLocal() as s:assert value.checked(s,c['credit_id']).state=='REFUNDED'
