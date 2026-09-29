from registration_terms_test_support import register_synthetic_consumer
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import EventRow, MobileEngagementJobRow, ConsumerNotificationRow
from go_hotel.domain.models import Event, new_id
from go_hotel.repositories.sql import repo
from go_hotel.mobile.orchestration import mobile_engagement
from go_hotel.mobile.push import push_worker


def register_mobile(client,email='native2a@example.com'):
    r=register_synthetic_consumer(client, json={'email':email,'password':'StrongPass123!','display_name':'Native Traveler'})
    assert r.status_code==200,r.text
    t=client.post('/v1/mobile/auth/login',json={'email':email,'password':'StrongPass123!'}).json()['data']
    client.cookies.clear()  # native client stores bearer tokens, not browser cookies
    return {'Authorization':f"Bearer {t['access_token']}"}

def book(client,h):
    client.post('/v1/mobile/devices',headers=h,json={'device_id':'ios-2a','platform':'IOS','push_provider':'APNS','push_token':'token-2a','notifications_enabled':True})
    off=client.post('/v1/search/hotels',json={'destination':{'city_code':'TYO'},'stay':{'check_in':(datetime.now(timezone.utc)+timedelta(days=20)).date().isoformat(),'check_out':(datetime.now(timezone.utc)+timedelta(days=24)).date().isoformat()},'occupancy':{'rooms':1,'adults':2,'children':0},'currency':'CNY'}).json()['data']['hotels'][0]['best_offer']
    pb=client.post(f"/v1/offers/{off['offer_id']}/prebook",json={'currency':'CNY'}).json()['data']
    o=client.post('/v1/consumer/orders',headers=h,json={'prebook_id':pb['prebook_id'],'expected_fare_rule_hash':pb['fare_rule']['offer_rule_hash'],'fare_confirmed':True}).json()['data']
    # create tokenized payment under bearer identity
    pm=client.post('/v1/consumer/wallet/payment-methods/tokenize',headers=h,json={'pan':'4111111111111111','expiry_month':12,'expiry_year':2030,'cvc':'123','make_default':True}).json()['data']
    c=client.post(f"/v1/consumer/orders/{o['order_id']}/secure-checkout",headers=h,json={'payment_method_id':pm['payment_method_id']})
    assert c.status_code==200,c.text
    return o['order_id']

def test_booking_push_deep_link_and_checkin_job(client):
    h=register_mobile(client); oid=book(client,h)
    created=mobile_engagement.ingest_domain_events(); assert created>=1
    jobs=mobile_engagement.jobs(); types={x['notification_type'] for x in jobs}
    assert 'BOOKING_CONFIRMED' in types and 'CHECKIN_REMINDER' in types
    mobile_engagement.process_due(); push_worker.run_once()
    inbox=client.get('/v1/mobile/notifications',headers=h).json()['data']['items']
    booking=[x for x in inbox if x['type']=='BOOKING_CONFIRMED']; assert booking
    assert booking[0]['deep_link']==f'go://trips/order/{oid}'
    assert booking[0]['delivery_status'] in {'SENT','INBOX_ONLY'}

def test_refund_and_compensation_events_become_mobile_notifications(client):
    h=register_mobile(client); oid=book(client,h)
    repo.append_event(Event(new_id('evt'),'REFUND_COMPLETED','HOTEL_ORDER',oid,{'refund_id':'ref_test'}))
    repo.append_event(Event(new_id('evt'),'COMPENSATION_COMPLETED','HOTEL_ORDER',oid,{'amount_minor':1000}))
    mobile_engagement.ingest_domain_events(); mobile_engagement.process_due(); push_worker.run_once()
    items=client.get('/v1/mobile/notifications',headers=h).json()['data']['items']
    types={x['type'] for x in items}
    assert 'REFUND_COMPLETED' in types and 'COMPENSATION_COMPLETED' in types

def test_checkout_review_first_push_then_next_app_open_quick_review_and_no_repeat(client):
    h=register_mobile(client); oid=book(client,h)
    # create immutable fulfillment event in the past so the 4h review invite is immediately due
    past=datetime.now(timezone.utc)-timedelta(hours=5)
    with SessionLocal.begin() as s:
        s.add(EventRow(event_id=new_id('evt'),event_type='FULFILLMENT_COMPLETED',aggregate_type='HOTEL_ORDER',aggregate_id=oid,payload={},occurred_at=past))
    mobile_engagement.ingest_domain_events(); mobile_engagement.process_due(); push_worker.run_once()
    items=client.get('/v1/mobile/notifications',headers=h).json()['data']['items']
    first=[x for x in items if x['type']=='FIRST_REVIEW_INVITE']; assert first
    rid=first[0]['payload']['review_id']; assert first[0]['deep_link']==f'go://reviews/{rid}'
    opened=client.post('/v1/mobile/app-open',headers=h); assert opened.status_code==200
    assert opened.json()['data']['action']=='SHOW_QUICK_REVIEW'
    # 5-star input completes immediately; next open must not interrupt again.
    star=client.post(f'/v1/consumer/reviews/{rid}/star',headers=h,json={'star':5}); assert star.status_code==200
    opened2=client.post('/v1/mobile/app-open',headers=h); assert opened2.json()['data']['action']=='NONE'

def test_native_low_review_requires_structured_tag_and_can_create_risk(client):
    h=register_mobile(client); oid=book(client,h)
    # deterministic eligibility helper retained only for test/staging fixtures
    complete=client.post(f'/internal/v1/demo/orders/{oid}/complete-stay'); rid=complete.json()['data']['review']['review_id']
    client.post(f'/v1/consumer/reviews/{rid}/second-trigger',headers=h)
    assert client.post(f'/v1/consumer/reviews/{rid}/star',headers=h,json={'star':1}).status_code==200
    no_tag=client.post(f'/v1/consumer/reviews/{rid}/complete',headers=h); assert no_tag.status_code==422
    assert client.post(f'/v1/consumer/reviews/{rid}/tags',headers=h,json={'tags':['SERIOUS_HYGIENE']}).status_code==200
    done=client.post(f'/v1/consumer/reviews/{rid}/complete',headers=h); assert done.status_code==200
    assert done.json()['data']['experience_score']>=3.0
    assert done.json()['data']['risk_candidates'][0]['status']=='CANDIDATE'

def test_mobile_fare_wrappers_enforce_consumer_ownership(client):
    h=register_mobile(client); oid=book(client,h)
    q=client.post(f'/v1/mobile/orders/{oid}/cancellation-quote',headers=h); assert q.status_code==200
    # second identity cannot access first user's fare quote
    register_mobile(client,'native2b@example.com')
    t=client.post('/v1/mobile/auth/login',json={'email':'native2b@example.com','password':'StrongPass123!'}).json()['data']
    h2={'Authorization':f"Bearer {t['access_token']}"}
    assert client.post(f'/v1/mobile/orders/{oid}/cancellation-quote',headers=h2).status_code==404
