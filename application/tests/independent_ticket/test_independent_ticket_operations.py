"""Independent role-bound runtime probes for ticket operations."""
from uuid import uuid4
import pytest
from go_hotel.core.config import settings
from go_hotel.flight.service import flight_service as flights
from go_hotel.services import ticket_operations as ops
from tests.test_depth48_flight_changes import booked
from tests.test_ticket_operations_runtime import login
from tests.test_depth48_flight_changes import pending

def setup_workflow(client, monkeypatch, receipt_state, unknown_first=False):
    # Role JWTs are real. This local probe does not certify production MFA.
    monkeypatch.setattr(settings, 'mfa_required_for_admin', False)
    owner, order, consumer = booked(client)
    oid = order['order_id']
    if unknown_first:
        flights.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://review-unknown', 'setup-actor')
    operator = login('GO_ORDER_OPS')
    path = f'/internal/v1/admin/ticket-operations/FLIGHT/{oid}'
    for revision, action in enumerate(['REGISTER','CLAIM','RECEIPT']):
        body = {'action':action,'command_id':uuid4().hex,'expected_revision':revision,'note':'independent probe'}
        if action=='RECEIPT':
            body['receipt']={'state':receipt_state, 'evidence_reference':'isolated://review-receipt'}
        response=client.post(path,headers=operator,json=body)
        assert response.status_code==200,response.text
    return owner, oid, path, operator

def test_apply_crash_after_native_commit_is_recoverable(client, monkeypatch):
    owner,oid,path,operator=setup_workflow(client,monkeypatch,'TICKETED',True)
    body={'action':'APPLY','command_id':uuid4().hex,'expected_revision':3,'note':'apply frozen receipt'}
    real=ops.append_vertical_evidence
    def interrupt(s,v,oid,kind,status,payload):
        if kind=='TICKET_OPERATIONS' and payload['action']=='APPLY':
            raise RuntimeError('INDEPENDENT_AFTER_NATIVE_COMMIT')
        return real(s,v,oid,kind,status,payload)
    monkeypatch.setattr(ops,'append_vertical_evidence',interrupt)
    with pytest.raises(RuntimeError,match='INDEPENDENT_AFTER_NATIVE_COMMIT'):
        client.post(path,headers=operator,json=body)
    assert flights.order(owner,oid)['status']=='TICKETED'
    monkeypatch.setattr(ops,'append_vertical_evidence',real)
    response=client.post(path,headers=operator,json=body)
    assert response.status_code==200,response.text
    assert response.json()['data']['workflow']['stage']=='APPLIED'

def test_unknown_receipt_has_followup_resolution_path(client, monkeypatch):
    owner,oid,path,operator=setup_workflow(client,monkeypatch,'UNKNOWN_EXTERNAL_STATE')
    body={'action':'APPLY','command_id':uuid4().hex,'expected_revision':3,'note':'apply unknown receipt'}
    response=client.post(path,headers=operator,json=body)
    assert response.status_code==200,response.text
    assert flights.order(owner,oid)['status']=='UNKNOWN_EXTERNAL_STATE'
    revision=response.json()['data']['workflow']['revision']
    # The existing user-visible action set must permit continued investigation.
    attempts=[]
    for action in ['CLAIM','RECEIPT','REGISTER']:
        body={'action':action,'command_id':uuid4().hex,'expected_revision':revision,'note':'followup receipt has arrived'}
        if action=='RECEIPT':body['receipt']={'state':'TICKETED','evidence_reference':'isolated://confirmed-later'}
        response=client.post(path,headers=operator,json=body)
        attempts.append((action,response.status_code,response.text))
        if response.status_code==200:return
    pytest.fail('No allowed continuation after UNKNOWN receipt: '+repr(attempts))

