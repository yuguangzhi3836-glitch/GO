"""Current-build boundary cases; synthetic rooms and payments never imply live acceptance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import pytest
from tests.hosted_review_support import legacy_publication,fare_hash
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (HostedDirectHotelRow, HostedDirectReservationRow,
    HostedDirectRateVariantRow, HostedInventoryDayRow, HostedReservationStayRow)
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services.official_hotel_catalog import configure_official_hotel, seed_demo_inventory
from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops


def inventory():
    h=booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'aoluguya-harbin',
        'contact':{'pets':'UNVERIFIED POLICY','deposit':{'amount':999},'inventory_data_mode':'SIMULATION'}},'test')
    configure_official_hotel()
    start=date.today()+timedelta(days=2)
    seed_demo_inventory(h['hosted_hotel_id'],start.isoformat(),5)
    with SessionLocal() as s:
        v=s.scalar(select(HostedDirectRateVariantRow))
        offer,pool=v.hosted_offer_id,v.inventory_pool_id
    legacy_publication(h['hosted_hotel_id'])
    body={'hosted_offer_id':offer,'expected_fare_rule_hash':fare_hash(offer),'guest_name':'TEST GUEST','guest_contact':'13800000000',
        'check_in':start.isoformat(),'check_out':(start+timedelta(days=2)).isoformat(),'adults':1,'children':0}
    return h['hosted_hotel_id'],pool,body


def available(pool):
    with SessionLocal() as s:
        return {r.stay_date:r.capacity_available for r in s.scalars(select(HostedInventoryDayRow).where(
            HostedInventoryDayRow.inventory_pool_id==pool)).all()}


def test_official_catalog_does_not_relabel_unverified_policies():
    hid,_,_=inventory()
    with SessionLocal() as s:
        contact=s.get(HostedDirectHotelRow,hid).contact_json
        assert contact['official_room_count']==17 and contact['inventory_data_mode']=='SIMULATION'
        assert 'pets' not in contact and 'deposit' not in contact


def test_last_room_concurrency_and_duplicate_cancel_preserve_stock():
    _,pool,b=inventory()
    for day in list(available(pool))[:2]:
        ops.set_inventory_day(pool,day,{'sale_state':'OPEN','capacity_total':1,'capacity_available':1})
    def reserve(i):
        try:return ops.reserve('aoluguya-harbin',b,f'concurrent-{i}',actor='owner')
        except ValueError as e:return str(e)
    with ThreadPoolExecutor(max_workers=4) as executor:results=list(executor.map(reserve,range(4)))
    successful=[r for r in results if isinstance(r,dict)]
    assert len(successful)==1 and results.count('NO_DATED_INVENTORY')==3
    rid=successful[0]['hosted_reservation_id']
    ops.action(rid,{'action':'CANCEL'},'owner',expected_owner='owner',pending_only=True)
    once=available(pool)
    ops.action(rid,{'action':'CANCEL'},'owner',expected_owner='owner',pending_only=True)
    assert available(pool)==once and once[b['check_in']]==1


def test_last_night_failure_and_changed_price_roll_back_all_inventory():
    _,pool,b=inventory();original=available(pool)
    with pytest.raises(ValueError,match='PRICE_CHANGED'):
        ops.reserve('aoluguya-harbin',{**b,'expected_total_minor':1},'wrong-price')
    assert available(pool)==original
    last=(date.fromisoformat(b['check_out'])-timedelta(days=1)).isoformat()
    ops.set_inventory_day(pool,last,{'sale_state':'OPEN','capacity_available':0})
    before=available(pool)
    with pytest.raises(ValueError,match='NO_DATED_INVENTORY'):ops.reserve('aoluguya-harbin',b,'last-night')
    assert available(pool)==before


def test_held_stock_owner_and_payment_uncertainty_are_protected():
    _,pool,b=inventory();r=ops.reserve('aoluguya-harbin',b,'payment-held',actor='owner');rid=r['hosted_reservation_id']
    with pytest.raises(ValueError,match='CAPACITY_CONFLICTS'):
        ops.set_inventory_day(pool,b['check_in'],{'sale_state':'OPEN','capacity_total':8,'capacity_available':8})
    with pytest.raises(ValueError,match='NOT_FOUND'):
        ops.action(rid,{'action':'CANCEL'},'other',expected_owner='other',pending_only=True)
    with SessionLocal.begin() as s:
        s.get(HostedDirectReservationRow,rid).payment_state='PROVIDER_RESULT_UNKNOWN'
        s.get(HostedReservationStayRow,rid).confirmation_expires_at=datetime.now(timezone.utc)-timedelta(minutes=1)
    before=available(pool)
    with pytest.raises(ValueError,match='PAYMENT_RELEASE_OR_REFUND_REQUIRED'):
        ops.action(rid,{'action':'CANCEL'},'owner',expected_owner='owner')
    result=ops.expire_pending()
    assert result['expired_count']==0 and result['payment_reconciliation_required']==1
    assert available(pool)==before
    with pytest.raises(ValueError,match='CONFIRMATION_EXPIRED'):
        ops.reschedule(rid,{'check_in':b['check_in'],'check_out':b['check_out']},'owner')


def test_failed_reschedule_restores_original_nights():
    _,pool,b=inventory();r=ops.reserve('aoluguya-harbin',b,'reschedule')
    target=date.fromisoformat(b['check_out'])
    ops.set_inventory_day(pool,target.isoformat(),{'sale_state':'OPEN','capacity_available':0})
    before=available(pool)
    with pytest.raises(ValueError,match='NO_DATED_INVENTORY'):
        ops.reschedule(r['hosted_reservation_id'],{'check_in':target.isoformat(),'check_out':(target+timedelta(days=1)).isoformat()},'owner')
    assert available(pool)==before
    with SessionLocal() as s:assert s.get(HostedDirectReservationRow,r['hosted_reservation_id']).check_in==b['check_in']


def test_rental_duration_pricing_and_invalid_periods():
    from go_hotel.mobility.rental.service import RentalService,rental_days
    service=RentalService()
    for end,days in [('2026-10-02T10:00:00',1),('2026-10-02T10:00:01',2),('2026-10-08T10:00:00',7)]:
        offer=service.search('NRT','NRT','2026-10-01T10:00:00',end)[0]
        assert offer['total_amount_minor']==42000*days
        order=service.create('owner',{'offer_id':offer['offer_id'],'pickup_location':'NRT','return_location':'NRT',
            'pickup_at':'2026-10-01T10:00:00','return_at':end})
        assert order['total_amount_minor']==offer['total_amount_minor']
    for start,end in [('bad','bad'),('2026-10-01','2026-10-01'),('2026-10-02','2026-10-01'),
        ('2026-10-01T10:00:00Z','2026-10-02T10:00:00')]:
        with pytest.raises(ValueError):rental_days(start,end)


def test_production_legacy_routes_require_identity_and_cannot_spoof_owner(client,monkeypatch):
    from test_master03_closure import book_all
    headers,orders=book_all(client);rid=orders['HOTEL']['order_id']
    monkeypatch.setattr(settings,'app_env','production')
    assert client.get(f'/v1/orders/{rid}').status_code==401
    assert client.get(f'/v1/orders/{rid}',headers={'Authorization':'Bearer invalid'}).status_code==401
    response=client.post('/v1/orders',headers=headers,json={'account_id':'another-owner','prebook_id':'none'})
    assert response.status_code==403,response.text
    from go_hotel.consumer.service import consumer_service
    consumer_service.register('other-boundary@example.test','StrongPass123!','OTHER',None)
    token=client.post('/v1/mobile/auth/login',json={'email':'other-boundary@example.test','password':'StrongPass123!'}).json()['data']['access_token']
    other={'Authorization':'Bearer '+token}
    assert client.get(f'/v1/orders/{rid}',headers=other).status_code==404
    assert client.post(f'/v1/orders/{rid}/cancel',headers=other,json={'cancellation_quote_id':'none'}).status_code==404
