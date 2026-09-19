from tests.attraction_fixtures import quoted_attraction
from pathlib import Path
from go_hotel.mobility.service import mobility_service
from go_hotel.attractions.service import attraction_service
from tests.vertical_transaction_helpers import pay_and_confirm, confirm_existing_fulfillment


def auth(client,email):
    r=client.post('/v1/consumer/auth/register',json={'email':email,'password':'StrongPass123!','display_name':'RC20 Tester'})
    assert r.status_code==200,r.text
    t=client.post('/v1/mobile/auth/login',json={'email':email,'password':'StrongPass123!'}).json()['data']
    client.cookies.clear()
    return {'Authorization':f"Bearer {t['access_token']}"}


def test_consumer_surface_exposes_all_six_vertical_actions_through_frozen_five_entry_home():
    js=Path('frontend/consumer/app.js').read_text(encoding='utf-8')
    for marker in [
        "showHotelSearch()","showFlightSearch()","showRailSearch()","showRideSearch()","showRentalSearch()","showAttractionSearch()",
        "/v1/flights/orders","/v1/rail/orders","/v1/mobility/rides/orders","/v1/mobility/rentals/orders","/v1/attractions/orders",
        "flightChange","flightRefund","railChange","railRefund","mobilityFulfill","mobilityCancel","attractionRedeem","attractionRefund",
        "证据链",
    ]:
        assert marker in js, marker
    assert "该品类正在按真实供给能力逐步开放" not in js
    assert 'data-home-vertical="MOBILITY"' in js
    assert 'function showHomeMobilityChooser()' in js
    assert 'showRentalSearch()' in js
    assert 'showRideSearch()' in js


def test_ride_state_machine_recovery_illegal_transition_and_evidence(client):
    h=auth(client,'rc20-ride@example.com')
    s=client.post('/v1/mobility/rides/search',json={'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-01T10:00:00','currency':'CNY'})
    off=s.json()['data']['items'][0]
    o=client.post('/v1/mobility/rides/orders',headers=h,json={'offer_id':off['offer_id'],'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-01T10:00:00','currency':'CNY'}).json()['data']
    oid=o['order_id']
    pay_and_confirm(client,h,'RIDE_ORDER',oid,'RIDE-'+oid[-6:])
    bad=client.post(f'/v1/mobility/orders/{oid}/fulfillment',headers=h,json={'action':'COMPLETE','evidence_reference':'bad-order'})
    assert bad.status_code==422
    unknown=mobility_service.admin_external_state(oid,'UNKNOWN_EXTERNAL_STATE','provider-timeout','expert-review')
    assert unknown['status']=='UNKNOWN_EXTERNAL_STATE'
    blocked=client.post(f'/v1/mobility/orders/{oid}/modify',headers=h,json={'new_time':'2026-09-01T11:00:00'})
    assert blocked.status_code==422
    rec=mobility_service.admin_external_state(oid,'CONFIRMED','provider-reconciled','expert-review','provider-timeout')
    assert rec['status']=='CONFIRMED'
    start=client.post(f'/v1/mobility/orders/{oid}/fulfillment',headers=h,json={'action':'START','evidence_reference':'driver-start'})
    assert start.status_code==200 and start.json()['data']['status']=='IN_PROGRESS'
    done=client.post(f'/v1/mobility/orders/{oid}/fulfillment',headers=h,json={'action':'COMPLETE','evidence_reference':'driver-complete'})
    assert done.status_code==200 and done.json()['data']['status']=='COMPLETED'
    detail=client.get(f'/v1/mobility/orders/{oid}',headers=h).json()['data']
    kinds=[x['kind'] for x in detail['evidence']]
    assert kinds==['ORDER_CREATED','SUPPLIER_CONFIRMED','EXTERNAL_STATE_UNKNOWN','RECONCILED_TO_CONFIRMED','FULFILLMENT_START','FULFILLMENT_COMPLETE']
    assert all(detail['evidence'][i]['previous_hash']==('GENESIS' if i==0 else detail['evidence'][i-1]['entry_hash']) for i in range(len(detail['evidence'])))


