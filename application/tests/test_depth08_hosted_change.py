from datetime import date,timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedRateCalendarDayRow as Rate,HostedDirectRateVariantRow as Variant,HostedFareFundingRow as Funding,HostedReservationNightRow as Night,HostedInventoryDayRow as Inventory
from go_hotel.services import hosted_fare_change as change
from tests.test_depth08_hosted_fare import booked,quote,execute as cancel,RULES
from tests.test_depth07_hosted_money import summary,funds,guest,payment,PROOF,approve,after,Reservation,Authorization,Ledger,ops


def change_quote(r,account,offset=1,action='CHANGE_DATE',days=2):
    cin=date.fromisoformat(r['check_in'])+timedelta(days=offset) if action=='CHANGE_DATE' else date.fromisoformat(r['check_in'])
    cout=cin+timedelta(days=days)
    return change.create_quote(r['hosted_reservation_id'],account,action,cin.isoformat(),cout.isoformat())


def apply(r,account,q):return change.execute(r['hosted_reservation_id'],account,q['quote_id'],q['new_amount_minor'],q['additional_amount_minor'],'CNY')


def rate(r,check_in,check_out,value):
    with SessionLocal.begin() as s:
        v=s.scalar(select(Variant).where(Variant.hosted_offer_id==r['hosted_offer_id']))
        for x in s.scalars(select(Rate).where(Rate.rate_variant_id==v.rate_variant_id,Rate.stay_date>=check_in,Rate.stay_date<check_out)):x.price_minor=value


@pytest.mark.parametrize('nightly,expected',[(100000,200000),(81000,162000),(40000,162000)])
def test_change_high_supplement_low_no_refund_and_immutable_original_authorization(client,monkeypatch,nightly,expected):
    r,account,h,a,p=booked(client,monkeypatch)
    q=change_quote(r,account);rate(r,q['check_in'],q['check_out'],nightly);q=change_quote(r,account)
    assert q['new_amount_minor']==expected and q['cash_refund_minor']==q['stay_credit_minor']==0
    with pytest.raises(ValueError,match='RECONFIRM'):change.execute(r['hosted_reservation_id'],account,q['quote_id'],expected,1,'CNY')
    result=apply(r,account,q);assert apply(r,account,q)==result
    x=summary(r);assert x['held_minor']==expected and x['release_minor']==(162000 if expected>162000 else 0) and x['capture_minor']==0
    with SessionLocal() as s:
        assert s.get(Authorization,a['authorization_id']).amount_minor==162000
        assert len(s.scalars(select(Funding)).all())==(1 if expected>162000 else 0) and s.scalars(select(Ledger)).all()==[]
        held=s.scalars(select(Night).where(Night.hosted_reservation_id==r['hosted_reservation_id'],Night.state=='HELD')).all()
        assert len(held)==2 and all(s.get(Inventory,n.inventory_day_id).capacity_available==7 for n in held)
        updated=s.get(Reservation,r['hosted_reservation_id']);assert updated.amount_minor==expected
    # Fee cancellation now binds the replacement hold; it never recaptures the old root.
    cancelled=cancel(r,account,quote(r,account));assert cancelled['authorization_released_minor']+cancelled['fee_captured_minor']+cancelled['cash_forfeiture_minor']==expected
    assert summary(r)['held_minor']==0


def test_stale_quote_price_change_last_night_sold_out_and_ledger_fault_keep_old_stay(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch);q=change_quote(r,account)
    rate(r,q['check_in'],q['check_out'],100000)
    with pytest.raises(ValueError,match='RATE_CHANGED'):apply(r,account,q)
    q=change_quote(r,account);target=q['nights'][-1]['inventory_day_id']
    with SessionLocal.begin() as s:s.get(Inventory,target).capacity_available=0
    with pytest.raises(ValueError,match='NO_DATED_INVENTORY'):apply(r,account,q)
    with SessionLocal.begin() as s:s.get(Inventory,target).capacity_available=8
    original=change.replace_authorization
    def fail(s,*args):original(s,*args);raise RuntimeError('after new authorization before commit')
    monkeypatch.setattr(change,'replace_authorization',fail)
    with pytest.raises(RuntimeError):apply(r,account,q)
    assert summary(r)['held_minor']==162000 and summary(r)['release_minor']==0
    with SessionLocal() as s:
        row=s.get(Reservation,r['hosted_reservation_id']);assert row.check_in==r['check_in'] and row.amount_minor==162000
        assert s.get(Inventory,target).capacity_available==8 and not s.scalars(select(Funding)).all()
    monkeypatch.setattr(change,'replace_authorization',original);apply(r,account,q)
    assert summary(r)['held_minor']==200000


