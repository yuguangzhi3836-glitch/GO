from registration_terms_test_support import register_synthetic_consumer
from datetime import datetime,timezone
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightOrderRow,RailOrderRow,MobilityRideOrderRow,OrderRow,AttractionOrderRow
from go_hotel.security.service import identity_service

def auth(client,email='recovery@example.com'):
    assert register_synthetic_consumer(client, json={'email':email,'password':'StrongPass123!','display_name':'Recovery User'}).status_code==200
    t=client.post('/v1/mobile/auth/login',json={'email':email,'password':'StrongPass123!'}).json()['data']
    return {'Authorization':'Bearer '+t['access_token']},identity_service.authenticate(t['access_token']).user_id

def seed(uid):
    n=datetime.now(timezone.utc)
    with SessionLocal() as s:
        s.add(FlightOrderRow(order_id='fg',account_id=uid,prebook_id='fp',status='CONFIRMED',total_amount_minor=100000,currency='CNY',passengers=[],payment_method_id=None,pnr='P',ticket_numbers=['T'],current_itinerary=[{'flight_number':'MU523','origin':'PVG','destination':'NRT'}],created_at=n,updated_at=n))
        s.add(MobilityRideOrderRow(order_id='rg',account_id=uid,status='CONFIRMED',pickup='NRT',dropoff='Ginza',pickup_at='2026-09-01T14:00:00+09:00',vehicle_class='COMFORT',total_amount_minor=10000,currency='CNY',passengers=[],flight_no='MU523',supplier_reference='R',created_at=n,updated_at=n))
        s.add(OrderRow(order_id='hg',prebook_id='hp',hotel_id='tokyo',account_id=uid,total_amount_minor=200000,currency='CNY',status='CONFIRMED',supplier_confirmation_no='H',supplier_id='S',version=1,created_at=n,updated_at=n))
        s.add(RailOrderRow(order_id='tg',account_id=uid,prebook_id='rp',status='CONFIRMED',total_amount_minor=50000,currency='CNY',passengers=[],payment_method_id=None,booking_reference='JR',ticket_numbers=['RT'],current_journey={'train_no':'N1','seat_class':'RESERVED','origin_station':'Tokyo','destination_station':'Kyoto'},created_at=n,updated_at=n))
        s.add(AttractionOrderRow(order_id='ag',account_id=uid,status='CONFIRMED',product_id='sky',product_name='Skytree',product_type='ATTRACTION',destination='Tokyo',visit_date='2026-09-01',session_time='16:30',ticket_type='ADULT',quantity=2,eligibility={},voucher_type='QR',voucher_code='QR',total_amount_minor=12000,currency='CNY',attendees=[],supplier_reference='A',created_at=n,updated_at=n));s.commit()

def journey(client,h):
    items=[{'vertical':'FLIGHT','order_id':'fg','starts_at':'2026-09-01T08:30:00+08:00'},{'vertical':'RIDE','order_id':'rg','starts_at':'2026-09-01T14:00:00+09:00'},{'vertical':'HOTEL','order_id':'hg','starts_at':'2026-09-01T15:00:00+09:00'},{'vertical':'RAIL','order_id':'tg','starts_at':'2026-09-01T16:00:00+09:00'},{'vertical':'ATTRACTION','order_id':'ag','starts_at':'2026-09-01T16:30:00+09:00'}]
    return client.post('/v1/trips/journeys',headers=h,json={'title':'Recovery Journey','items':items}).json()['data']

def disruption(client,h,j):
    return client.post(f"/v1/trips/journeys/{j['journey_id']}/disruptions/evaluate",headers=h,json={'source_item_id':j['timeline'][0]['item_id'],'event_type':'FLIGHT_DELAY','severity':'HIGH','facts':{'original_arrival_at':'2026-09-01T13:00:00+09:00','estimated_arrival_at':'2026-09-01T15:05:00+09:00','delay_minutes':125}}).json()['data']

def test_builds_multi_vertical_recovery_options_without_auto_mutation(client):
    h,uid=auth(client);seed(uid);j=journey(client,h);d=disruption(client,h,j)
    r=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-plans",headers=h,json={'advice_id':d['advice']['advice_id']});assert r.status_code==200,r.text
    p=r.json()['data']; assert p['auto_mutation_performed'] is False and len(p['options'])>=6
    verts={x['vertical'] for x in p['options']};assert {'RIDE','HOTEL','RAIL','ATTRACTION'}<=verts
    assert all(x['execution_route'] for x in p['options'])

def test_select_is_single_choice_per_impact_and_still_no_execution(client):
    h,uid=auth(client,'recovery2@example.com');seed(uid);j=journey(client,h);d=disruption(client,h,j)
    p=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-plans",headers=h,json={'advice_id':d['advice']['advice_id']}).json()['data']
    picks=[];seen=set()
    for o in p['options']:
        if o['impact_id'] not in seen: picks.append(o['option_id']);seen.add(o['impact_id'])
    r=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-plans/{p['plan_id']}/select",headers=h,json={'option_ids':picks});assert r.status_code==200
    out=r.json()['data'];assert out['status']=='SELECTED' and out['auto_mutation_performed'] is False
    h2,_=auth(client,'recovery-other@example.com');assert client.get(f"/v1/trips/journeys/{j['journey_id']}/recovery-plans/{p['plan_id']}",headers=h2).status_code==404
