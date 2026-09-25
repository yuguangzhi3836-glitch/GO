from registration_terms_test_support import register_synthetic_consumer
from go_hotel.rail.service import rail_service
from tests.vertical_transaction_helpers import confirm_existing_fulfillment
def auth(client,email='rail@example.com'):
    r=register_synthetic_consumer(client, json={'email':email,'password':'StrongPass123!','display_name':'Rail Traveler'})
    assert r.status_code==200,r.text
    t=client.post('/v1/mobile/auth/login',json={'email':email,'password':'StrongPass123!'}).json()['data']
    client.cookies.clear()
    return {'Authorization':f"Bearer {t['access_token']}"}

def create_ticketed(client,h):
    s=client.post('/v1/rail/search',json={'origin_station':'SHA','destination_station':'HZH','travel_date':'2026-09-01','currency':'CNY'})
    assert s.status_code==200,s.text
    items=s.json()['data']['items']; assert len(items)>=3
    assert items[0]['seat_class']=='SECOND_CLASS'
    pb=client.post(f"/v1/rail/offers/{items[0]['offer_id']}/prebook"); assert pb.status_code==200,pb.text
    order=client.post('/v1/rail/orders',headers=h,json={'prebook_id':pb.json()['data']['prebook_id'],'passengers':[{'full_name':'CHEN TEST','type':'ADT'}]}); assert order.status_code==200,order.text
    oid=order.json()['data']['order_id']
    co=client.post(f'/v1/rail/orders/{oid}/checkout',headers=h,json={'payment_method_id':'pm_test_token'}); assert co.status_code==200,co.text
    assert co.json()['data']['status']=='PAYMENT_CONFIRMED_AWAITING_SUPPLIER'
    confirm_existing_fulfillment(client,oid,'RAIL-'+oid[-6:],['R-'+oid[-8:]])
    final=client.get(f'/v1/rail/orders/{oid}',headers=h).json()['data']
    assert final['status']=='TICKETED' and final['booking_reference'] and final['ticket_numbers']
    return oid

def test_rail_search_to_ticket_and_trip(client):
    h=auth(client); oid=create_ticketed(client,h)
    detail=client.get(f'/v1/rail/orders/{oid}',headers=h); assert detail.status_code==200
    assert detail.json()['data']['journey']['origin_station']=='SHA'
    trips=client.get('/v1/rail/trips',headers=h).json()['data']['items']; assert trips[0]['order_id']==oid
    unified=client.get('/v1/consumer/trips',headers=h).json()['data']['items']; assert any(x.get('vertical')=='RAIL' and x['order_id']==oid for x in unified)

def test_rail_change_reissues_ticket(client):
    h=auth(client,'rail-change@example.com'); oid=create_ticketed(client,h)
    q=client.post(f'/v1/rail/orders/{oid}/change-quote',headers=h,json={'new_travel_date':'2026-09-03','new_seat_class':'SECOND_CLASS'}); assert q.status_code==200,q.text
    data=q.json()['data']; assert data['change_fee_minor']==500
    ex=client.post(f"/v1/rail/orders/{oid}/execute-change/{data['quote_id']}",headers=h); assert ex.status_code==200,ex.text
    assert ex.json()['data']['status']=='UNKNOWN_EXTERNAL_STATE' and ex.json()['data']['ticket_numbers']==[]
    rec=rail_service.admin_external_state(oid,'TICKETED','supplier-change-proof','ops','RAIL-REISSUED',['R-TICKET-REISSUED'])
    assert rec['journey']['travel_date']=='2026-09-03' and rec['ticket_numbers']==['R-TICKET-REISSUED']

def test_rail_refund_tracks_fee_and_original_payment(client):
    h=auth(client,'rail-refund@example.com'); oid=create_ticketed(client,h)
    q=client.get(f'/v1/rail/orders/{oid}/refund-quote',headers=h); assert q.status_code==200
    assert q.json()['data']['refund_to']=='ORIGINAL_PAYMENT_METHOD'
    r=client.post(f'/v1/rail/orders/{oid}/refund',headers=h); assert r.status_code==200,r.text
    assert r.json()['data']['status']=='REFUND_COMPLETED'
    d=client.get(f'/v1/rail/orders/{oid}',headers=h).json()['data']; assert d['status']=='REFUNDED'

def test_cross_account_rail_order_isolation(client):
    h=auth(client,'rail-a@example.com'); oid=create_ticketed(client,h)
    h2=auth(client,'rail-b@example.com')
    assert client.get(f'/v1/rail/orders/{oid}',headers=h2).status_code in {404,422}
