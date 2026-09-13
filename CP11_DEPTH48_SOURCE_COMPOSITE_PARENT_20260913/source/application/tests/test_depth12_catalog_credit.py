import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from copy import deepcopy
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (OrderRow,StayCreditRow,PaymentOrderRootRow,OmnichannelMoneyMovementRow as Movement,
    CatalogCreditContractRow as Contract,CatalogCreditSourceRow as Source,CatalogCreditAllocationRow as Allocation,
    FareRuleRow,CatalogCreditQuoteRow as Quote)
from go_hotel.services import catalog_stay_credit as svc,catalog_credit_value as value
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.connectors.mock_hotel import connector
from test_sprint1m_fare_runtime import booked_order


def run(awaitable):return asyncio.run(awaitable)
def dates(days=100):return ((datetime.now(timezone.utc)+timedelta(days=days)).date().isoformat(),(datetime.now(timezone.utc)+timedelta(days=days+3)).date().isoformat())
def convert(client,idem='credit12'):
    oid=booked_order(client,idem=idem);q=svc.conversion_quote(oid)
    c=run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))
    return oid,c['stay_credit_id'],q
def redeem(cid,delta=0,days=100,token='pm_success'):
    ci,co=dates(days);connector.date_price_delta[ci]=delta
    q=run(svc.redemption_quote(cid,ci,co))
    r=run(svc.redeem(cid,q['quote_id'],q['quote_hash'],True,token,'owner'))
    return q,r
def net(oid):
    with SessionLocal() as s:
        rr=s.scalars(select(PaymentOrderRootRow).where(PaymentOrderRootRow.business_id==oid)).all()
        return s.scalars(select(Movement).where(Movement.root_payment_intent_id.in_([r.payment_intent_id for r in rr]))).all()


def test_conversion_actual_paid_and_original_source_refund_is_frozen(client):
    oid=booked_order(client)
    with SessionLocal.begin() as s:s.get(OrderRow,oid).total_amount_minor=9_000_000
    q=svc.conversion_quote(oid)
    assert q['credit_value_minor']==1_443_200
    cap=next(m for m in net(oid) if m.movement_type=='CAPTURE')
    money.create(cap.root_payment_intent_id,{'movement_type':'REFUND','parent_movement_id':cap.money_movement_id,'amount_minor':10_000,'mode':'CONTRACT_SIMULATOR','evidence':['prior-refund']},'prior','owner')
    with pytest.raises(ValueError,match='STALE'):run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))
    q=svc.conversion_quote(oid);c=run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))
    assert c['available_minor']==1_433_200
    with pytest.raises(ValueError,match='SOURCE_FUNDS_RESERVED'):
        money.create(cap.root_payment_intent_id,{'movement_type':'REFUND','parent_movement_id':cap.money_movement_id,'amount_minor':1,'mode':'CONTRACT_SIMULATOR','evidence':['double-refund']},'double-refund','owner')
    assert run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))['stay_credit_id']==c['stay_credit_id']
    assert connector.cancel_calls==1


def test_conversion_unknown_reply_queries_without_resending(client,monkeypatch):
    oid=booked_order(client);q=svc.conversion_quote(oid);original=connector.cancel
    async def lost(confirmation):await original(confirmation);raise TimeoutError('reply lost')
    monkeypatch.setattr(connector,'cancel',lost)
    c=run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))
    assert c['status']=='UNKNOWN_CANCEL' and c['available_minor']==0
    assert run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))['status']=='UNKNOWN_CANCEL'
    fixed=run(svc.reconcile_conversion(c['stay_credit_id'],'owner'))
    assert fixed['status']=='ACTIVE' and connector.cancel_calls==1


