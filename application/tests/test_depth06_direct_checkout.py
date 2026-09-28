from tests.hosted_review_support import legacy_publication,fare_hash,register_isolated_rooms
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta,timezone
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (HostedDirectReservationRow as Reservation,HostedReservationStayRow as Stay,
    HostedReservationNightRow as Night,HostedInventoryDayRow as Inventory,
    HostedDirectRateVariantRow as Variant,AlipayAuthorizationRow as Authorization,
    AlipaySafeguardedEventRow as Event)
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services.official_hotel_catalog import configure_official_hotel,seed_demo_inventory
from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops
from go_hotel.services import hosted_checkout as checkout
from go_hotel.services.alipay_safeguarded_settlement import alipay_safeguarded_settlement_service as payment
from tests.test_sprint3a_flight import auth


def reservation(client):
    headers=auth(client);hotel=booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店'},'isolated-admin')
    configure_official_hotel();seed_demo_inventory(hotel['hosted_hotel_id'],days=8)
    legacy_publication(hotel['hosted_hotel_id'])
    cin=(date.today()+timedelta(days=1)).isoformat();cout=(date.today()+timedelta(days=3)).isoformat()
    available=ops.availability('aoluguya-harbin',{'check_in':cin,'check_out':cout,'adults':1})
    offer=available['items'][0]
    register_isolated_rooms(hotel['hosted_hotel_id'],offer['hosted_offer_id'],['SIM-101'])
    legacy_publication(hotel['hosted_hotel_id'])
    r=client.post('/v1/direct/aoluguya-harbin/reservations',headers={**headers,'Idempotency-Key':'direct-reserve'},
        json={'hosted_offer_id':offer['hosted_offer_id'],'check_in':cin,'check_out':cout,'guest_name':'TEST GUEST',
        'guest_contact':'13800000000','expected_total_minor':offer['total_amount_minor'],'expected_fare_rule_hash':fare_hash(offer['hosted_offer_id'])})
    assert r.status_code==200,r.text
    row=r.json()['data']
    with SessionLocal() as s:account=s.get(Stay,row['hosted_reservation_id']).created_by
    return row,account,headers


def freeze(r,account):return checkout.authorize(account,r['hosted_reservation_id'],r['amount_minor'],r['currency'])

def inventory(r):
    with SessionLocal() as s:
        nights=s.scalars(select(Night).where(Night.hosted_reservation_id==r['hosted_reservation_id'])).all()
        return [(n.state,s.get(Inventory,n.inventory_day_id).capacity_available) for n in nights]


def test_official_inventory_reservation_authorization_cancel_is_one_atomic_release(client):
    r,account,h=reservation(client);rid=r['hosted_reservation_id']
    assert inventory(r)==[('HELD',7),('HELD',7)]
    first=freeze(r,account);again=freeze(r,account)
    assert first==again and first['payment_captured'] is False
    assert first['authorization']['amount_minor']==r['amount_minor']
    status=client.get('/v1/direct/reservations/'+rid,headers=h).json()['data']
    assert status['reservation']['payment_state']=='CONTRACT_AUTHORIZED_NOT_ALIPAY'
    assert len(status['authorizations'])==1
    for _ in range(2):
        response=client.post('/v1/direct/reservations/'+rid+'/cancel',headers=h)
        assert response.status_code==200,response.text
    assert inventory(r)==[('RELEASED',8),('RELEASED',8)]
    with SessionLocal() as s:
        a=s.get(Authorization,first['authorization']['authorization_id'])
        assert a.state=='CONTRACT_RELEASED_NOT_ALIPAY' and not a.external_invoked
        assert len(s.scalars(select(Event).where(Event.event_type=='AUTHORIZATION_RELEASED')).all())==1
    with pytest.raises(ValueError,match='NOT_AUTHORIZABLE'):freeze(r,account)


def test_checkout_binds_owner_amount_currency_and_requires_explicit_mode(client):
    r,account,h=reservation(client);path='/v1/direct/reservations/'+r['hosted_reservation_id']+'/checkout'
    for amount,currency in [(1,'CNY'),(r['amount_minor'],'USD'),(True,'CNY')]:
        with pytest.raises(ValueError,match='RECONFIRM'):checkout.authorize(account,r['hosted_reservation_id'],amount,currency)
    with pytest.raises(ValueError,match='NOT_FOUND'):freeze(r,'intruder')
    response=client.post(path,headers=h,json={'expected_amount_minor':r['amount_minor'],'currency':'CNY'})
    assert response.status_code==422
    with SessionLocal() as s:assert not s.scalars(select(Authorization)).all()
    assert inventory(r)==[('HELD',7),('HELD',7)]


def test_confirmation_timeout_releases_only_known_simulated_frozen_funds(client):
    r,account,_=reservation(client);a=freeze(r,account)
    with SessionLocal.begin() as s:s.get(Stay,r['hosted_reservation_id']).confirmation_expires_at=datetime.now(timezone.utc)-timedelta(minutes=1)
    assert ops.expire_pending()['expired_count']==1
    assert inventory(r)==[('RELEASED',8),('RELEASED',8)]
    with SessionLocal() as s:assert s.get(Authorization,a['authorization']['authorization_id']).state=='CONTRACT_RELEASED_NOT_ALIPAY'


