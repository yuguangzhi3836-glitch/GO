from tests.test_depth11_catalog_supplier_remedy import (booked_order,admin_headers,supplier_headers,EVIDENCE,remedy,configure,funding,SessionLocal,OrderRow,select,Plan,Case,Movement,Intent,Root,connector)
from tests.test_sprint3a_flight import auth
from go_hotel.security.service import identity_service
from go_hotel.db.models import ConsumerProfileRow


def data(r):assert r.status_code==200,r.text;return r.json()['data']


def test_api_independent_permission_stale_evidence_and_customer_progress(client):
    h=auth(client,'catalog-remedy-owner@example.com')
    with SessionLocal() as s:owner=s.scalar(select(ConsumerProfileRow).where(ConsumerProfileRow.email=='catalog-remedy-owner@example.com')).user_id
    oid,paid=booked_order(client,'api-flow',account_id=owner)
    supplier=supplier_headers();admin=admin_headers();path=f'/v1/supplier/orders/{oid}/unable-to-fulfill'
    body={'reason_code':'OVERBOOKING','evidence_ids':['unverified-file']}
    assert client.post(path,headers=h,json=body).status_code==403
    c=data(client.post(path,headers=supplier|{'Idempotency-Key':'api-independent'},json=body));assert c['state']=='EVIDENCE_REQUIRED'
    base='/internal/v1/supplier-fault-cases/'+c['case_id']
    assert data(client.get(f'/v1/supplier/orders/{oid}/supplier-cancellation',headers=supplier))['state']=='EVIDENCE_REQUIRED'
    supplier_proof=data(client.post(f'/v1/supplier/orders/{oid}/supplier-cancellation/evidence',headers=supplier,json=EVIDENCE))
    assert supplier_proof['state']=='INDEPENDENT_REVIEW_REQUIRED'
    listing=data(client.get('/internal/v1/supplier-fault/cases',headers=admin));assert listing['items'][0]['case_id']==c['case_id']
    assert client.get('/internal/v1/supplier-fault/cases',headers=h).status_code==403
    from tests.supplier_fixture import admit_trading_supplier
    fixture_owner = identity_service.create_user('other_catalog_supplier','Test-Only-Other123!','SUPPLIER_USER','sup_other',['SUPPLIER_OWNER'])
    admit_trading_supplier('sup_other', fixture_owner)
    other_supplier={'Authorization':'Bearer '+identity_service.login('other_catalog_supplier','Test-Only-Other123!')['access_token']}
    assert client.get(f'/v1/supplier/orders/{oid}/supplier-cancellation',headers=other_supplier).status_code==404
    assert client.post(f'/v1/supplier/orders/{oid}/supplier-cancellation/evidence',headers=other_supplier,json=EVIDENCE).status_code==404
    for forbidden in [h,supplier]:assert client.post(base+'/evidence',headers=forbidden,json=EVIDENCE).status_code==403
    c=data(client.post(base+'/evidence',headers=admin,json=EVIDENCE))
    b={'confirmed_cause':'NO_ROOM','accepted_evidence_ids':c['evidence_ids'],'decision_reference':'test://review','expected_evidence_hash':c['evidence_hash']}
    assert client.post(base+'/review',headers=admin,json=b|{'compensation_amount_minor':999999}).status_code==422
    changed=data(client.post(base+'/evidence',headers=admin,json={**EVIDENCE,'reference':'test://new-file','sha256':'c'*64}))
    stale=client.post(base+'/review',headers=admin,json=b);assert stale.status_code==409 and 'EVIDENCE_CHANGED' in stale.text
    approved=data(client.post(base+'/review',headers=admin,json=b|{'expected_evidence_hash':changed['evidence_hash']}))
    wrong=client.post(base+'/execute',headers=admin,json={'expected_decision_hash':'f'*64});assert wrong.status_code==409
    other=auth(client,'catalog-remedy-other@example.com')
    assert client.post(f'/v1/consumer/orders/{oid}/supplier-cancellation-remedy/retry',headers=other).status_code==404
    detail=data(client.get(f'/v1/consumer/orders/{oid}/detail',headers=h));assert detail['supplier_remedy']['financial_decision_approved']
    for private in ['liability','evidence','requester_id','decision','bank_available_minor']:assert private not in detail['supplier_remedy']
    configure('sup_mock',paid)
    result=data(client.post(f'/v1/consumer/orders/{oid}/supplier-cancellation-remedy/retry',headers=h));assert result['state']=='COMPLETED' and result['compensation']['amount_minor']==paid
    assert connector.cancel_calls==1


def test_service_requester_with_finance_role_cannot_approve_own_supplier_request(client):
    oid,paid=booked_order(client,'mixed-role');admin=admin_headers()
    token=admin['Authorization'].split(' ',1)[1]
    principal=identity_service.authenticate(token)
    c=remedy.request(oid,'sup_mock','OVERBOOKING',[],principal.user_id)
    c=remedy.add_evidence(c['case_id'],EVIDENCE,'evidence-staff')
    body={'confirmed_cause':'NO_ROOM','accepted_evidence_ids':c['evidence_ids'],'decision_reference':'test://review','expected_evidence_hash':c['evidence_hash']}
    rejected=client.post('/internal/v1/supplier-fault-cases/'+c['case_id']+'/review',headers=admin,json=body)
    assert rejected.status_code==409 and 'MAKER_CHECKER' in rejected.text and connector.cancel_calls==0
