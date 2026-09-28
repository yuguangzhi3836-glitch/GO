from registration_terms_test_support import register_synthetic_consumer
from datetime import datetime,timezone
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderRow,FlightOrderRow,RailOrderRow,MobilityRideOrderRow,MobilityRentalOrderRow,AttractionOrderRow
from go_hotel.security.service import identity_service

def auth(client):
 r=register_synthetic_consumer(client, json={'email':'journey@example.com','password':'StrongPass123!','display_name':'Journey User'});assert r.status_code==200
 t=client.post('/v1/mobile/auth/login',json={'email':'journey@example.com','password':'StrongPass123!'}).json()['data'];return {'Authorization':'Bearer '+t['access_token']},identity_service.authenticate(t['access_token']).user_id

def seed(uid):
 n=datetime.now(timezone.utc)
 with SessionLocal() as s:
  s.add(OrderRow(order_id='h_jny',prebook_id='p1',hotel_id='go_hotel_tokyo',account_id=uid,total_amount_minor=320000,currency='CNY',status='CONFIRMED',supplier_confirmation_no='HTL88',supplier_id='sup1',version=1,created_at=n,updated_at=n))
  s.add(FlightOrderRow(order_id='f_jny',account_id=uid,prebook_id='fp1',status='CONFIRMED',total_amount_minor=240000,currency='CNY',passengers=[],payment_method_id=None,pnr='PNR88',ticket_numbers=['7810001'],current_itinerary=[{'flight_number':'MU523','origin':'PVG','destination':'NRT'}],created_at=n,updated_at=n))
  s.add(RailOrderRow(order_id='t_jny',account_id=uid,prebook_id='rp1',status='CONFIRMED',total_amount_minor=68000,currency='CNY',passengers=[],payment_method_id=None,booking_reference='JR88',ticket_numbers=['JR-T1'],current_journey={'train_no':'NOZOMI 215','seat_class':'指定席','origin_station':'东京','destination_station':'京都'},created_at=n,updated_at=n))
  s.add(MobilityRideOrderRow(order_id='ride_jny',account_id=uid,status='CONFIRMED',pickup='NRT',dropoff='银座',pickup_at='2026-09-01T14:00:00+09:00',vehicle_class='COMFORT',total_amount_minor=16800,currency='CNY',passengers=[],flight_no='MU523',supplier_reference='R88',created_at=n,updated_at=n))
  s.add(MobilityRentalOrderRow(order_id='car_jny',account_id=uid,status='CONFIRMED',pickup_location='京都站',return_location='京都站',pickup_at='2026-09-04T13:00:00+09:00',return_at='2026-09-06T09:00:00+09:00',vehicle_class='COMPACT',insurance={},mileage={'type':'UNLIMITED'},deposit_minor=300000,total_amount_minor=126000,currency='CNY',drivers=[],supplier_reference='C88',created_at=n,updated_at=n))
  s.add(AttractionOrderRow(order_id='a_jny',account_id=uid,status='CONFIRMED',product_id='skytree',product_name='东京晴空塔',product_type='ATTRACTION',destination='东京',visit_date='2026-09-03',session_time='16:00',ticket_type='ADULT',quantity=2,eligibility={},voucher_type='QR',voucher_code='GOQR88',total_amount_minor=18000,currency='CNY',attendees=[],supplier_reference='A88',created_at=n,updated_at=n));s.commit()

def test_unified_go_trips_six_verticals(client):
 h,uid=auth(client);seed(uid)
 items=[
 {'vertical':'FLIGHT','order_id':'f_jny','starts_at':'2026-09-01T08:30:00+08:00'},
 {'vertical':'RIDE','order_id':'ride_jny','starts_at':'2026-09-01T14:00:00+09:00'},
 {'vertical':'HOTEL','order_id':'h_jny','title':'东京银座静居酒店','starts_at':'2026-09-01T15:00:00+09:00','ends_at':'2026-09-04T10:00:00+09:00'},
 {'vertical':'ATTRACTION','order_id':'a_jny','starts_at':'2026-09-03T16:00:00+09:00'},
 {'vertical':'RAIL','order_id':'t_jny','starts_at':'2026-09-04T10:03:00+09:00'},
 {'vertical':'RENTAL','order_id':'car_jny','starts_at':'2026-09-04T13:00:00+09:00'}]
 r=client.post('/v1/trips/journeys',headers=h,json={'title':'东京 · 京都 6日旅行','destination_summary':'上海 → 东京 → 京都 → 上海','starts_at':'2026-09-01','ends_at':'2026-09-06','items':items});assert r.status_code==200,r.text
 d=r.json()['data'];assert d['item_count']==6;assert set(d['verticals'])=={'FLIGHT','RIDE','HOTEL','ATTRACTION','RAIL','RENTAL'}
 assert [x['vertical'] for x in d['timeline']]==['FLIGHT','RIDE','HOTEL','ATTRACTION','RAIL','RENTAL']
 g=client.get('/v1/trips/journeys/'+d['journey_id'],headers=h);assert g.status_code==200;assert g.json()['data']['timeline'][0]['status']=='CONFIRMED'
 l=client.get('/v1/trips/journeys',headers=h);assert l.status_code==200 and len(l.json()['data']['items'])==1

def test_cross_account_journey_isolation(client):
 h,uid=auth(client);seed(uid);r=client.post('/v1/trips/journeys',headers=h,json={'title':'Private Journey','items':[{'vertical':'HOTEL','order_id':'h_jny'}]}).json()['data']
 register_synthetic_consumer(client, json={'email':'other@example.com','password':'StrongPass123!','display_name':'Other'});t=client.post('/v1/mobile/auth/login',json={'email':'other@example.com','password':'StrongPass123!'}).json()['data'];h2={'Authorization':'Bearer '+t['access_token']}
 assert client.get('/v1/trips/journeys/'+r['journey_id'],headers=h2).status_code==404
