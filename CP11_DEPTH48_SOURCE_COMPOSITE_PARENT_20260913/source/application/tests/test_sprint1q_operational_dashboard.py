from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderRow, RefundRow, SupplierFinancialAccountRow
from go_hotel.security.service import identity_service

def supplier_headers():
    token=identity_service.login('supplier_owner','change-me-supplier')
    return {'Authorization':'Bearer '+token['access_token']}

def admin_headers():
    token=identity_service.login('go_admin','change-me-admin')
    return {'Authorization':'Bearer '+token['access_token']}


def booked_order(client, idem='q'):
    ci=(datetime.now(timezone.utc)+timedelta(days=30)).date().isoformat(); co=(datetime.now(timezone.utc)+timedelta(days=34)).date().isoformat()
    s=client.post('/v1/search/hotels',json={'destination':{'city_code':'TYO'},'stay':{'check_in':ci,'check_out':co},'occupancy':{'rooms':1,'adults':2,'children':0},'currency':'CNY'})
    off=s.json()['data']['hotels'][0]['best_offer']
    pb=client.post(f"/v1/offers/{off['offer_id']}/prebook",json={'currency':'CNY'}).json()['data']
    o=client.post('/v1/orders',headers={'Idempotency-Key':f'ord-q-{idem}'},json={'prebook_id':pb['prebook_id'],'account_id':'acct_demo'}).json()['data']
    client.post(f"/v1/orders/{o['order_id']}/payments",headers={'Idempotency-Key':f'pay-q-{idem}'},json={'payment_method_token':'pm_success','amount_minor':o['total_amount_minor'],'currency':'CNY'})
    client.post(f"/internal/v1/orders/{o['order_id']}/confirm")
    return o


def test_supplier_identity_propagates_to_order_and_supplier_dashboard(client):
    o=booked_order(client,'identity')
    with SessionLocal() as s:
        row=s.get(OrderRow,o['order_id'])
        assert row.supplier_id=='sup_mock'
    d=client.get('/v1/supplier/dashboard',headers=supplier_headers()).json()['data']
    assert d['orders']['CONFIRMED']==1
    assert d['supplier_id']=='sup_mock'


def test_supplier_order_list_is_tenant_scoped(client):
    o=booked_order(client,'scope')
    own=client.get('/v1/supplier/orders',headers=supplier_headers()).json()['data']
    identity_service.create_user('supplier_other','OtherPass123!','SUPPLIER_USER','sup_other',['SUPPLIER_OWNER'])
    other_token=identity_service.login('supplier_other','OtherPass123!')
    other=client.get('/v1/supplier/orders',headers={'Authorization':'Bearer '+other_token['access_token']}).json()['data']
    assert any(x['order_id']==o['order_id'] for x in own['items'])
    assert other['items']==[]


def test_supplier_refund_appears_in_console(client):
    o=booked_order(client,'refund')
    cq=client.post(f"/v1/orders/{o['order_id']}/cancellation-quote").json()['data']
    client.post(f"/v1/orders/{o['order_id']}/cancel",json={'cancellation_quote_id':cq['quote_id']})
    data=client.get('/v1/supplier/refunds',headers=supplier_headers()).json()['data']
    assert data['count']>=1
    assert data['items'][0]['order_id']==o['order_id']


def test_admin_dashboard_and_queues_are_operational_views(client):
    booked_order(client,'admin')
    dash=client.get('/internal/v1/admin/dashboard',headers=admin_headers()).json()['data']
    assert dash['orders']['CONFIRMED']>=1
    assert 'outbox' in dash and 'financial' in dash
    queues=client.get('/internal/v1/admin/queues',headers=admin_headers()).json()['data']
    assert 'risk_review' in queues['queues']
    assert 'connector_health' in queues['queues']


def test_supplier_financial_risk_is_visible(client):
    client.put('/internal/v1/suppliers/sup_mock/financial-account',headers=admin_headers(),json={'settlement_available_minor':1000,'reserve_available_minor':2000,'bank_available_minor':3000,'debit_mandate_active':True})
    d=client.get('/v1/supplier/dashboard',headers=supplier_headers()).json()['data']['financial_risk']
    assert d['settlement_available_minor']==1000
    assert d['reserve_available_minor']==2000
    assert d['debit_mandate_active'] is True
    admin=client.get('/internal/v1/admin/settlement',headers=admin_headers()).json()['data']
    assert any(x['supplier_id']=='sup_mock' for x in admin['items'])