def test_native_applier_cannot_verify_after_other_operator_resumes_audit(client,monkeypatch):
    monkeypatch.setattr(settings,'mfa_required_for_admin',False)
    owner,order,q,_=pending(client)
    oid=order['order_id'];path=f'/internal/v1/admin/ticket-operations/FLIGHT/{oid}'
    recorder=login('GO_ORDER_OPS');first_applier=login('GO_ORDER_OPS');resumer=login('GO_ORDER_OPS')
    for revision,action in enumerate(['REGISTER','CLAIM','RECEIPT']):
        body={'action':action,'command_id':uuid4().hex,'expected_revision':revision,'note':'independent verification separation'}
        if action=='RECEIPT':body['receipt']={'state':'TICKETED','evidence_reference':'isolated://verify-separation',
            'supplier_reference':'INDPNR','ticket_numbers':['IND-T1','IND-T2'],'quote_id':q['quote_id']}
        response=client.post(path,headers=recorder,json=body)
        assert response.status_code==200,response.text
    real=ops.append_vertical_evidence
    def interrupt(s,v,oid,kind,status,payload):
        if kind=='TICKET_OPERATIONS' and payload['action']=='APPLY':raise RuntimeError('INDEPENDENT_AFTER_NATIVE_COMMIT')
        return real(s,v,oid,kind,status,payload)
    monkeypatch.setattr(ops,'append_vertical_evidence',interrupt)
    with pytest.raises(RuntimeError,match='INDEPENDENT_AFTER_NATIVE_COMMIT'):
        client.post(path,headers=first_applier,json={'action':'APPLY','command_id':uuid4().hex,'expected_revision':3,'note':'original native applier'})
    monkeypatch.setattr(ops,'append_vertical_evidence',real)
    revision=client.get(path,headers=resumer).json()['data']['workflow']['revision']
    response=client.post(path,headers=resumer,json={'action':'APPLY','command_id':uuid4().hex,'expected_revision':revision,'note':'resume original outcome'})
    assert response.status_code==200,response.text
    revision=response.json()['data']['workflow']['revision']
    response=client.post(path,headers=first_applier,json={'action':'VERIFY','command_id':uuid4().hex,'expected_revision':revision,'note':'must not self verify native work'})
    assert response.status_code in {403,409},response.text
    assert response.json()['detail']=='TICKET_OPERATIONS_INDEPENDENT_VERIFIER_REQUIRED'

def test_late_old_apply_never_executes_new_receipt(client,monkeypatch):
    owner,oid,path,first=setup_workflow(client,monkeypatch,'TICKETED',True)
    old={'action':'APPLY','command_id':uuid4().hex,'expected_revision':3,'note':'old apply only'}
    real=ops.append_vertical_evidence
    def interrupt(s,v,oid,kind,status,payload):
        if kind=='TICKET_OPERATIONS' and payload['action']=='APPLY':raise RuntimeError('INDEPENDENT_AFTER_NATIVE_COMMIT')
        return real(s,v,oid,kind,status,payload)
    monkeypatch.setattr(ops,'append_vertical_evidence',interrupt)
    with pytest.raises(RuntimeError,match='INDEPENDENT_AFTER_NATIVE_COMMIT'):
        client.post(path,headers=first,json=old)
    monkeypatch.setattr(ops,'append_vertical_evidence',real)
    second=login('GO_ORDER_OPS')
    revision=client.get(path,headers=second).json()['data']['workflow']['revision']
    for action in ['APPLY','CLAIM','RECEIPT']:
        body={'action':action,'command_id':uuid4().hex,'expected_revision':revision,'note':'new processing cycle'}
        if action=='RECEIPT':body['receipt']={'state':'UNKNOWN_EXTERNAL_STATE','evidence_reference':'isolated://new-uncertainty'}
        response=client.post(path,headers=second,json=body)
        assert response.status_code==200,response.text
        revision=response.json()['data']['workflow']['revision']
    assert flights.order(owner,oid)['status']=='TICKETED'
    client.post(path,headers=first,json=old)
    assert flights.order(owner,oid)['status']=='TICKETED','Old command applied a new receipt'
