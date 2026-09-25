from ride_cancellation_fixture import post_ride_order
from tests.attraction_fixtures import quoted_attraction
import pytest
from datetime import date, timedelta
from sqlalchemy import select
from tests.test_sprint3a_flight import auth as flight_auth, create_ticketed
from tests.test_sprint3c_mobility import auth as mobility_auth
from tests.test_sprint3d_attractions import auth as attr_auth
from tests.vertical_transaction_helpers import pay_and_confirm
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightChangeQuoteRow, AttractionChangeQuoteRow, OrderSupplierFulfillmentRow, MobilityRideOrderRow
from go_hotel.flight.service import flight_service
from go_hotel.attractions.service import attraction_service
from go_hotel.mobility.service import mobility_service
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service


def test_flight_old_quote_cannot_execute_after_refund(client):
    h=flight_auth(client,'terminal-flight@example.com'); oid=create_ticketed(client,h)
    q=client.post(f'/v1/flights/orders/{oid}/change-quote',headers=h,json={'new_departure_date':(date.today()+timedelta(days=12)).isoformat()}).json()['data']
    assert client.post(f'/v1/flights/orders/{oid}/refund',headers=h).status_code==200
    r=client.post(f"/v1/flights/orders/{oid}/execute-change/{q['quote_id']}",headers=h)
    assert r.status_code in {404,422}


def test_attraction_expired_quote_fails_closed(client):
    h=attr_auth(client)
    off=client.post('/v1/attractions/search',json={'destination':'东京','visit_date':'2026-09-03'}).json()['data']['items'][0]
    o=client.post('/v1/attractions/orders',headers=h,json=quoted_attraction(client,{'offer_id':off['offer_id'],'visit_date':'2026-09-03','quantity':1})).json()['data']
    pay_and_confirm(client,h,'ATTRACTION_ORDER',o['order_id'],'ATTR-'+o['order_id'][-6:],voucher_code='V-'+o['order_id'][-6:])
    q=client.post(f"/v1/attractions/orders/{o['order_id']}/change-quote",headers=h,json={'new_visit_date':'2026-09-04'}).json()['data']
    with SessionLocal.begin() as s:
        row=s.get(AttractionChangeQuoteRow,q['quote_id']); row.expires_at=row.expires_at-timedelta(days=1)
    r=client.post(f"/v1/attractions/orders/{o['order_id']}/execute-change/{q['quote_id']}",headers=h)
    assert r.status_code in {404,422}


def test_ride_unknown_from_in_progress_restores_in_progress(client):
    h=mobility_auth(client)
    off=client.post('/v1/mobility/rides/search',json={'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-02T10:00:00','currency':'CNY'}).json()['data']['items'][0]
    o=post_ride_order(client,headers=h,body={'offer_id':off['offer_id'],'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-02T10:00:00','currency':'CNY'}).json()['data']
    pay_and_confirm(client,h,'RIDE_ORDER',o['order_id'],'RIDE-'+o['order_id'][-6:])
    assert client.post(f"/v1/mobility/orders/{o['order_id']}/fulfillment",headers=h,json={'action':'START','evidence_reference':'ride-start'}).json()['data']['status']=='IN_PROGRESS'
    x=mobility_service.admin_external_state(o['order_id'],'UNKNOWN_EXTERNAL_STATE','unknown-proof','ops')
    assert x['status']=='UNKNOWN_EXTERNAL_STATE'
    from go_hotel.mobility.ride.recovery_evidence import current_unknown_episode
    with SessionLocal() as s:
        _,episode=current_unknown_episode(s,s.get(MobilityRideOrderRow,o['order_id']))
    y=mobility_service.admin_external_state(o['order_id'],'CONFIRMED','reconcile-proof','ops',episode)
    assert y['status']=='IN_PROGRESS'
    repeat=client.post(f"/v1/mobility/orders/{o['order_id']}/fulfillment",headers=h,json={'action':'START','evidence_reference':'repeat-start'})
    assert repeat.status_code in {404,422}


def test_late_supplier_fact_cannot_resurrect_completed_ride(client):
    h=mobility_auth(client)
    off=client.post('/v1/mobility/rides/search',json={'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-02T10:00:00','currency':'CNY'}).json()['data']['items'][0]
    o=post_ride_order(client,headers=h,body={'offer_id':off['offer_id'],'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-02T10:00:00','currency':'CNY'}).json()['data']
    pay_and_confirm(client,h,'RIDE_ORDER',o['order_id'],'RIDE-'+o['order_id'][-6:])
    client.post(f"/v1/mobility/orders/{o['order_id']}/fulfillment",headers=h,json={'action':'START','evidence_reference':'start'})
    client.post(f"/v1/mobility/orders/{o['order_id']}/fulfillment",headers=h,json={'action':'COMPLETE','evidence_reference':'complete'})
    with SessionLocal() as s:
        f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.business_id==o['order_id']))
        fid=f.order_supplier_fulfillment_id
    with pytest.raises(ValueError,match='TERMINAL_ORDER_SUPPLIER_FACT_REJECTED'):
        order_supplier_fulfillment_service.record_supplier_fact(fid,{'state':'SUPPLIER_CONFIRMED','supplier_confirmation_reference':'LATE','evidence_reference':'late-confirm'})
    with SessionLocal() as s: assert s.get(MobilityRideOrderRow,o['order_id']).status=='COMPLETED'


