from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RefundRow, StayCreditRow, ReviewSessionRow
from sqlalchemy import select
from datetime import datetime, timezone, timedelta


def _search(client):
    today=datetime.now(timezone.utc).date()
    r=client.post('/v1/search/hotels',json={"destination":{"city_code":"TYO"},"stay":{"check_in":(today+timedelta(days=20)).isoformat(),"check_out":(today+timedelta(days=24)).isoformat()},"occupancy":{"rooms":1,"adults":2,"children":0},"currency":"CNY"})
    assert r.status_code==200
    return r.json()['data']['hotels'][0]

def _book(client):
    h=_search(client); offer=h['best_offer']
    pb=client.post(f"/v1/offers/{offer['offer_id']}/prebook",json={"currency":"CNY"}).json()['data']
    order=client.post('/v1/orders',json={"prebook_id":pb['prebook_id'],"account_id":"acct_demo"},headers={'Idempotency-Key':'order-x'}).json()['data']
    checkout=client.post(f"/v1/consumer/orders/{order['order_id']}/checkout",json={"payment_method_token":"pm_success"},headers={'Idempotency-Key':'checkout-x'})
    assert checkout.status_code==200, checkout.text
    assert checkout.json()['data']['status']=='CONFIRMED'
    return checkout.json()['data']

def test_consumer_frontend_mount(client):
    r=client.get('/go-app/')
    assert r.status_code==200
    assert '<title>GO 旅行</title>' in r.text
    # Verify the actual mounted assets, not a stale cache-busting timestamp.
    from html.parser import HTMLParser
    class Assets(HTMLParser):
        def __init__(self): super().__init__(); self.urls=[]
        def handle_starttag(self, tag, attrs):
            attrs=dict(attrs)
            if tag == 'script' and attrs.get('src'): self.urls.append(attrs['src'])
            if tag == 'link' and attrs.get('rel') == 'stylesheet': self.urls.append(attrs['href'])
    assets=Assets();assets.feed(r.text)
    assert any(url.startswith('/go-app/app.js?') for url in assets.urls)
    assert any(url.startswith('/go-app/vi-reference-10.css?') for url in assets.urls)
    for url in assets.urls:
        loaded=client.get(url)
        assert loaded.status_code == 200, url
        assert loaded.content, url

def test_consumer_booking_trips_change_cancel_refund(client):
    o=_book(client); oid=o['order_id']
    trips=client.get('/v1/consumer/trips?account_id=acct_demo').json()['data']
    assert any(x['order_id']==oid and x['status']=='CONFIRMED' for x in trips['items'])
    today=datetime.now(timezone.utc).date()
    q=client.post(f'/v1/orders/{oid}/change-quote',json={'new_check_in':(today+timedelta(days=50)).isoformat(),'new_check_out':(today+timedelta(days=54)).isoformat()})
    assert q.status_code==200
    cq=q.json()['data']
    changed=client.post(f'/v1/orders/{oid}/change',json={'change_quote_id':cq['change_quote_id'],'payment_method_token':'pm_success'},headers={'Idempotency-Key':'change-x'})
    assert changed.status_code==200
    canq=client.post(f'/v1/orders/{oid}/cancellation-quote').json()['data']
    cancelled=client.post(f'/v1/orders/{oid}/cancel',json={'cancellation_quote_id':canq['quote_id'],'reason_code':'CHANGE_OF_PLAN'},headers={'Idempotency-Key':'cancel-x'})
    assert cancelled.status_code==200, cancelled.text
    detail=client.get(f'/v1/consumer/orders/{oid}/detail?account_id=acct_demo').json()['data']
    assert detail['order']['status']=='CANCELLED'
    assert detail['refunds']
    assert detail['refunds'][-1]['status']=='COMPLETED'

def test_consumer_stay_credit_and_quick_review(client):
    # Credit path on a confirmed order.
    o=_book(client); oid=o['order_id']
    q=client.post(f'/v1/orders/{oid}/stay-credit-quote').json()['data']
    assert q['scope']=='PROPERTY_ONLY' and q['validity_days']==365
    c=client.post(f'/v1/orders/{oid}/convert-to-stay-credit',headers={'Idempotency-Key':'credit-x'},json={'quote_id':q['quote_id'],'quote_hash':q['quote_hash'],'confirmed':True})
    assert c.status_code==200, c.text
    assert c.json()['data']['status']=='ACTIVE'

    # Separate confirmed order for review path.
    # Unique idempotency keys because the test DB stores them globally.
    h=_search(client); offer=h['best_offer']
    pb=client.post(f"/v1/offers/{offer['offer_id']}/prebook",json={"currency":"CNY"}).json()['data']
    order=client.post('/v1/orders',json={"prebook_id":pb['prebook_id'],"account_id":"acct_demo"},headers={'Idempotency-Key':'order-review'}).json()['data']
    chk=client.post(f"/v1/consumer/orders/{order['order_id']}/checkout",json={"payment_method_token":"pm_success"},headers={'Idempotency-Key':'checkout-review'})
    assert chk.status_code==200
    complete=client.post(f"/internal/v1/demo/orders/{order['order_id']}/complete-stay")
    assert complete.status_code==200
    pending=client.get('/v1/reviews/pending?account_id=acct_demo').json()['data']
    assert pending
    rid=pending[0]['review_id']
    client.post(f'/v1/reviews/{rid}/second-trigger')
    star=client.post(f'/v1/reviews/{rid}/star',json={'star':1},headers={'Idempotency-Key':'review-star-x'})
    assert star.status_code==200
    tags=client.post(f'/v1/reviews/{rid}/tags',json={'tags':['SERIOUS_HYGIENE']})
    assert tags.status_code==200
    done=client.post(f'/v1/reviews/{rid}/complete',headers={'Idempotency-Key':'review-complete-x'})
    assert done.status_code==200
    assert done.json()['data']['experience_score']>=3.0
    assert done.json()['data']['risk_candidates'][0]['status']=='CANDIDATE'
