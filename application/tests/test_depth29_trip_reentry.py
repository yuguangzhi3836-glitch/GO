from ride_cancellation_fixture import post_ride_order
"""HTTP/SQLite acceptance with synthetic orders; no browser or live payment."""
from datetime import date, timedelta, datetime, timezone

import pytest
from sqlalchemy import event, select, func

from go_hotel.db.session import SessionLocal, engine
from go_hotel.db.models import ConsumerUnifiedLifecycleRow as Life
from go_hotel.services.consumer_trip_index import list_trips
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service
from tests.test_sprint3a_flight import auth
from tests.attraction_fixtures import quoted_attraction


def data(response):
    assert response.status_code == 200, response.text
    return response.json()['data']


def six_orders(client, headers):
    day = (date.today() + timedelta(days=14)).isoformat()
    end = (date.today() + timedelta(days=16)).isoformat()
    person = {'full_name':'ISOLATED TRAVELER', 'type':'ADT'}
    hotel = data(client.post('/v1/search/hotels', json={
        'destination':{'city_code':'TYO'}, 'stay':{'check_in':day,'check_out':end},
        'occupancy':{'rooms':1,'adults':1,'children':0}, 'currency':'CNY'}))['hotels'][0]
    quote = data(client.post(f"/v1/offers/{hotel['best_offer']['offer_id']}/prebook", json={'currency':'CNY'}))
    orders = {'HOTEL': data(client.post('/v1/consumer/orders', headers=headers, json={
        'prebook_id':quote['prebook_id'], 'expected_fare_rule_hash':quote['fare_rule']['offer_rule_hash'],
        'fare_confirmed':True}))}
    for vertical, root, query in (
        ('FLIGHT', '/v1/flights', {'origin':'PVG','destination':'NRT','departure_date':day}),
        ('RAIL', '/v1/rail', {'origin_station':'SHA','destination_station':'HZH','travel_date':day}),
    ):
        offer = data(client.post(root+'/search', json=query))['items'][0]
        quote = data(client.post(root+f"/offers/{offer['offer_id']}/prebook"))
        orders[vertical] = data(client.post(root+'/orders', headers=headers,
            json={'prebook_id':quote['prebook_id'], 'passengers':[person]}))
    for vertical, path, criteria, party in (
        ('RIDE', 'rides', {'pickup':'PVG','dropoff':'Bund','pickup_at':day+'T10:00:00'}, {'passengers':[person]}),
        ('RENTAL', 'rentals', {'pickup_location':'NRT','return_location':'NRT',
            'pickup_at':day+'T09:00:00','return_at':end+'T09:00:00'}, {'drivers':[person]}),
    ):
        offer = data(client.post(f'/v1/mobility/{path}/search', json=criteria))['items'][0]
        body=criteria | party | {'offer_id':offer['offer_id']}
        orders[vertical] = data(post_ride_order(client,headers=headers,body=body) if vertical=='RIDE' else client.post(f'/v1/mobility/{path}/orders', headers=headers,json=body))
    offer = data(client.post('/v1/attractions/search', json={'destination':'东京','visit_date':day}))['items'][0]
    orders['ATTRACTION'] = data(client.post('/v1/attractions/orders', headers=headers,
        json=quoted_attraction(client, {'offer_id':offer['offer_id'],'visit_date':day,
            'quantity':1,'attendees':[person]})))
    return orders


def paths(vertical, order_id):
    prefix = {'HOTEL':'/v1/consumer/orders/', 'FLIGHT':'/v1/flights/orders/',
        'RAIL':'/v1/rail/orders/', 'RIDE':'/v1/mobility/orders/',
        'RENTAL':'/v1/mobility/orders/', 'ATTRACTION':'/v1/attractions/orders/'}[vertical]
    return prefix + order_id + ('/detail' if vertical == 'HOTEL' else '')