def test_rule_snapshot_consent_and_validity_are_fixed(client):
    oid=booked_order(client);q=svc.conversion_quote(oid)
    with pytest.raises(ValueError,match='CONSENT'):run(svc.convert(oid,q['quote_id'],q['quote_hash'],False,'owner'))
    with pytest.raises(ValueError,match='CONSENT'):run(svc.convert(oid,q['quote_id'],'0'*64,True,'owner'))
    from catalog_fare_helpers import publish_for_order
    with pytest.raises(ValueError,match='MAXIMUM_365'):publish_for_order(oid,stay_credit_days=10000)
    publish_for_order(oid,stay_credit_days=100)
    # Supplier rule changes cannot renew or shorten this accepted original-order deadline.
    c=run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))
    assert c['expires_at']==q['credit_expires_at']
    with SessionLocal() as s:
        original_created=s.get(OrderRow,oid).created_at.replace(tzinfo=timezone.utc)
    assert datetime.fromisoformat(c['expires_at'])==original_created+timedelta(days=365)
    oid2=booked_order(client,idem='new-rule')
    assert svc.conversion_quote(oid2)['validity_days']==100
    with SessionLocal.begin() as s:s.get(StayCreditRow,c['stay_credit_id']).expires_at+=timedelta(days=1)
    with pytest.raises(ValueError,match='VALIDITY_CHANGED'):svc.get_credit(c['stay_credit_id'])


def test_lower_price_forfeits_only_difference_and_no_new_capture(client):
    oid,cid,_=convert(client);q,r=redeem(cid,-43_200)
    assert r['status']=='REDEEMED' and r['applied_minor']==1_400_000 and r['forfeited_difference_minor']==43_200
    assert not net(r['order_id'])
    with SessionLocal() as s:
        c,p=value.checked(s,cid);assert p.available_minor==0 and c.credit_value_minor==1_443_200
    with pytest.raises(ValueError,match='NOT_ACTIVE'):run(svc.redemption_quote(cid,*dates(110)))


def test_four_redemptions_have_one_supplier_booking(client):
    _,cid,_=convert(client);ci,co=dates();q=run(svc.redemption_quote(cid,ci,co));before=connector.book_calls
    def action(_):return run(svc.redeem(cid,q['quote_id'],q['quote_hash'],True,'pm_success','owner'))
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(action,range(4)))
    assert len({r['order_id'] for r in results})==1 and connector.book_calls==before+1
    assert svc.get_credit(cid)['status']=='REDEEMED'


def test_different_quotes_cannot_double_spend_same_credit(client):
    _,cid,_=convert(client);one=run(svc.redemption_quote(cid,*dates(100)));two=run(svc.redemption_quote(cid,*dates(110)))
    run(svc.redeem(cid,one['quote_id'],one['quote_hash'],True,'pm_success','owner'))
    with pytest.raises(ValueError,match='NOT_ACTIVE'):run(svc.redeem(cid,two['quote_id'],two['quote_hash'],True,'pm_success','owner'))


def test_prebook_price_change_restores_credit_and_does_not_book(client):
    _,cid,_=convert(client);before=connector.book_calls;connector.prebook_price_delta_minor=500
    _,r=redeem(cid)
    assert r['status']=='FAILED' and connector.book_calls==before
    assert svc.get_credit(cid)['available_minor']==1_443_200
    with SessionLocal() as s:value.checked(s,cid)


def test_missing_prebook_reply_is_recovered_by_query(client,monkeypatch):
    _,cid,_=convert(client);original=connector.prebook_with_key
    async def lost(offer,key):await original(offer,key);raise TimeoutError('lost prebook')
    monkeypatch.setattr(connector,'prebook_with_key',lost)
    _,r=redeem(cid);assert r['status']=='UNKNOWN_PREBOOK'
    completed=run(svc.reconcile_redemption(r['order_id'],'owner'))
    assert completed['status']=='REDEEMED' and svc.get_credit(cid)['available_minor']==0


def test_missing_booking_reply_is_recovered_without_resend(client,monkeypatch):
    _,cid,_=convert(client);original=connector.book
    async def lost(oid,pb,idempotency_key=None):await original(oid,pb,idempotency_key);raise TimeoutError('lost book')
    monkeypatch.setattr(connector,'book',lost)
    _,r=redeem(cid,156_800);assert r['status']=='UNKNOWN_BOOK'
    calls=connector.book_calls
    assert not [m for m in net(r['order_id']) if m.movement_type=='CAPTURE']
    completed=run(svc.reconcile_redemption(r['order_id'],'owner'))
    assert completed['status']=='REDEEMED' and connector.book_calls==calls
    assert [m.amount_minor for m in net(r['order_id']) if m.movement_type=='CAPTURE']==[156_800]