def test_rental_pickup_return_cancel_rules_and_reconciliation(client):
    h=auth(client,'rc20-rental@example.com')
    s=client.post('/v1/mobility/rentals/search',json={'pickup_location':'NRT','return_location':'NRT','pickup_at':'2026-09-02T09:00:00','return_at':'2026-09-05T09:00:00','currency':'CNY'})
    off=s.json()['data']['items'][0]
    o=client.post('/v1/mobility/rentals/orders',headers=h,json={'offer_id':off['offer_id'],'pickup_location':'NRT','return_location':'NRT','pickup_at':'2026-09-02T09:00:00','return_at':'2026-09-05T09:00:00','currency':'CNY'}).json()['data']
    oid=o['order_id']
    pay_and_confirm(client,h,'RENTAL_ORDER',oid,'RENTAL-'+oid[-6:])
    assert o['insurance'] and o['deposit_minor']>0 and o['mileage']
    mobility_service.admin_external_state(oid,'UNKNOWN_EXTERNAL_STATE','fleet-timeout','expert-review')
    mobility_service.admin_external_state(oid,'CONFIRMED','fleet-confirmed','expert-review','fleet-timeout')
    p=client.post(f'/v1/mobility/orders/{oid}/fulfillment',headers=h,json={'action':'PICKUP','evidence_reference':'rental-pickup'})
    assert p.status_code==200 and p.json()['data']['status']=='IN_PROGRESS'
    assert client.post(f'/v1/mobility/orders/{oid}/cancel',headers=h).status_code==422
    r=client.post(f'/v1/mobility/orders/{oid}/fulfillment',headers=h,json={'action':'RETURN','evidence_reference':'rental-return'})
    assert r.status_code==200 and r.json()['data']['status']=='COMPLETED'
    assert client.post(f'/v1/mobility/orders/{oid}/fulfillment',headers=h,json={'action':'RETURN','evidence_reference':'duplicate'}).status_code==422
    detail=client.get(f'/v1/mobility/orders/{oid}',headers=h).json()['data']
    assert [x['kind'] for x in detail['evidence']][-2:]==['FULFILLMENT_PICKUP','FULFILLMENT_RETURN']


def test_attraction_redemption_unknown_recovery_closed_and_illegal_states(client):
    h=auth(client,'rc20-attr@example.com')
    s=client.post('/v1/attractions/search',json={'destination':'东京','visit_date':'2026-09-03'}).json()['data']['items']
    off=next(x for x in s if x['offer_id']=='tokyo_skytree')
    o=client.post('/v1/attractions/orders',headers=h,json=quoted_attraction(client,{'offer_id':off['offer_id'],'visit_date':'2026-09-03','quantity':1,'attendees':[{'name':'A'}]})).json()['data']
    oid=o['order_id']
    pay_and_confirm(client,h,'ATTRACTION_ORDER',oid,'ATTR-'+oid[-6:],voucher_code='V-'+oid[-6:])
    attraction_service.admin_external_state(oid,'UNKNOWN_EXTERNAL_STATE','supplier-timeout','expert-review')
    assert client.get(f'/v1/attractions/orders/{oid}/refund-quote',headers=h).status_code==422
    attraction_service.admin_external_state(oid,'CONFIRMED','supplier-reconciled','expert-review')
    red=client.post(f'/v1/attractions/orders/{oid}/redeem',headers=h,json={'evidence_reference':'gate-scan'})
    assert red.status_code==200 and red.json()['data']['status']=='FULFILLED'
    assert client.post(f'/v1/attractions/orders/{oid}/redeem',headers=h,json={'evidence_reference':'replay'}).status_code==422
    assert client.post(f'/v1/attractions/orders/{oid}/refund',headers=h).status_code==422
    detail=client.get(f'/v1/attractions/orders/{oid}',headers=h).json()['data']
    assert [x['kind'] for x in detail['evidence']][-1]=='VOUCHER_REDEEMED'


