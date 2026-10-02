from datetime import date, timedelta
from go_hotel.flight.service import flight_service
from tests.vertical_transaction_helpers import confirm_existing_fulfillment
def auth(client,email='flight@example.com'):
    # Existing-account fixture for transaction tests. Signup admission has its
    # own suite; shipped draft terms must remain closed in this combined tree.
    from go_hotel.consumer.service import consumer_service
    consumer_service.register(email,'StrongPass123!','Flight Traveler')
    t=client.post('/v1/mobile/auth/login',json={'email':email,'password':'StrongPass123!'}).json()['data']
    client.cookies.clear()
    return {'Authorization':f"Bearer {t['access_token']}"}

def create_ticketed(client,h):
    s=client.post('/v1/flights/search',json={'origin':'PVG','destination':'NRT','departure_date':'2026-09-01','cabin':'ECONOMY','currency':'CNY'})
    assert s.status_code==200,s.text
    items=s.json()['data']['items']; assert len(items)>=3
    assert items[0]['baggage']['checked_bag_kg']==23
    pb=client.post(f"/v1/flights/offers/{items[0]['offer_id']}/prebook"); assert pb.status_code==200,pb.text
    order=client.post('/v1/flights/orders',headers=h,json={'prebook_id':pb.json()['data']['prebook_id'],'passengers':[{'full_name':'CHEN TEST','type':'ADT'}]}); assert order.status_code==200,order.text
    oid=order.json()['data']['order_id']
    co=client.post(f'/v1/flights/orders/{oid}/checkout',headers=h,json={'payment_method_id':'pm_test_token'}); assert co.status_code==200,co.text
    assert co.json()['data']['status']=='PAYMENT_CONFIRMED_AWAITING_SUPPLIER'
    confirm_existing_fulfillment(client,oid,'PNR-'+oid[-6:],['990-'+oid[-8:]])
    final=client.get(f'/v1/flights/orders/{oid}',headers=h).json()['data']
    assert final['status']=='TICKETED' and final['pnr'] and final['ticket_numbers']
    return oid

def test_flight_search_to_ticket_and_trip(client):
    h=auth(client); oid=create_ticketed(client,h)
    detail=client.get(f'/v1/flights/orders/{oid}',headers=h); assert detail.status_code==200
    assert detail.json()['data']['itinerary'][0]['origin']=='PVG'
    trips=client.get('/v1/flights/trips',headers=h).json()['data']['items']; assert trips[0]['order_id']==oid

def test_flight_change_reissues_ticket(client):
    h=auth(client); oid=create_ticketed(client,h)
    q=client.post(f'/v1/flights/orders/{oid}/change-quote',headers=h,json={'new_departure_date':(date.today()+timedelta(days=12)).isoformat()}); assert q.status_code==200,q.text
    data=q.json()['data']; assert data['fare_difference_minor']==30000 and data['change_fee_minor']==10000
    ex=client.post(f"/v1/flights/orders/{oid}/execute-change/{data['quote_id']}",headers=h); assert ex.status_code==200,ex.text
    assert ex.json()['data']['status']=='UNKNOWN_EXTERNAL_STATE' and ex.json()['data']['ticket_numbers']==[]
    rec=flight_service.admin_external_state(oid,'TICKETED','supplier-change-proof','ops','PNR-REISSUED',['990-REISSUED-REAL'])
    assert rec['itinerary'][0]['departure_date']==data['new_departure_date']
    assert rec['ticket_numbers']==['990-REISSUED-REAL']

def test_flight_refund_tracks_fee_and_original_payment(client):
    h=auth(client); oid=create_ticketed(client,h)
    q=client.get(f'/v1/flights/orders/{oid}/refund-quote',headers=h); assert q.status_code==200
    assert q.json()['data']['refund_to']=='ORIGINAL_PAYMENT_METHOD'
    r=client.post(f'/v1/flights/orders/{oid}/refund',headers=h); assert r.status_code==200,r.text
    assert r.json()['data']['status']=='REFUND_COMPLETED'
    d=client.get(f'/v1/flights/orders/{oid}',headers=h).json()['data']; assert d['status']=='REFUNDED'

def test_cross_account_flight_order_isolation(client):
    h=auth(client,'flight-a@example.com'); oid=create_ticketed(client,h)
    h2=auth(client,'flight-b@example.com')
    assert client.get(f'/v1/flights/orders/{oid}',headers=h2).status_code in {404,422}
