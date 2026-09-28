from uuid import uuid4
import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal, engine
from go_hotel.db.models import (OrderSupplierFulfillmentRow, JourneyRecoveryEvidenceChainRow,
    AttractionOrderRow, OmnichannelLedgerEntryRow)
from go_hotel.core.config import settings
from go_hotel.services import ticket_operations
from tests.test_depth21_refund_recovery import booked
from tests.test_ticket_operations_runtime import login
from tests.test_rental_attraction_preinventory import money


@pytest.fixture
def workspace(client,monkeypatch):
    monkeypatch.setattr(settings,'mfa_required_for_admin',False)
    svc,owner,oid=booked('ATTRACTION')
    with SessionLocal() as s:
        sid=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.business_id==oid)).supplier_id
    return {'client':client,'svc':svc,'owner':owner,'oid':oid,
        'supplier':login('SUPPLIER_OWNER',sid),'readonly':login('READ_ONLY',sid),
        'foreign':login('SUPPLIER_OWNER','foreign-isolated'),'operator':login('GO_ORDER_OPS'),
        'verifier':login('GO_ORDER_OPS'),'admin_readonly':login('GO_READ_ONLY'),
        'sp':f'/v1/supplier/ticket-operations/ATTRACTION/{oid}',
        'ap':f'/internal/v1/admin/ticket-operations/ATTRACTION/{oid}'}


def command(w,action,actor='operator',receipt=None,status=200,body=None):
    path=w['sp'] if actor in {'supplier','readonly','foreign'} else w['ap']
    if body is None:
        view=w['client'].get(w['ap'],headers=w['operator']);assert view.status_code==200,view.text
        body={'action':action,'command_id':uuid4().hex,'expected_revision':view.json()['data']['workflow']['revision'],
              'note':'isolated normal role operation'}
        if receipt is not None:body['receipt']=receipt
    r=w['client'].post(path,headers=w[actor],json=body)
    assert r.status_code==status,r.text
    return body,r


def prepare(w,state='CONFIRMED'):
    receipt={'state':state,'evidence_reference':'isolated://attraction-receipt'}
    if state=='CONFIRMED':
        q=w['svc'].change_quote(w['owner'],w['oid'],'2026-09-16','16:00')
        w['svc'].execute_change(w['owner'],w['oid'],q['quote_id'])
        receipt.update(quote_id=q['quote_id'],supplier_reference='ATTR-OPS',voucher_code='VOUCHER-OPS')
    command(w,'REGISTER','supplier');command(w,'CLAIM','supplier');command(w,'RECEIPT','supplier',receipt)
    return receipt


def test_normal_change_supplier_operator_independent_verifier(workspace):
    w=workspace;prepare(w);before=money()
    command(w,'APPLY','supplier',status=409)
    body,r=command(w,'APPLY');assert r.json()['data']['workflow']['stage']=='APPLIED'
    _,replay=command(w,'APPLY',body=body);assert replay.json()['data']['idempotent_replay']
    current=w['svc'].get(w['owner'],w['oid'])
    assert current['visit_date']=='2026-09-16' and current['voucher_code']=='VOUCHER-OPS'
    assert money()==before
    command(w,'VERIFY',status=409)
    command(w,'VERIFY','verifier');command(w,'FOLLOW_UP')
    view=w['client'].get(w['sp'],headers=w['supplier']).json()['data']
    assert view['workflow']['stage']=='CLOSED' and view['order']['money_summary']['verified']
    assert view['order']['money_summary']['net_minor']==36000
    assert 'evidence' not in view['order'] and 'account_id' not in view['order']


def test_closure_cannot_close_before_verified_original_refund(workspace):
    w=workspace;prepare(w,'CLOSED_BY_SUPPLIER');command(w,'APPLY')
    before=money();command(w,'VERIFY','verifier',status=409);assert money()==before
    q=w['svc'].refund_quote(w['owner'],w['oid'])
    assert q['reason']=='SUPPLIER_CLOSED' and q['refund_amount_minor']==36000
    w['svc'].refund(w['owner'],w['oid'],q['quote_hash'])
    command(w,'VERIFY','verifier');command(w,'FOLLOW_UP')
    view=w['client'].get(w['sp'],headers=w['supplier']).json()['data']
    assert view['order']['status']=='REFUNDED' and view['workflow']['stage']=='CLOSED'
    assert view['order']['money_summary']['net_minor']==0


def test_role_and_tenant_denials_have_no_money_or_workflow_side_effects(workspace):
    w=workspace;before=money()
    assert w['client'].get(w['sp'],headers=w['foreign']).status_code==404
    command(w,'REGISTER','foreign',status=404)
    command(w,'REGISTER','readonly',status=403)
    command(w,'REGISTER','admin_readonly',status=403)
    assert money()==before
    assert w['client'].get(w['ap'],headers=w['operator']).json()['data']['workflow']['revision']==0


@pytest.mark.parametrize('receipt',[
    {'state':'TICKETED','evidence_reference':'isolated://wrong-kind'},
    {'state':'CONFIRMED','evidence_reference':'isolated://no-voucher'},
    {'state':'CLOSED_BY_SUPPLIER','evidence_reference':' '},
])
def test_invalid_receipt_does_not_advance(workspace,receipt):
    w=workspace;command(w,'REGISTER','supplier');command(w,'CLAIM','supplier')
    before=money();command(w,'RECEIPT','supplier',receipt,status=409);assert money()==before
    assert w['client'].get(w['ap'],headers=w['operator']).json()['data']['workflow']['stage']=='ASSIGNED'


