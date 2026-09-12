"""Exercise real route dependencies and stale-review guards, not just services."""
from fastapi import HTTPException
from go_hotel.security.service import identity_service
from tests.test_sprint1n_supplier_compensation import admin_headers,supplier_headers
from tests.test_sprint3a_flight import auth
from tests.test_depth10_hosted_disruption import (datetime,timedelta,timezone,ThreadPoolExecutor,pytest,select,SessionLocal,Disruption,Account,Liability,Compensation,Intent,Mandate,Offer,fault,funding,legacy_finance,booked,credited,approved,start,EVIDENCE,summary,inventory,Reservation,Ledger,Authorization,money)


def data(response):
    assert response.status_code==200,response.text
    return response.json()['data']


def checker_headers():
    identity_service.create_user('isolated_fault_checker','Test-Checker-Only123!','GO_ADMIN',None,['GO_GOVERNANCE'])
    return {'Authorization':'Bearer '+identity_service.login('isolated_fault_checker','Test-Checker-Only123!')['access_token']}


def test_api_scope_independent_evidence_snapshot_and_customer_retry(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch)
    with SessionLocal() as s:hotel=s.get(Offer,r['hosted_offer_id']).hosted_hotel_id
    rid=r['hosted_reservation_id'];base='/internal/v1/hosted-direct';admin=admin_headers();peer=checker_headers()
    candidates=data(client.get(base+'/disruption-candidates',headers=admin))
    assert rid in [x['reservation_id'] for x in candidates['items']]
    for forbidden in [{},h,supplier_headers()]:
        assert client.get(base+'/disruptions',headers=forbidden).status_code in {401,403}
    path=base+f'/hotels/{hotel}/reservations/{rid}/disruptions'
    body={'claimed_cause':'OVERBOOKING','evidence':[EVIDENCE]};key={'Idempotency-Key':'api-fault-request'}
    assert client.post(path,headers=admin,json=body).status_code==422
    assert client.post(path,headers=admin|key,json=body|{'refund_amount_minor':999999}).status_code==422
    c=data(client.post(path,headers=admin|key,json=body));cid=c['case_id'];case=base+'/disruptions/'+cid
    assert data(client.post(path,headers=admin|key,json=body))['case_id']==cid
    assert rid not in [x['reservation_id'] for x in data(client.get(base+'/disruption-candidates',headers=admin))['items']]
    detail=data(client.get(case,headers=peer));assert detail['evidence'][0]['reference']==EVIDENCE['reference']
    assert len(data(client.get(base+'/disruptions',headers=admin))['items'])==1
    review={'confirmed_cause':'NO_ROOM','accepted_evidence_ids':c['evidence_ids'],'decision_reference':'test://independent','expected_evidence_hash':c['evidence_hash']}
    rejected=client.post(case+'/review',headers=admin,json=review);assert rejected.status_code==409 and 'MAKER_CHECKER' in rejected.text
    changed=data(client.post(case+'/evidence',headers=admin,json={**EVIDENCE,'reference':'test://new-evidence','sha256':'b'*64}))
    stale=client.post(case+'/review',headers=peer,json=review);assert stale.status_code==409 and 'EVIDENCE_CHANGED' in stale.text
    approved_case=data(client.post(case+'/review',headers=peer,json=review|{'expected_evidence_hash':changed['evidence_hash']}))
    assert approved_case['confirmed_cause']=='NO_ROOM' and approved_case['financial_decision_approved']
    stale=client.post(case+'/execute',headers=peer,json={'expected_decision_hash':'0'*64});assert stale.status_code==409 and 'DECISION_CHANGED' in stale.text
    outsider=auth(client,'disruption-outsider@example.com')
    assert client.post(f'/v1/direct/reservations/{rid}/disruption/retry',headers=outsider).status_code==409
    assert client.get(case,headers=h).status_code==403
    done=data(client.post(f'/v1/direct/reservations/{rid}/disruption/retry',headers=h));assert done['state']=='COMPLETED'
    assert summary(r)['release_minor']==162000


def test_api_bank_mandate_and_recovery_reject_unscoped_users_and_noninteger_money(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch)
    with SessionLocal() as s:hotel=s.get(Offer,r['hosted_offer_id']).hosted_hotel_id
    base=f'/internal/v1/hosted-direct/hotels/{hotel}';admin=admin_headers()
    body={'currency':'CNY','maximum_per_case_minor':10000,'expires_at':(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),'authority_reference':'test://scoped-signed-mandate','authority_hash':'e'*64}
    for forbidden in [h,supplier_headers()]:
        assert client.post(base+'/fault-mandates',headers=forbidden,json=body).status_code==403
    for value in [True,1.2,'10000']:
        assert client.post(base+'/fault-mandates',headers=admin,json=body|{'maximum_per_case_minor':value}).status_code==422
        assert client.post(base+'/fault-recoveries',headers=admin|{'Idempotency-Key':'receipt'},json={'amount_minor':value,'settlement_reference':'test://receipt'}).status_code==422
    invalid=client.post(base+'/fault-mandates',headers=admin,json=body|{'scope':'ANY_PAYMENT'});assert invalid.status_code==422
    mandate=data(client.post(base+'/fault-mandates',headers=admin,json=body))
    assert mandate['scope']==funding.MANDATE_SCOPE
    assert client.get(base+'/fault-finance',headers=h).status_code==403
    view=data(client.get(base+'/fault-finance',headers=admin));assert view['mandates'][0]['effective']
    assert data(client.post('/internal/v1/hosted-direct/fault-mandates/'+mandate['mandate_id']+'/revoke',headers=admin))['state']=='REVOKED'
    view=data(client.get(base+'/fault-finance',headers=admin));assert not view['mandates'][0]['effective'] and view['mandates'][0]['deactivated_by']
    legacy_finance.configure_supplier_finance(hotel,0,0,0,False)
    receipt={'amount_minor':10000,'settlement_reference':'test://confirmed-isolated-receipt'}
    first=data(client.post(base+'/fault-recoveries',headers=admin|{'Idempotency-Key':'receipt'},json=receipt))
    assert data(client.post(base+'/fault-recoveries',headers=admin|{'Idempotency-Key':'another-key'},json=receipt))==first
    with SessionLocal() as s:assert s.get(Account,hotel).settlement_available_minor==10000
    assert data(client.get(base+'/fault-finance',headers=admin))['recent_recoveries'][0]['recovery_id']==first['recovery_id']
