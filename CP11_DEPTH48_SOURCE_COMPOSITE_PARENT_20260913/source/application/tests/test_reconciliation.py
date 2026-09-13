def _confirmed(client):
    search=client.post('/v1/search/hotels',json={'destination':{'city_code':'TYO'},'stay':{'check_in':'2026-09-01','check_out':'2026-09-02'},'currency':'CNY'}).json()['data']
    offer=search['hotels'][0]['best_offer']
    pb=client.post(f"/v1/offers/{offer['offer_id']}/prebook",json={'currency':'CNY'}).json()['data']
    order=client.post('/v1/orders',json={'prebook_id':pb['prebook_id'],'account_id':'acct'},headers={'Idempotency-Key':'ord-r'}).json()['data']
    client.post(f"/v1/orders/{order['order_id']}/payments",json={'amount_minor':offer['total_amount_minor'],'currency':'CNY','payment_method_token':'ok'},headers={'Idempotency-Key':'pay-r'})
    return client.post(f"/internal/v1/orders/{order['order_id']}/confirm").json()['data']

def test_reconciliation_matches_confirmed_supplier(client):
    order=_confirmed(client)
    r=client.post('/internal/v1/connectors/reconciliation/run-once?limit=10')
    assert r.status_code==200
    assert r.json()['data']['checked'] >= 1
    assert r.json()['data']['mismatches']==0
