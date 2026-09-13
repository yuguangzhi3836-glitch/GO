from datetime import datetime,timezone
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightOrderRow,RailOrderRow,MobilityRideOrderRow,OrderRow
from go_hotel.security.service import identity_service

def auth(client,email='intel@example.com'):
    r=client.post('/v1/consumer/auth/register',json={'email':email,'password':'StrongPass123!','display_name':'Intel User'});assert r.status_code==200
    t=client.post('/v1/mobile/auth/login',json={'email':email,'password':'StrongPass123!'}).json()['data']
    return {'Authorization':'Bearer '+t['access_token']},identity_service.authenticate(t['access_token']).user_id

def seed(uid):
    n=datetime.now(timezone.utc)
    with SessionLocal() as s:
        s.add(FlightOrderRow(order_id='f_dis',account_id=uid,prebook_id='fp',status='CONFIRMED',total_amount_minor=100000,currency='CNY',passengers=[],payment_method_id=None,pnr='PNR1',ticket_numbers=['T1'],current_itinerary=[{'flight_number':'MU523','origin':'PVG','destination':'NRT'}],created_at=n,updated_at=n))
        s.add(MobilityRideOrderRow(order_id='r_dis',account_id=uid,status='CONFIRMED',pickup='NRT',dropoff='Ginza',pickup_at='2026-09-01T14:00:00+09:00',vehicle_class='COMFORT',total_amount_minor=10000,currency='CNY',passengers=[],flight_no='MU523',supplier_reference='R1',created_at=n,updated_at=n))
        s.add(OrderRow(order_id='h_dis',prebook_id='hp',hotel_id='tokyo',account_id=uid,total_amount_minor=200000,currency='CNY',status='CONFIRMED',supplier_confirmation_no='H1',supplier_id='S1',version=1,created_at=n,updated_at=n))
        s.add(RailOrderRow(order_id='t_dis',account_id=uid,prebook_id='rp',status='CONFIRMED',total_amount_minor=50000,currency='CNY',passengers=[],payment_method_id=None,booking_reference='JR1',ticket_numbers=['RT1'],current_journey={'train_no':'N1','seat_class':'RESERVED','origin_station':'Tokyo','destination_station':'Kyoto'},created_at=n,updated_at=n));s.commit()

def make_journey(client,h):
    items=[
      {'vertical':'FLIGHT','order_id':'f_dis','starts_at':'2026-09-01T08:30:00+08:00'},
      {'vertical':'RIDE','order_id':'r_dis','starts_at':'2026-09-01T14:00:00+09:00'},
      {'vertical':'HOTEL','order_id':'h_dis','starts_at':'2026-09-01T15:00:00+09:00'},
      {'vertical':'RAIL','order_id':'t_dis','starts_at':'2026-09-01T16:00:00+09:00'}]
    r=client.post('/v1/trips/journeys',headers=h,json={'title':'Disruption Journey','items':items});assert r.status_code==200
    return r.json()['data']

def test_flight_delay_detects_downstream_impacts_without_auto_mutation(client):
    h,uid=auth(client);seed(uid);j=make_journey(client,h);source=j['timeline'][0]
    r=client.post(f"/v1/trips/journeys/{j['journey_id']}/disruptions/evaluate",headers=h,json={
      'source_item_id':source['item_id'],'event_type':'FLIGHT_DELAY','severity':'HIGH',
      'facts':{'original_arrival_at':'2026-09-01T13:00:00+09:00','estimated_arrival_at':'2026-09-01T15:05:00+09:00','delay_minutes':125}})
    assert r.status_code==200,r.text;d=r.json()['data']
    assert d['auto_mutation_performed'] is False
    types={x['impact_type'] for x in d['impacts']}
    assert 'PICKUP_AT_RISK' in types and 'CHECKIN_CONTEXT_CHANGED' in types and 'CONNECTION_AT_RISK' in types
    assert all(x['recommended_action'].get('auto_execute') is False for x in d['impacts'])
    with SessionLocal() as s:
        assert s.get(FlightOrderRow,'f_dis').status=='CONFIRMED'
        assert s.get(MobilityRideOrderRow,'r_dis').status=='CONFIRMED'
        assert s.get(RailOrderRow,'t_dis').status=='CONFIRMED'

def test_latest_and_acknowledge_and_isolation(client):
    h,uid=auth(client,'intel2@example.com');seed(uid);j=make_journey(client,h)
    e=client.post(f"/v1/trips/journeys/{j['journey_id']}/disruptions/evaluate",headers=h,json={'source_item_id':j['timeline'][0]['item_id'],'event_type':'FLIGHT_DELAY','facts':{'estimated_arrival_at':'2026-09-01T15:05:00+09:00','delay_minutes':95}}).json()['data']
    g=client.get(f"/v1/trips/journeys/{j['journey_id']}/disruptions/latest",headers=h);assert g.status_code==200 and g.json()['data']['advice']['advice_id']==e['advice']['advice_id']
    a=client.post(f"/v1/trips/journeys/{j['journey_id']}/advice/{e['advice']['advice_id']}/acknowledge",headers=h);assert a.status_code==200 and a.json()['data']['status']=='ACKNOWLEDGED'
    h2,_=auth(client,'otherintel@example.com');assert client.get(f"/v1/trips/journeys/{j['journey_id']}/disruptions/latest",headers=h2).status_code==404