def test_multiple_changes_keep_prior_roots_and_refund_final_original_capture(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch)
    q=change_quote(r,account,offset=1);rate(r,q['check_in'],q['check_out'],100000);q=change_quote(r,account,offset=1);first=apply(r,account,q)
    r={**r,**first};q=change_quote(r,account,offset=1);rate(r,q['check_in'],q['check_out'],120000);q=change_quote(r,account,offset=1);second=apply(r,account,q);r={**r,**second}
    assert r['amount_minor']==240000 and summary(r)['held_minor']==240000 and summary(r)['release_minor']==362000
    sid=guest.create(r['hosted_reservation_id'],'hotel')['stay_lifecycle_id']
    guest.identity(sid,{'identity_evidence_hash':'a'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'},'hotel');guest.arrive(sid,'hotel')
    guest.assign_room(sid,{'room_reference':'SIM-101'},'hotel');guest.check_in(sid,{'registration_evidence_reference':'test://reg'},'hotel')
    guest.checkout(sid,{**PROOF,'fulfilled_amount_minor':240000},'hotel');payment.fulfill(a['authorization_id'],PROOF,'hotel');payment.capture(a['authorization_id'],{'mode':'CONTRACT_DRY_RUN'})
    assert summary(r)['capture_minor']==240000 and summary(r)['held_minor']==0
    _,e=approve(sid,240000);after.retry_refund(account,r['hosted_reservation_id'],e['refund_eligibility_id'])
    assert summary(r)['refund_minor']==240000
    with SessionLocal() as s:assert len(s.scalars(select(Funding)).all())==2 and len(s.scalars(select(Ledger)).all())==4


def test_in_house_extension_preserves_old_night_prices_and_updates_fulfillment(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch);sid=guest.create(r['hosted_reservation_id'],'hotel')['stay_lifecycle_id']
    guest.identity(sid,{'identity_evidence_hash':'a'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'},'hotel');guest.arrive(sid,'hotel')
    guest.assign_room(sid,{'room_reference':'SIM-101'},'hotel');guest.check_in(sid,{'registration_evidence_reference':'test://reg'},'hotel')
    rate(r,r['check_in'],r['check_out'],999999)
    with pytest.raises(ValueError,match='PRE_ARRIVAL'):change_quote(r,account)
    q=change_quote(r,account,action='EXTEND_STAY',days=3)
    assert [x['price_minor'] for x in q['nights']]==[81000,81000,81000]
    assert q['new_amount_minor']==243000 and q['additional_amount_minor']==81000
    apply(r,account,q)
    from go_hotel.db.models import GuestStayLifecycleRow
    with SessionLocal() as s:assert s.get(GuestStayLifecycleRow,sid).planned_check_out==q['check_out']
    guest.checkout(sid,PROOF,'hotel');payment.fulfill(a['authorization_id'],PROOF,'hotel');payment.capture(a['authorization_id'],{'mode':'CONTRACT_DRY_RUN'})
    assert summary(r)['capture_minor']==243000 and summary(r)['held_minor']==0


def test_parallel_changes_owner_and_currency_never_double_release(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch);rate(r,r['check_in'],(date.fromisoformat(r['check_out'])+timedelta(days=3)).isoformat(),100000);qs=[change_quote(r,account,offset=i) for i in (1,2)]
    with pytest.raises(ValueError,match='NOT_FOUND'):apply(r,'other',qs[0])
    with pytest.raises(ValueError,match='RECONFIRM'):change.execute(r['hosted_reservation_id'],account,qs[0]['quote_id'],163000,1000,'USD')
    def attempt(q):
        try:return apply(r,account,q)['state']
        except ValueError as error:return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,qs))
    assert results.count('CONFIRMED')==1 and summary(r)['held_minor']==200000 and summary(r)['release_minor']==162000


def test_zero_fee_equal_or_lower_reprice_keeps_hold_without_minting_credit(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch,rules={**RULES,'change_fee_minor':0})
    q=change_quote(r,account);rate(r,q['check_in'],q['check_out'],40000);q=change_quote(r,account)
    assert q['additional_amount_minor']==q['authorization_replacement_minor']==q['cash_refund_minor']==q['stay_credit_minor']==0
    apply(r,account,q);x=summary(r)
    assert x['held_minor']==162000 and x['authorization_minor']==162000 and x['release_minor']==0
    with SessionLocal() as s:assert s.scalars(select(Funding)).all()==[]


def test_unknown_money_and_open_dispute_freeze_dated_changes(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch);q=change_quote(r,account)
    with SessionLocal.begin() as s:s.get(Authorization,a['authorization_id']).external_invoked=True
    with pytest.raises(ValueError,match='RECONCILIATION'):apply(r,account,q)
    with SessionLocal.begin() as s:s.get(Authorization,a['authorization_id']).external_invoked=False
    sid=guest.create(r['hosted_reservation_id'],'hotel')['stay_lifecycle_id']
    guest.dispute(sid,{'dispute_type':'AMOUNT','evidence_reference':'test://disputed'},'hotel')
    with pytest.raises(ValueError,match='DISPUTE'):change_quote(r,account)
    assert summary(r)['held_minor']==162000 and summary(r)['release_minor']==0


def test_changed_order_no_show_settles_current_hold_and_can_refund_it(client,monkeypatch):
    from datetime import datetime,timezone
    from go_hotel.services import hosted_fare_rules as fare
    r,account,h,a,p=booked(client,monkeypatch);q=change_quote(r,account);changed=apply(r,account,q);r={**r,**changed}
    sid=guest.create(r['hosted_reservation_id'],'hotel')['stay_lifecycle_id']
    monkeypatch.setattr(fare,'now',lambda:datetime.fromisoformat(r['check_in']).replace(hour=16,tzinfo=timezone.utc))
    q=fare.create_quote(r['hosted_reservation_id'],'NO_SHOW');review=fare.request_no_show(r['hosted_reservation_id'],q['quote_id'],'hotel')
    payment.approve_adjustment(review['adjustment_approval_id'],{'evidence_reference':'test://review'},'checker')
    guest.no_show(sid,{'fare_quote_id':q['quote_id'],'expected_fee_minor':q['fee_minor'],'currency':'CNY','approval_id':review['adjustment_approval_id'],'hotel_no_show_evidence':'test://no-show'},'hotel')
    assert summary(r)['capture_minor']==129600 and summary(r)['held_minor']==0
    _,e=approve(sid,129600);after.retry_refund(account,r['hosted_reservation_id'],e['refund_eligibility_id'])
    assert summary(r)['refund_minor']==129600