def test_supplier_rejection_restores_credit_and_releases_difference(client):
    _,cid,_=convert(client);connector.fail_book=True
    _,r=redeem(cid,156_800);assert r['status']=='UNKNOWN_BOOK'
    completed=run(svc.reconcile_redemption(r['order_id'],'owner'))
    assert completed['status']=='FAILED' and svc.get_credit(cid)['available_minor']==1_443_200
    moves=net(r['order_id']);assert not any(m.movement_type=='CAPTURE' for m in moves)
    assert [m.amount_minor for m in moves if m.movement_type=='RELEASE']==[156_800]


def test_capture_failure_keeps_booking_and_credit_reserved_until_new_consent(client):
    _,cid,_=convert(client);q,r=redeem(cid,156_800,token='pm_capture_fail')
    assert r['status']=='CAPTURE_PENDING' and svc.get_credit(cid)['available_minor']==0
    calls=connector.book_calls
    with pytest.raises(ValueError,match='CONSENT'):svc.retry_payment(r['order_id'],q['quote_hash'],False,'pm_success','owner')
    completed=svc.retry_payment(r['order_id'],q['quote_hash'],True,'pm_success','owner')
    assert completed['status']=='REDEEMED' and connector.book_calls==calls
    assert [m.amount_minor for m in net(r['order_id']) if m.movement_type=='CAPTURE']==[156_800]


def test_authorization_decline_never_books_and_restores_credit(client):
    _,cid,_=convert(client);before=connector.book_calls
    _,r=redeem(cid,156_800,token='pm_decline')
    assert r['status']=='FAILED' and connector.book_calls==before and not net(r['order_id'])
    assert svc.get_credit(cid)['available_minor']==1_443_200


def test_declined_capture_retry_cannot_be_captured_by_status_reconciliation(client):
    _,cid,_=convert(client);q,r=redeem(cid,156_800,token='pm_capture_fail')
    calls=connector.book_calls
    declined=svc.retry_payment(r['order_id'],q['quote_hash'],True,'pm_decline','owner')
    assert declined['status']=='CAPTURE_PENDING'
    assert run(svc.reconcile_redemption(r['order_id'],'owner'))['status']=='CAPTURE_PENDING'
    assert not [m for m in net(r['order_id']) if m.movement_type=='CAPTURE']
    assert svc.get_credit(cid)['available_minor']==0 and connector.book_calls==calls
    assert svc.retry_payment(r['order_id'],q['quote_hash'],True,'pm_success','owner')['status']=='REDEEMED'
    assert [m.amount_minor for m in net(r['order_id']) if m.movement_type=='CAPTURE']==[156_800]


def test_unknown_booking_is_not_treated_as_rejection(client):
    _,cid,_=convert(client);connector.ambiguous_book=True
    _,r=redeem(cid,156_800);before=connector.book_calls
    assert run(svc.reconcile_redemption(r['order_id'],'owner'))['status']=='UNKNOWN_BOOK'
    assert svc.get_credit(cid)['available_minor']==0 and connector.book_calls==before


def test_expired_credit_cannot_be_redeemed_even_with_live_quote(client,monkeypatch):
    _,cid,_=convert(client);q=run(svc.redemption_quote(cid,*dates(100)))
    expiry=datetime.fromisoformat(svc.get_credit(cid)['expires_at'])
    monkeypatch.setattr(svc,'now',lambda:expiry+timedelta(seconds=1));monkeypatch.setattr(value,'now',lambda:expiry+timedelta(seconds=1))
    with pytest.raises(ValueError,match='EXPIRED'):run(svc.redeem(cid,q['quote_id'],q['quote_hash'],True,'pm_success','owner'))
    assert svc.get_credit(cid)['status']=='EXPIRED'


def test_quote_tamper_or_cross_property_never_reserves_credit(client):
    _,cid,_=convert(client);q=run(svc.redemption_quote(cid,*dates()))
    with SessionLocal.begin() as s:
        row=s.get(Quote,q['quote_id']);body=deepcopy(row.payload_json);body['property_id']='other';row.payload_json=body
    with pytest.raises(ValueError,match='QUOTE_FACT_MISMATCH'):run(svc.redeem(cid,q['quote_id'],q['quote_hash'],True,'pm_success','owner'))
    assert svc.get_credit(cid)['available_minor']==1_443_200