def test_ride_unknown_can_converge_to_failed(client):
    h=mobility_auth(client)
    off=client.post('/v1/mobility/rides/search',json={'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-02T10:00:00','currency':'CNY'}).json()['data']['items'][0]
    o=post_ride_order(client,headers=h,body={'offer_id':off['offer_id'],'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-02T10:00:00','currency':'CNY'}).json()['data']
    pay_and_confirm(client,h,'RIDE_ORDER',o['order_id'],'RIDE-'+o['order_id'][-6:])
    assert mobility_service.admin_external_state(o['order_id'],'UNKNOWN_EXTERNAL_STATE','unknown-proof','ops')['status']=='UNKNOWN_EXTERNAL_STATE'
    from go_hotel.mobility.ride.recovery_evidence import current_unknown_episode
    with SessionLocal() as s:
        _,episode=current_unknown_episode(s,s.get(MobilityRideOrderRow,o['order_id']))
    assert mobility_service.admin_external_state(o['order_id'],'FAILED','supplier-failed-proof','ops',episode)['status']=='FAILED'


def test_attraction_redeem_evidence_keeps_consumed_credential(client):
    from go_hotel.services.rc20_vertical_evidence import list_vertical_evidence
    h=attr_auth(client)
    off=client.post('/v1/attractions/search',json={'destination':'东京','visit_date':'2026-09-03'}).json()['data']['items'][0]
    o=client.post('/v1/attractions/orders',headers=h,json=quoted_attraction(client,{'offer_id':off['offer_id'],'visit_date':'2026-09-03','quantity':1})).json()['data']
    pay_and_confirm(client,h,'ATTRACTION_ORDER',o['order_id'],'ATTR-'+o['order_id'][-6:],voucher_code='VOUCH-'+o['order_id'][-6:])
    assert client.post(f"/v1/attractions/orders/{o['order_id']}/redeem",headers=h,json={'evidence_reference':'gate-scan'}).status_code==200
    with SessionLocal() as s:
        evidence=list_vertical_evidence(s,'ATTRACTION',o['order_id'])
    row=next(x for x in reversed(evidence) if x['kind']=='VOUCHER_REDEEMED')
    assert row['payload']['voucher_code'].startswith('VOUCH-')
    assert row['payload']['supplier_reference']


def test_same_supplier_fact_replay_does_not_append_events(client):
    from go_hotel.db.models import OrderSupplierFulfillmentEventRow, ConsumerUnifiedLifecycleEventRow, ConsumerUnifiedLifecycleRow
    h=mobility_auth(client)
    off=client.post('/v1/mobility/rides/search',json={'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-02T10:00:00','currency':'CNY'}).json()['data']['items'][0]
    o=post_ride_order(client,headers=h,body={'offer_id':off['offer_id'],'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-02T10:00:00','currency':'CNY'}).json()['data']
    pay_and_confirm(client,h,'RIDE_ORDER',o['order_id'],'RIDE-'+o['order_id'][-6:])
    with SessionLocal() as s:
        f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.business_id==o['order_id']))
        life=s.scalar(select(ConsumerUnifiedLifecycleRow).where(ConsumerUnifiedLifecycleRow.vertical=='RIDE',ConsumerUnifiedLifecycleRow.order_id==o['order_id']))
        before_f=len(s.scalars(select(OrderSupplierFulfillmentEventRow).where(OrderSupplierFulfillmentEventRow.order_supplier_fulfillment_id==f.order_supplier_fulfillment_id)).all())
        before_l=len(s.scalars(select(ConsumerUnifiedLifecycleEventRow).where(ConsumerUnifiedLifecycleEventRow.consumer_unified_lifecycle_id==life.consumer_unified_lifecycle_id)).all())
        fid=f.order_supplier_fulfillment_id; ref=f.supplier_confirmation_reference
    replay=order_supplier_fulfillment_service.record_supplier_fact(fid,{'state':'SUPPLIER_CONFIRMED','supplier_confirmation_reference':ref,'evidence_reference':'replay-proof'})
    assert replay['replayed'] is True
    with SessionLocal() as s:
        after_f=len(s.scalars(select(OrderSupplierFulfillmentEventRow).where(OrderSupplierFulfillmentEventRow.order_supplier_fulfillment_id==fid)).all())
        life=s.scalar(select(ConsumerUnifiedLifecycleRow).where(ConsumerUnifiedLifecycleRow.vertical=='RIDE',ConsumerUnifiedLifecycleRow.order_id==o['order_id']))
        after_l=len(s.scalars(select(ConsumerUnifiedLifecycleEventRow).where(ConsumerUnifiedLifecycleEventRow.consumer_unified_lifecycle_id==life.consumer_unified_lifecycle_id)).all())
    assert (after_f,after_l)==(before_f,before_l)
