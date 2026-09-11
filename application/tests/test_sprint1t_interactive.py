
def login(client,u='supplier_owner',p='change-me-supplier'):
    r=client.post('/v1/auth/login',json={'username':u,'password':p}); assert r.status_code==200, r.text
    return r.json()['data']['access_token']
def h(t): return {'Authorization':f'Bearer {t}'}

def make_order(client):
    s=client.post('/v1/search/hotels',json={'destination':{'city_code':'TYO'},'stay':{'check_in':'2026-09-01','check_out':'2026-09-05'},'occupancy':{'rooms':1,'adults':2,'children':0},'currency':'CNY'}).json()['data']
    off=s['hotels'][0]['best_offer']; pb=client.post(f"/v1/offers/{off['offer_id']}/prebook",json={'currency':'CNY'}).json()['data']
    o=client.post('/v1/orders',headers={'Idempotency-Key':'it-order'},json={'prebook_id':pb['prebook_id'],'account_id':'acct_demo'}).json()['data']
    client.post(f"/v1/orders/{o['order_id']}/payments",headers={'Idempotency-Key':'it-pay'},json={'payment_method_token':'pm_success','amount_minor':o['total_amount_minor'],'currency':'CNY'})
    client.post(f"/internal/v1/orders/{o['order_id']}/confirm")
    return o['order_id']

def test_supplier_order_workbench_is_authenticated_and_scoped(client):
    oid=make_order(client); t=login(client)
    r=client.get(f'/v1/supplier/orders/{oid}/workbench',headers=h(t)); assert r.status_code==200, r.text
    d=r.json()['data']; assert d['order']['order_id']==oid and 'timeline' in d and 'fare_options' in d

def test_admin_interactive_endpoints_require_permissions(client):
    from go_hotel.security.service import identity_service
    identity_service.create_user('trust1t','long-password-trust1t','GO_ADMIN',None,['GO_TRUST'])
    t=login(client,'trust1t','long-password-trust1t')
    assert client.get('/internal/v1/admin/connector-onboardings',headers=h(t)).status_code==403
    assert client.get('/internal/v1/approvals',headers=h(t)).status_code==200

def test_frontend_contains_interactive_workbench_contract(client):
    assert client.get('/supplier-console/').status_code==200
    assert client.get('/go-admin/').status_code==200
    js=client.get('/console-assets/app.js').text
    for marker in ['orderWorkbench','riskWorkbench','judgmentReplay','connectorWorkbench','adminSettlement']:
        assert marker in js