def test_unknown_funds_keep_inventory_and_block_cancel_and_timeout(client):
    r,account,h=reservation(client);a=freeze(r,account)
    with SessionLocal.begin() as s:
        s.get(Authorization,a['authorization']['authorization_id']).state='UNKNOWN_EXTERNAL_STATE'
        s.get(Stay,r['hosted_reservation_id']).confirmation_expires_at=datetime.now(timezone.utc)-timedelta(minutes=1)
    assert client.post('/v1/direct/reservations/'+r['hosted_reservation_id']+'/cancel',headers=h).status_code==409
    result=ops.expire_pending();assert result['expired_count']==0 and result['payment_reconciliation_required']==1
    assert inventory(r)==[('HELD',7),('HELD',7)]


def test_frozen_authorization_blocks_reschedule_and_capture_until_fulfillment(client):
    r,account,_=reservation(client);a=freeze(r,account)['authorization'];aid=a['authorization_id']
    with pytest.raises(ValueError,match='PAYMENT_ADJUSTMENT_REQUIRED'):
        ops.reschedule(r['hosted_reservation_id'],{'check_in':r['check_in'],'check_out':r['check_out']},'hotel')
    with pytest.raises(ValueError,match='FULFILLMENT_SETTLEMENT_GATE_REQUIRED'):payment.capture(aid,{'mode':'CONTRACT_DRY_RUN'})
    proof={'hotel_fulfillment_evidence':'isolated-test://stay-completed','guest_checkout_reference':'isolated-test://checkout'}
    with pytest.raises(ValueError,match='HOTEL_CONFIRMATION_REQUIRED'):payment.fulfill(aid,proof,'test-hotel')
    ops.action(r['hosted_reservation_id'],{'action':'CONFIRM','hotel_confirmation_reference':'SIM-HOTEL'},'test-hotel')
    with pytest.raises(ValueError,match='COMPLETED_GUEST_STAY_REQUIRED'):payment.fulfill(aid,proof,'test-hotel')
    from go_hotel.services.guest_stay_fulfillment import guest_stay_fulfillment_service as guest
    sid=guest.create(r['hosted_reservation_id'],'hotel')['stay_lifecycle_id']
    guest.identity(sid,{'identity_evidence_hash':'a'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'},'hotel')
    guest.arrive(sid,'hotel');guest.assign_room(sid,{'room_reference':'SIM-101'},'hotel')
    guest.check_in(sid,{'registration_evidence_reference':'test://registration'},'hotel')
    guest.checkout(sid,proof,'hotel');payment.fulfill(aid,proof,'test-hotel')
    first=payment.capture(aid,{'mode':'CONTRACT_DRY_RUN'});assert payment.capture(aid,{'mode':'CONTRACT_DRY_RUN'})==first
    assert first['state']=='CONTRACT_CAPTURED_NOT_ALIPAY_NOT_SETTLED'
    with SessionLocal() as s:
        assert len(s.scalars(select(Event).where(Event.event_type=='CAPTURE_CONTRACT_VALIDATED')).all())==1
        assert s.get(Reservation,r['hosted_reservation_id']).payment_state=='CONTRACT_CAPTURED_NOT_ALIPAY'


def test_simultaneous_checkout_retries_have_one_authorization(client):
    r,account,_=reservation(client)
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(lambda _:freeze(r,account),range(2)))
    assert result[0]==result[1]
    with SessionLocal() as s:assert len(s.scalars(select(Authorization)).all())==1


def test_cancel_racing_checkout_cannot_leave_funds_frozen_for_cancelled_room(client):
    r,account,_=reservation(client)
    def pay():
        try:return freeze(r,account)
        except ValueError:return 'CANCELLED_BEFORE_AUTHORIZATION'
    def cancel():return ops.action(r['hosted_reservation_id'],{'action':'CANCEL'},account,account,True,True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(pay);b=pool.submit(cancel);a.result();b.result()
    assert inventory(r)==[('RELEASED',8),('RELEASED',8)]
    with SessionLocal() as s:assert all(a.state=='CONTRACT_RELEASED_NOT_ALIPAY' for a in s.scalars(select(Authorization)))


def test_reservations_can_be_recovered_by_owner_after_page_reload(client):
    r,_,h=reservation(client)
    result=client.get('/v1/consumer/direct-reservations',headers=h)
    assert result.status_code==200 and result.json()['data']['items'][0]['hosted_reservation_id']==r['hosted_reservation_id']
    other=auth(client,'other-direct@example.com')
    assert client.get('/v1/consumer/direct-reservations',headers=other).json()['data']['items']==[]
    assert client.get('/v1/direct/reservations/'+r['hosted_reservation_id'],headers=other).status_code==404


@pytest.mark.parametrize('condition',['staging','real-rate','expired'])
def test_authorization_rejects_non_simulated_or_expired_order(client,monkeypatch,condition):
    r,account,_=reservation(client)
    if condition=='staging':monkeypatch.setattr(checkout.settings,'app_env','staging')
    else:
        with SessionLocal.begin() as s:
            if condition=='real-rate':s.scalar(select(Variant).where(Variant.hosted_offer_id==r['hosted_offer_id'])).payment_mode='ALIPAY'
            else:s.get(Stay,r['hosted_reservation_id']).confirmation_expires_at=datetime.now(timezone.utc)-timedelta(minutes=1)
    with pytest.raises(ValueError):freeze(r,account)
    with SessionLocal() as s:assert not s.scalars(select(Authorization)).all()