def test_resolution_and_workflow_share_atomic_transaction(workspace,monkeypatch):
    w=workspace;prepare(w);before=w['svc'].get(w['owner'],w['oid']),money()
    original=ticket_operations.append_vertical_evidence
    def fail(s,v,oid,kind,status,payload):
        if kind=='TICKET_OPERATIONS' and payload.get('action')=='APPLY':raise RuntimeError('after-native-before-workflow')
        return original(s,v,oid,kind,status,payload)
    monkeypatch.setattr(ticket_operations,'append_vertical_evidence',fail)
    with pytest.raises(RuntimeError,match='after-native-before-workflow'):command(w,'APPLY')
    assert (w['svc'].get(w['owner'],w['oid']),money())==before
    monkeypatch.setattr(ticket_operations,'append_vertical_evidence',original)
    command(w,'APPLY')
    assert w['svc'].get(w['owner'],w['oid'])['voucher_code']=='VOUCHER-OPS'


def test_money_corruption_blocks_follow_up_after_verification(workspace):
    w=workspace;prepare(w,'CLOSED_BY_SUPPLIER');command(w,'APPLY')
    q=w['svc'].refund_quote(w['owner'],w['oid']);w['svc'].refund(w['owner'],w['oid'],q['quote_hash'])
    command(w,'VERIFY','verifier')
    with SessionLocal.begin() as s:
        entry=s.scalar(select(OmnichannelLedgerEntryRow).where(OmnichannelLedgerEntryRow.entry_type=='REFUND'))
        entry.account_code='WRONG-ACCOUNT'
    before=money();command(w,'FOLLOW_UP',status=409);assert money()==before
    assert w['client'].get(w['ap'],headers=w['operator']).json()['data']['workflow']['stage']=='VERIFIED'


def test_stale_supplier_quote_cannot_apply_to_new_change(workspace):
    w=workspace
    q=w['svc'].change_quote(w['owner'],w['oid'],'2026-09-16','16:00')
    w['svc'].execute_change(w['owner'],w['oid'],q['quote_id'])
    command(w,'REGISTER','supplier');command(w,'CLAIM','supplier')
    command(w,'RECEIPT','supplier',{'state':'CONFIRMED','evidence_reference':'isolated://wrong',
        'supplier_reference':'S','voucher_code':'V','quote_id':'unrelated-quote'})
    before=w['svc'].get(w['owner'],w['oid']),money()
    command(w,'APPLY',status=409)
    assert (w['svc'].get(w['owner'],w['oid']),money())==before
    assert w['client'].get(w['ap'],headers=w['operator']).json()['data']['workflow']['stage']=='RECEIPT_RECORDED'


@pytest.mark.parametrize('commit_first',[False,True])
def test_actual_process_exit_resolves_attraction_atomically(workspace,commit_first):
    w=workspace;prepare(w)
    revision=w['client'].get(w['ap'],headers=w['operator']).json()['data']['workflow']['revision']
    body={'action':'APPLY','command_id':uuid4().hex,'expected_revision':revision,'note':'actual process death'}
    code='''import os,json
from go_hotel.services import ticket_operations as ops
from go_hotel.security.service import identity_service
principal=identity_service.authenticate(os.environ['TEST_ACTOR_TOKEN'])
original=ops.append_vertical_evidence
def crash(s,v,oid,kind,status,payload):
 if kind=='TICKET_OPERATIONS' and payload.get('action')=='APPLY':os._exit(75)
 return original(s,v,oid,kind,status,payload)
if os.environ['COMMIT_FIRST']=='False':ops.append_vertical_evidence=crash
ops.apply('ATTRACTION',os.environ['CASE_ORDER'],principal,json.loads(os.environ['CASE_BODY']))
os._exit(75)
'''
    env={**os.environ,'DATABASE_URL':engine.url.render_as_string(hide_password=False),'PYTHONPATH':os.path.abspath('src'),
        'TEST_ACTOR_TOKEN':w['operator']['Authorization'].removeprefix('Bearer '),'COMMIT_FIRST':str(commit_first),
        'CASE_ORDER':w['oid'],'CASE_BODY':json.dumps(body)}
    process=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,timeout=30)
    assert process.returncode==75,process.stderr.decode()
    assert w['svc'].get(w['owner'],w['oid'])['status']==('CONFIRMED' if commit_first else 'UNKNOWN_EXTERNAL_STATE')
    _,result=command(w,'APPLY',body=body)
    assert result.json()['data']['idempotent_replay']==commit_first
    with SessionLocal() as s:
        applied=[e for e in ticket_operations._events(s,'ATTRACTION',w['oid']) if e['action']=='APPLY']
        assert len(applied)==1


def test_supplier_vertical_filter_and_pagination_preserve_tenant(workspace):
    w=workspace
    _,_,second=booked('ATTRACTION','second-owner')
    base='/v1/supplier/transaction-orders'
    pages=[w['client'].get(base,headers=w['supplier'],params={'vertical':'ATTRACTION','limit':1,'offset':i}) for i in range(2)]
    assert all(r.status_code==200 for r in pages)
    rows=[r.json()['data']['items'][0] for r in pages]
    assert {r['order_id'] for r in rows}=={w['oid'],second}
    assert all(r['vertical']=='ATTRACTION' for r in rows)
    assert w['client'].get(base,headers=w['supplier'],params={'vertical':'RENTAL'}).json()['data']['items']==[]
    assert w['client'].get(base,headers=w['foreign'],params={'vertical':'ATTRACTION'}).json()['data']['items']==[]
    assert w['client'].get(base,headers=w['supplier'],params={'vertical':'INVALID'}).status_code==422