def test_attraction_supplier_closure_blocks_consumer_mutations(client):
    h=auth(client,'rc20-attr-close@example.com')
    o=client.post('/v1/attractions/orders',headers=h,json=quoted_attraction(client,{'offer_id':'tokyo_skytree','visit_date':'2026-09-03','quantity':1})).json()['data']
    pay_and_confirm(client,h,'ATTRACTION_ORDER',o['order_id'],'ATTR-'+o['order_id'][-6:],voucher_code='V-'+o['order_id'][-6:])
    attraction_service.admin_external_state(o['order_id'],'CLOSED_BY_SUPPLIER','closure-notice','expert-review')
    assert client.post(f"/v1/attractions/orders/{o['order_id']}/change-quote",headers=h,json={'new_visit_date':'2026-09-04'}).status_code==422
    assert client.get(f"/v1/attractions/orders/{o['order_id']}/refund-quote",headers=h).status_code==422
    d=client.get(f"/v1/attractions/orders/{o['order_id']}",headers=h).json()['data']
    assert d['status']=='CLOSED_BY_SUPPLIER'
    assert d['evidence'][-1]['kind']=='SUPPLIER_CLOSED'


def _ticketed_flight(client,h):
    s=client.post('/v1/flights/search',json={'origin':'PVG','destination':'NRT','departure_date':'2026-09-01','cabin':'ECONOMY','currency':'CNY'}).json()['data']['items'][0]
    pb=client.post(f"/v1/flights/offers/{s['offer_id']}/prebook").json()['data']
    o=client.post('/v1/flights/orders',headers=h,json={'prebook_id':pb['prebook_id'],'passengers':[{'full_name':'RC20 TEST','type':'ADT'}]}).json()['data']
    co=client.post(f"/v1/flights/orders/{o['order_id']}/checkout",headers=h,json={'payment_method_id':'pm_rc20_engineering_token'}); assert co.status_code==200,co.text
    confirm_existing_fulfillment(client,o['order_id'],'PNR-'+o['order_id'][-6:],['990-'+o['order_id'][-8:]])
    return o['order_id']


def _ticketed_rail(client,h):
    s=client.post('/v1/rail/search',json={'origin_station':'SHA','destination_station':'HZH','travel_date':'2026-09-01','currency':'CNY'}).json()['data']['items'][0]
    pb=client.post(f"/v1/rail/offers/{s['offer_id']}/prebook").json()['data']
    o=client.post('/v1/rail/orders',headers=h,json={'prebook_id':pb['prebook_id'],'passengers':[{'full_name':'RC20 TEST','type':'ADT'}]}).json()['data']
    co=client.post(f"/v1/rail/orders/{o['order_id']}/checkout",headers=h,json={'payment_method_id':'pm_rc20_engineering_token'}); assert co.status_code==200,co.text
    confirm_existing_fulfillment(client,o['order_id'],'RAIL-'+o['order_id'][-6:],['R-'+o['order_id'][-8:]])
    return o['order_id']


def test_flight_unknown_state_reconciliation_and_evidence(client):
    from go_hotel.flight.service import flight_service
    h=auth(client,'rc20-flight-recovery@example.com'); oid=_ticketed_flight(client,h)
    u=flight_service.admin_external_state(oid,'UNKNOWN_EXTERNAL_STATE','ndc-timeout','expert-review')
    assert u['status']=='UNKNOWN_EXTERNAL_STATE'
    assert client.get(f'/v1/flights/orders/{oid}/refund-quote',headers=h).status_code==422
    r=flight_service.admin_external_state(oid,'TICKETED','ndc-reconciled','expert-review')
    assert r['status']=='TICKETED'
    d=client.get(f'/v1/flights/orders/{oid}',headers=h).json()['data']
    assert [x['kind'] for x in d['evidence']][-2:]==['EXTERNAL_STATE_UNKNOWN','RECONCILED_TO_TICKETED']


def test_rail_unknown_state_reconciliation_and_evidence(client):
    from go_hotel.rail.service import rail_service
    h=auth(client,'rc20-rail-recovery@example.com'); oid=_ticketed_rail(client,h)
    u=rail_service.admin_external_state(oid,'UNKNOWN_EXTERNAL_STATE','rail-provider-timeout','expert-review')
    assert u['status']=='UNKNOWN_EXTERNAL_STATE'
    assert client.post(f'/v1/rail/orders/{oid}/change-quote',headers=h,json={'new_travel_date':'2026-09-02'}).status_code==422
    r=rail_service.admin_external_state(oid,'TICKETED','rail-provider-reconciled','expert-review')
    assert r['status']=='TICKETED'
    d=client.get(f'/v1/rail/orders/{oid}',headers=h).json()['data']
    assert [x['kind'] for x in d['evidence']][-2:]==['EXTERNAL_STATE_UNKNOWN','RECONCILED_TO_TICKETED']
