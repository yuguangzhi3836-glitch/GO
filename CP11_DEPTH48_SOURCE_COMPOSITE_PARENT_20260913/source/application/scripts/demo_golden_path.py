from fastapi.testclient import TestClient
from go_hotel.main import app

client = TestClient(app)

search = client.post('/v1/search/hotels', json={
    'destination': {'city_code': 'TYO'},
    'stay': {'check_in': '2026-09-01', 'check_out': '2026-09-05'},
    'currency': 'CNY'
}).json()
offer = search['data']['hotels'][0]['best_offer']
print('1 SEARCH:', offer)

pb = client.post(f"/v1/offers/{offer['offer_id']}/prebook", json={'currency': 'CNY'}).json()['data']
print('2 PREBOOK:', pb)

order = client.post('/v1/orders', headers={'Idempotency-Key': 'demo-order'}, json={
    'prebook_id': pb['prebook_id'], 'account_id': 'acct_demo'
}).json()['data']
print('3 ORDER:', order)

payment = client.post(f"/v1/orders/{order['order_id']}/payments", headers={'Idempotency-Key': 'demo-pay'}, json={
    'payment_method_token': 'pm_success',
    'amount_minor': order['total_amount_minor'],
    'currency': order['currency']
}).json()['data']
print('4 PAYMENT:', payment)

confirmed = client.post(f"/internal/v1/orders/{order['order_id']}/confirm").json()['data']
print('5 CONFIRMED:', confirmed)

events = client.get(f"/internal/v1/orders/{order['order_id']}/events").json()['data']
print('6 EVENTS:', [e['event_type'] for e in events])
