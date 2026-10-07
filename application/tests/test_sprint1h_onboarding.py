from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HotelExternalIdentityRow
from go_hotel.security.service import identity_service

def admin_headers(username='go_admin',password='change-me-admin'):
    token=identity_service.login(username,password)
    return {'Authorization':'Bearer '+token['access_token']}

def connector_headers():
    identity_service.create_user('connector_ops','ConnectorPass123!','GO_ADMIN',None,['GO_CONNECTOR'])
    return admin_headers('connector_ops','ConnectorPass123!')

def approved_headers(client,operation,onboarding_id):
    requester=admin_headers()
    identity_service.create_user('go_approver','ApproverPass123!','GO_ADMIN',None,['GO_GOVERNANCE'])
    approver=admin_headers('go_approver','ApproverPass123!')
    request=client.post('/internal/v1/approvals',headers=requester,json={'operation_type':operation,'subject_type':'SUPPLIER_CONNECTOR','subject_id':onboarding_id,'payload':{}})
    approval_id=request.json()['data']['approval_id']
    approved=client.post(f'/internal/v1/approvals/{approval_id}/approve',headers=approver,json={'note':'V7 dual control'})
    assert approved.status_code==200
    return requester|{'X-Approval-ID':approval_id}

def test_supplier_connector_onboarding_requires_connector_admin_permission(client):
    create_body={'supplier_id':'sup_sec','connector_id':'conn_mock_hotel','environment':'SANDBOX'}
    assert client.post('/internal/v1/supplier-connectors',json=create_body).status_code==401

    identity_service.create_user('finance_admin_onb','ConnectorDenied123!','GO_ADMIN',None,['GO_FINANCE'])
    finance=admin_headers('finance_admin_onb','ConnectorDenied123!')
    denied=client.post('/internal/v1/supplier-connectors',json=create_body,headers=finance)
    assert denied.status_code==403
    assert denied.json()['detail']=='PERMISSION_DENIED'

def test_supplier_connector_onboarding_golden_path(client):
    headers=connector_headers()
    r=client.post('/internal/v1/supplier-connectors',json={'supplier_id':'sup_001','connector_id':'conn_mock_hotel','environment':'SANDBOX'},headers=headers)
    assert r.status_code==200
    onb=r.json()['data']; oid=onb['onboarding_id']; assert onb['status']=='DRAFT'

    r=client.put(f'/internal/v1/supplier-connectors/{oid}/credentials',json={'credential_reference':'vault://providers/hotel/sup-001'},headers=headers|{'X-Actor-ID':'go_connector_ops'})
    assert r.status_code==200
    meta=r.json()['data']; assert meta['status']=='ACTIVE'; assert meta['reference_only'] is True; assert meta['external_call_executed'] is False
    assert client.get(f'/internal/v1/supplier-connectors/{oid}',headers=headers).json()['data']['status']=='MAPPING_PENDING'

    r=client.post(f'/internal/v1/supplier-connectors/{oid}/property-mappings',json={'external_hotel_id':'mock_ext_001','proposed_hotel_id':'htl_001','external_name':'Mock Tokyo','confidence_bps':10000,'match_method':'CONTRACTED_MAPPING'},headers=headers)
    mapping=r.json()['data']; mid=mapping['mapping_id']; assert mapping['status']=='PROPOSED'
    r=client.post(f'/internal/v1/supplier-connectors/property-mappings/{mid}/review',json={'decision':'APPROVE'},headers=headers|{'X-Actor-ID':'go_mapping_admin'})
    assert r.status_code==200; assert r.json()['data']['status']=='APPROVED'
    assert client.get(f'/internal/v1/supplier-connectors/{oid}',headers=headers).json()['data']['status']=='CERTIFICATION_PENDING'

    r=client.post(f'/internal/v1/supplier-connectors/{oid}/certify',headers=headers|{'X-Actor-ID':'go_certifier'})
    assert r.status_code==200; assert r.json()['data']['passed'] is True
    assert client.get(f'/internal/v1/supplier-connectors/{oid}',headers=headers).json()['data']['status']=='CERTIFIED'

    r=client.post(f'/internal/v1/supplier-connectors/{oid}/activation-request',headers=headers|{'X-Actor-ID':'go_connector_ops'})
    assert r.status_code==200; assert r.json()['data']['status']=='ACTIVATION_PENDING'
    r=client.post(f'/internal/v1/supplier-connectors/{oid}/activate',json={'percent':5},headers=approved_headers(client,'CONNECTOR_ACTIVATION',oid))
    assert r.status_code==200; assert r.json()['data']['status']=='ACTIVE'; assert r.json()['data']['rollout_percent']==5
    r=client.put(f'/internal/v1/supplier-connectors/{oid}/rollout',json={'percent':25},headers=headers|{'X-Actor-ID':'go_governance'})
    assert r.status_code==200; assert r.json()['data']['rollout_percent']==25

    with SessionLocal() as s:
        ident=s.query(HotelExternalIdentityRow).filter_by(connector_id='conn_mock_hotel',external_hotel_id='mock_ext_001').one()
        assert ident.hotel_id=='htl_001'

