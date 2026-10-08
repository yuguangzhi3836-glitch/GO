import pytest
from go_hotel.core.config import settings
from registration_terms_test_support import register_synthetic_consumer


@pytest.fixture(autouse=True)
def stable_synthetic_signing_key(monkeypatch):
    # Registration cookies must be verified with the same test-only key that
    # signed them after register_synthetic_consumer restores its inner patches.
    monkeypatch.setattr(settings, 'jwt_signing_key', 'isolated-registration-test-key-32bytes-only')

def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("go_consumer_csrf")}

def register(client,email="traveler@example.com"):
    r=register_synthetic_consumer(client, json={"email":email,"password":"StrongPass123!","display_name":"GO Traveler"})
    assert r.status_code==200,r.text
    assert r.json()['data']['profile']['go_id'].startswith('GO')
    return r.json()['data']['profile']

def search_offer(client):
    r=client.post('/v1/search/hotels',json={"destination":{"city_code":"TYO"},"stay":{"check_in":"2026-09-01","check_out":"2026-09-05"},"occupancy":{"rooms":1,"adults":2,"children":0},"currency":"CNY"},headers=csrf(client))
    assert r.status_code==200,r.text
    return r.json()['data']['hotels'][0]['best_offer']

def test_register_secure_cookie_go_id_and_session(client):
    p=register(client)
    assert client.cookies.get('go_consumer_access')
    assert client.cookies.get('go_consumer_refresh')
    assert client.cookies.get('go_consumer_csrf')
    me=client.get('/v1/consumer/me')
    assert me.status_code==200
    assert me.json()['data']['go_id']==p['go_id']
    # No tokens are returned in registration JSON.
    assert 'access_token' not in str(p)

def test_traveler_and_payment_tokenization_no_pan_readback(client):
    register(client)
    t=client.post('/v1/consumer/travelers',json={"full_name":"Chen Traveler","date_of_birth":"1990-01-02","nationality":"CHN","document_type":"PASSPORT","document_number":"E12345678","is_primary":True},headers=csrf(client))
    assert t.status_code==200,t.text
    assert t.json()['data']['document_number_masked'].endswith('5678')
    assert 'E12345678' not in t.text
    pm=client.post('/v1/consumer/wallet/payment-methods/tokenize',json={"pan":"4111111111111111","expiry_month":12,"expiry_year":2030,"cvc":"123","make_default":True},headers=csrf(client))
    assert pm.status_code==200,pm.text
    assert pm.json()['data']['last4']=='1111'
    assert '4111111111111111' not in pm.text and '123' not in pm.text
    w=client.get('/v1/consumer/wallet').json()['data']
    assert len(w['payment_methods'])==1 and 'provider_token' not in str(w)

def test_authenticated_order_ownership_and_tokenized_checkout(client):
    register(client)
    pm=client.post('/v1/consumer/wallet/payment-methods/tokenize',json={"pan":"4111111111111111","expiry_month":12,"expiry_year":2030,"cvc":"123","make_default":True},headers=csrf(client)).json()['data']
    off=search_offer(client)
    pb=client.post(f"/v1/offers/{off['offer_id']}/prebook",json={"currency":"CNY"},headers=csrf(client))
    assert pb.status_code==200,pb.text
    order=client.post('/v1/consumer/orders',json={"prebook_id":pb.json()['data']['prebook_id'],"expected_fare_rule_hash":pb.json()['data']['fare_rule']['offer_rule_hash'],"fare_confirmed":True},headers=csrf(client))
    assert order.status_code==200,order.text
    oid=order.json()['data']['order_id']
    checkout=client.post(f'/v1/consumer/orders/{oid}/secure-checkout',json={"payment_method_id":pm['payment_method_id']},headers=csrf(client))
    assert checkout.status_code==200,checkout.text
    assert checkout.json()['data']['status']=='CONFIRMED'
    trips=client.get('/v1/consumer/trips').json()['data']['items']
    assert any(x['order_id']==oid for x in trips)

    # A different GO ID cannot see the first account's order.
    client.post('/v1/consumer/auth/logout',headers=csrf(client))
    register(client,'other@example.com')
    hidden=client.get(f'/v1/consumer/orders/{oid}/detail')
    assert hidden.status_code==404

def test_refresh_rotation_and_logout(client):
    register(client)
    old=client.cookies.get('go_consumer_refresh')
    r=client.post('/v1/consumer/auth/refresh',headers=csrf(client))
    assert r.status_code==200,r.text
    assert client.cookies.get('go_consumer_refresh')!=old
    out=client.post('/v1/consumer/auth/logout',headers=csrf(client))
    assert out.status_code==200
    assert client.get('/v1/consumer/me').status_code==401