def test_six_created_orders_remain_reachable_before_and_after_checkout(client):
    headers = auth(client, 'depth29@example.test')
    orders = six_orders(client, headers)
    rows = data(client.get('/v1/consumer/unified-trips', headers=headers))['items']
    assert len(rows) == 6
    assert {x['vertical'] for x in rows} == set(orders)
    assert all(x['navigation'] and x['navigation']['order_id'] == x['order_id'] for x in rows)
    tracking = data(client.get('/v1/mobility/rides/orders/'+orders['RIDE']['order_id']+'/flight-tracking', headers=headers))
    assert tracking['order_id'] == orders['RIDE']['order_id']
    assert tracking['confirmed_pickup_at'] == orders['RIDE']['pickup_at']
    assert tracking['data_mode'] == 'SIMULATION'
    for vertical, order in orders.items():
        oid = order['order_id']
        data(client.get(paths(vertical, oid), headers=headers))
        confirmation = {'mode':'CONTRACT_SIMULATOR', 'expected_amount_minor':order['total_amount_minor'],
            'currency':order['currency']}
        checkout = f'/v1/consumer/checkout/{vertical}/{oid}'
        h = headers | {'Idempotency-Key':'depth29-'+oid}
        bad = client.post(checkout, headers=h, json=confirmation | {'expected_amount_minor':order['total_amount_minor']+1})
        assert bad.status_code == 409
        paid = data(client.post(checkout, headers=h, json=confirmation))
        assert paid['external_live'] is False and paid['data_mode'] == 'SIMULATION'
        assert data(client.post(checkout, headers=h, json=confirmation)) == paid
        updated = data(client.get('/v1/consumer/unified-trips', headers=headers))['items']
        assert len(updated) == 6  # Native and projected identities must not duplicate.
        current = next(x for x in updated if x['vertical'] == vertical)
        assert current['native_status'] in {'CONFIRMED','TICKETED'}

    other = auth(client, 'depth29-other@example.test')
    assert data(client.get('/v1/consumer/unified-trips', headers=other))['items'] == []
    for vertical, order in orders.items():
        assert client.get(paths(vertical, order['order_id']), headers=other).status_code in {403,404}
    assert client.get('/v1/consumer/unified-trips').status_code == 401


def test_hosted_reservation_uses_owner_binding_and_direct_navigation(client):
    from tests.test_depth06_direct_checkout import reservation
    row, account, headers = reservation(client)
    items = data(client.get('/v1/consumer/unified-trips', headers=headers))['items']
    item = next(x for x in items if x['order_id'] == row['hosted_reservation_id'])
    assert item['navigation'] == {'kind':'HOTEL_DIRECT','order_id':row['hosted_reservation_id']}
    assert item['payment_state'] == row['payment_state']
    data(client.get('/v1/direct/reservations/'+item['order_id'], headers=headers))
    assert list_trips('not-the-owner') == []


def test_trip_reads_do_not_write_or_turn_injected_urls_into_navigation(client):
    headers = auth(client, 'depth29-read@example.test')
    account = data(client.get('/v1/consumer/me', headers=headers))['user_id']
    consumer_unified_lifecycle_service.project({'account_id':account, 'vertical':'HOTEL',
        'order_id':'invented', 'title':'Claim without canonical order', 'lifecycle_state':'CONFIRMED',
        'payment_state':'PAID', 'refund_state':'NONE', 'source_updated_at':datetime.now(timezone.utc).isoformat(),
        'evidence_reference':'isolated://claim', 'facts':{'detail_url':'https://untrusted.example/order'}})
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in {'INSERT','UPDATE','DELETE','REPLACE'}:
            writes.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        for _ in range(2):
            items = list_trips(account)
            assert len(items) == 1 and items[0]['navigation'] is None
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert writes == []


def test_stale_lifecycle_does_not_mask_new_native_state_or_infer_payment(client):
    from tests.test_sprint3a_flight import create_ticketed
    from go_hotel.db.models import FlightOrderRow
    headers = auth(client, 'depth29-stale@example.test')
    oid = create_ticketed(client, headers)
    with SessionLocal.begin() as session:
        order = session.get(FlightOrderRow, oid)
        order.status = 'UNKNOWN_EXTERNAL_STATE'
        order.updated_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    item = data(client.get('/v1/consumer/unified-trips', headers=headers))['items'][0]
    assert item['native_status'] == 'UNKNOWN_EXTERNAL_STATE'
    assert item['lifecycle_state'] == 'UNKNOWN_EXTERNAL_STATE'
    assert not item['projection_current']
    assert item['payment_state'] == item['refund_state'] == 'UNKNOWN'
    assert item['navigation']['kind'] == 'FLIGHT'


def test_trip_read_cannot_bypass_existing_production_truth_gate(client, monkeypatch):
    from tests.test_sprint3a_flight import create_ticketed
    from go_hotel.core.config import settings
    headers = auth(client, 'depth29-production@example.test')
    create_ticketed(client, headers)
    monkeypatch.setattr(settings, 'app_env', 'production')
    response = client.get('/v1/consumer/unified-trips', headers=headers)
    assert response.status_code == 503
    assert 'FLIGHT_PROVIDER_TRUTH_REQUIRED' in response.text