def test_activation_blocked_without_mapping_and_certification(client):
    headers=connector_headers()
    oid=client.post('/internal/v1/supplier-connectors',json={'supplier_id':'sup_002','connector_id':'conn_mock_hotel'},headers=headers).json()['data']['onboarding_id']
    client.put(f'/internal/v1/supplier-connectors/{oid}/credentials',json={'credential_reference':'vault://providers/hotel/sup-002'},headers=headers)
    r=client.post(f'/internal/v1/supplier-connectors/{oid}/activation-request',headers=headers)
    assert r.status_code==422

def test_credential_rotation_revokes_previous(client):
    headers=connector_headers()
    oid=client.post('/internal/v1/supplier-connectors',json={'supplier_id':'sup_003','connector_id':'conn_mock_hotel'},headers=headers).json()['data']['onboarding_id']
    client.put(f'/internal/v1/supplier-connectors/{oid}/credentials',json={'credential_reference':'vault://providers/hotel/sup-003-v1'},headers=headers)
    client.put(f'/internal/v1/supplier-connectors/{oid}/credentials',json={'credential_reference':'vault://providers/hotel/sup-003-v2'},headers=headers)
    rows=client.get(f'/internal/v1/supplier-connectors/{oid}/credentials',headers=headers).json()['data']
    assert len(rows)==2
    assert sum(1 for r in rows if r['status']=='ACTIVE')==1
    assert all(r['reference_only'] is True for r in rows)
    assert all(r['external_call_executed'] is False for r in rows)

def test_suspend_zeroes_rollout(client):
    headers=connector_headers()
    oid=client.post('/internal/v1/supplier-connectors',json={'supplier_id':'sup_004','connector_id':'conn_mock_hotel'},headers=headers).json()['data']['onboarding_id']
    client.put(f'/internal/v1/supplier-connectors/{oid}/credentials',json={'credential_reference':'vault://providers/hotel/sup-004'},headers=headers)
    mid=client.post(f'/internal/v1/supplier-connectors/{oid}/property-mappings',json={'external_hotel_id':'x1','proposed_hotel_id':'htl_001'},headers=headers).json()['data']['mapping_id']
    client.post(f'/internal/v1/supplier-connectors/property-mappings/{mid}/review',json={'decision':'APPROVE'},headers=headers)
    client.post(f'/internal/v1/supplier-connectors/{oid}/certify',headers=headers)
    client.post(f'/internal/v1/supplier-connectors/{oid}/activation-request',headers=headers)
    client.post(f'/internal/v1/supplier-connectors/{oid}/activate',json={'percent':10},headers=approved_headers(client,'CONNECTOR_ACTIVATION',oid))
    r=client.post(f'/internal/v1/supplier-connectors/{oid}/suspend',json={'reason':'HEALTH_THRESHOLD_BREACH'},headers=approved_headers(client,'CONNECTOR_SUSPENSION',oid))
    assert r.status_code==200; assert r.json()['data']['status']=='SUSPENDED'; assert r.json()['data']['rollout_percent']==0
