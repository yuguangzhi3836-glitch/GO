from go_hotel.security.service import identity_service
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import AuditEventRow


def login(client,u,p):
    r=client.post('/v1/auth/login',json={'username':u,'password':p}); assert r.status_code==200, r.text
    return r.json()['data']

def h(tok): return {'Authorization':f"Bearer {tok}"}

def test_supplier_dashboard_requires_auth_and_tenant_comes_from_token(client):
    assert client.get('/v1/supplier/dashboard').status_code==401
    t=login(client,'supplier_owner','change-me-supplier')['access_token']
    r=client.get('/v1/supplier/dashboard?supplier_id=sup_other',headers=h(t))
    assert r.status_code==200
    assert r.json()['data']['supplier_id']=='sup_mock'

def test_admin_rbac_separates_finance_from_trust(client):
    identity_service.create_user('finance_admin','long-password-finance','GO_ADMIN',None,['GO_FINANCE'])
    t=login(client,'finance_admin','long-password-finance')['access_token']
    assert client.get('/internal/v1/admin/settlement',headers=h(t)).status_code==200
    assert client.get('/internal/v1/admin/risk-cases',headers=h(t)).status_code==403

def test_refresh_and_session_revocation(client):
    d=login(client,'supplier_owner','change-me-supplier')
    r=client.post('/v1/auth/refresh',json={'refresh_token':d['refresh_token']}); assert r.status_code==200
    access=r.json()['data']['access_token']
    assert client.get('/v1/auth/me',headers=h(access)).status_code==200
    assert client.post('/v1/auth/logout',headers=h(access)).status_code==200
    assert client.get('/v1/auth/me',headers=h(access)).status_code==401

def test_dual_control_requires_distinct_second_admin(client):
    identity_service.create_user('connector_ops','long-password-connector','GO_ADMIN',None,['GO_CONNECTOR'])
    identity_service.create_user('governance_2','long-password-governance','GO_ADMIN',None,['GO_GOVERNANCE'])
    req=login(client,'connector_ops','long-password-connector')['access_token']
    appr=login(client,'governance_2','long-password-governance')['access_token']
    a=client.post('/internal/v1/approvals',headers=h(req),json={'operation_type':'CONNECTOR_ACTIVATION','subject_type':'SUPPLIER_CONNECTOR','subject_id':'onb_test','payload':{}})
    assert a.status_code==200
    aid=a.json()['data']['approval_id']
    b=client.post(f'/internal/v1/approvals/{aid}/approve',headers=h(appr),json={'note':'second control'})
    assert b.status_code==200 and b.json()['data']['status']=='APPROVED'

def test_mutating_authenticated_request_writes_audit(client):
    t=login(client,'supplier_owner','change-me-supplier')['access_token']
    client.post('/v1/auth/logout',headers={**h(t),'X-Request-ID':'req-audit-1'})
    with SessionLocal() as s:
        rows=s.query(AuditEventRow).filter(AuditEventRow.request_id=='req-audit-1').all()
        assert rows and rows[0].action=='HTTP_POST'
