"""Regression coverage for current-architecture fixes after PR217 retirement."""
import os
from urllib.parse import parse_qs, urlparse
import pytest
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    ProfileImportJobRow as Job, RentalChangeQuoteRow as Quote,
    OmnichannelMoneyMovementRow as Movement, OmnichannelPaymentIntentRow as Intent,
    OmnichannelLedgerEntryRow as Entry,
)
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as vault, h
from go_hotel.mobility.rental import changes
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as bridge
from tests.test_depth06_rental_settlement import paid, START, end, balances


@pytest.fixture(scope='module',autouse=True)
def isolated_media_cache(tmp_path_factory):
    # The C13 candidate is mounted read-only. Keep runtime cache creation in
    # pytest's writable temporary directory, before the client imports the app.
    previous=os.environ.get('GO_MEDIA_CACHE_DIR')
    os.environ['GO_MEDIA_CACHE_DIR']=str(tmp_path_factory.mktemp('guard-media'))
    try:
        yield
    finally:
        if previous is None:os.environ.pop('GO_MEDIA_CACHE_DIR',None)
        else:os.environ['GO_MEDIA_CACHE_DIR']=previous


@pytest.mark.parametrize('key',['source_disconnected','values_deleted','connection_intent',
    'provider_connection_id','account_holder_authorized','state_hash','import_job_id'])
def test_client_reserved_metadata_rejected_before_insert(key):
    with pytest.raises(ValueError,match='PROFILE_IMPORT_METADATA_RESERVED'):
        vault.create_import('owner',{'metadata':{key:False},'items':[]})
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(Job))==0


@pytest.mark.parametrize('metadata',[[],False,'connection_intent'])
def test_metadata_must_be_object(metadata):
    with pytest.raises(ValueError,match='PROFILE_IMPORT_METADATA_INVALID'):
        vault.create_import('owner',{'metadata':metadata})


def test_http_body_cannot_promote_metadata_trust(client):
    from tests.test_sprint3a_flight import auth
    response=client.post('/v1/consumer/profile/imports',headers=auth(client),json={
        'trusted_source':True,'provider_connection_id':'forged',
        'metadata':{'connection_intent':True},'items':[]})
    assert response.status_code==409
    assert response.json()['detail']=='PROFILE_IMPORT_METADATA_RESERVED'


@pytest.mark.parametrize('official',[False,True])
def test_server_provider_import_and_replay_binding(monkeypatch,official):
    if official:monkeypatch.setenv('GO_CTRIP_PROFILE_AUTHORIZATION_URL','https://provider.example/authorize')
    else:monkeypatch.delenv('GO_CTRIP_PROFILE_AUTHORIZATION_URL',raising=False)
    connection=vault.create_provider_connection('owner',{'provider':'CTRIP','account_holder_confirmed':True})
    cid=connection['connection_id']
    if official:
        state=parse_qs(urlparse(connection['authorization_url']).query)['state'][0]
        result=vault.complete_provider_connection(cid,{'state':state,'account_holder_verified':True,
            'provider_account_subject':'subject','authorization_evidence_reference':'test://authorization','items':[]})
    else:result=vault.upload_provider_export('owner',cid,{'account_holder_confirmed':True,'items':[]})
    preview=result['preview']
    with SessionLocal() as s:
        job=s.get(Job,preview['import_job_id'])
        assert job.metadata_json['provider_connection_id']==cid
        assert job.metadata_json['account_holder_authorized' if official else 'account_holder_confirmed'] is True
    with pytest.raises(ValueError,match='PROFILE_PROVIDER_IMPORT_BINDING_INVALID'):
        vault.create_import('owner',{'source_type':'USER_DATA_PACKAGE','source_provider':'CTRIP',
            'source_reference':cid,'source_fingerprint':preview['source_fingerprint'],'items':[]})
    assert vault.disconnect_provider_connection('owner',cid,True)['status']=='DELETED'


@pytest.mark.parametrize('mutation',['owner','provider','fingerprint','reference','status'])
def test_internal_provider_binding_cannot_cross_owner_or_source(monkeypatch,mutation):
    monkeypatch.delenv('GO_CTRIP_PROFILE_AUTHORIZATION_URL',raising=False)
    connection=vault.create_provider_connection('owner',{'provider':'CTRIP','account_holder_confirmed':True})
    cid=connection['connection_id']
    with SessionLocal.begin() as s:s.get(Job,cid).status='UPLOAD_CONSUMED'
    user='owner';body={'source_type':'USER_DATA_PACKAGE','source_provider':'CTRIP',
        'source_reference':cid,'source_fingerprint':h([cid,'user-export']),'items':[]}
    if mutation=='owner':user='other'
    elif mutation=='provider':body['source_provider']='MEITUAN'
    elif mutation=='fingerprint':body['source_fingerprint']='wrong'
    elif mutation=='reference':body['source_reference']='wrong'
    else:
        with SessionLocal.begin() as s:s.get(Job,cid).status='DISCONNECTED'
    with pytest.raises(ValueError,match='PROFILE_PROVIDER_IMPORT_BINDING_INVALID'):
        vault._create_import(user,body,provider_connection_id=cid)
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(Job))==1


def test_user_metadata_and_regular_replay_remain_valid():
    body={'source_type':'MANUAL','source_fingerprint':'ordinary','metadata':{'note':'my file'},'items':[]}
    first=vault.create_import('owner',body)
    assert vault.create_import('owner',body)['import_job_id']==first['import_job_id']
    with SessionLocal() as s:assert s.get(Job,first['import_job_id']).metadata_json=={'note':'my file'}


@pytest.mark.parametrize('field',['state','amount','currency','parent','key','owner','ledger','missing'])
def test_topup_requires_durable_bound_capture(client,monkeypatch,field):
    account,oid,_=paid(client);q=changes.quote(account,oid,START,end(4))
    original=bridge.capture_adjustment
    def corrupt(*a,**kw):
        result=original(*a,**kw)
        with SessionLocal.begin() as s:
            cap=s.get(Movement,result['capture_id'])
            if field=='state':cap.state='UNKNOWN_EXTERNAL_STATE'
            elif field=='amount':cap.amount_minor+=1
            elif field=='currency':cap.currency='USD'
            elif field=='parent':cap.parent_movement_id='unrelated'
            elif field=='key':cap.idempotency_key='unrelated'
            elif field=='owner':s.get(Intent,cap.root_payment_intent_id).payer_id='other-owner'
            elif field=='ledger':
                row=s.scalar(select(Entry).where(Entry.transaction_id==cap.money_movement_id));row.amount_minor+=1
            else:result['capture_id']='missing'
        return result
    monkeypatch.setattr(bridge,'capture_adjustment',corrupt)
    with pytest.raises(ValueError,match='RENTAL_CHANGE_(CAPTURE_NOT_CONFIRMED|PAYMENT_BINDING_INVALID)'):
        changes.execute(account,oid,q['quote_id'],42000,'CNY')
    with SessionLocal() as s:assert s.get(Quote,q['quote_id']).status=='MONEY_PENDING'
    from go_hotel.mobility.rental.service import rental_service
    order=rental_service.get(account,oid)
    assert order['status']=='CHANGE_PENDING' and order['return_at']==end(3)


@pytest.mark.parametrize('case',['missing','duplicate','key'])
def test_refund_receipt_must_match_frozen_plan(client,monkeypatch,case):
    account,oid,_=paid(client);q=changes.quote(account,oid,START,end(2))
    original=bridge.execute_refund_plan
    def corrupt(*a,**kw):
        result=original(*a,**kw)
        if case=='missing':result['money_movement_ids']=['missing']
        elif case=='duplicate':result['money_movement_ids']*=2
        else:
            with SessionLocal.begin() as s:s.get(Movement,result['money_movement_ids'][0]).idempotency_key='unrelated-refund'
        return result
    monkeypatch.setattr(bridge,'execute_refund_plan',corrupt)
    with pytest.raises(ValueError,match='REFUND_'):
        changes.execute(account,oid,q['quote_id'],-42000,'CNY')
    with SessionLocal() as s:assert s.get(Quote,q['quote_id']).status=='MONEY_PENDING'


def test_forged_refund_plan_rejected_before_money_execution(client,monkeypatch):
    account,oid,_=paid(client);q=changes.quote(account,oid,START,end(2))
    original=bridge.plan_refund
    def corrupt(*a,**kw):
        plan=original(*a,**kw);plan[0]['key']='unrelated-operation';return plan
    monkeypatch.setattr(bridge,'plan_refund',corrupt)
    def forbidden(*a,**kw):pytest.fail('must reject before moving money')
    monkeypatch.setattr(bridge,'execute_refund_plan',forbidden)
    with pytest.raises(ValueError,match='RENTAL_CHANGE_REFUND_PLAN_INVALID'):
        changes.execute(account,oid,q['quote_id'],-42000,'CNY')
    assert balances()['REFUND']==0


def test_executed_replay_revalidates_capture(client):
    account,oid,_=paid(client);q=changes.quote(account,oid,START,end(4))
    changes.execute(account,oid,q['quote_id'],42000,'CNY')
    with SessionLocal.begin() as s:
        cap=s.scalar(select(Movement).where(Movement.business_id==q['quote_id'],Movement.movement_type=='CAPTURE'))
        cap.state='UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError,match='RENTAL_CHANGE_CAPTURE_NOT_CONFIRMED'):
        changes.execute(account,oid,q['quote_id'],42000,'CNY')


@pytest.mark.parametrize('days',[2,4])
def test_money_committed_before_completion_interruption_replays_once(client,monkeypatch,days):
    account,oid,_=paid(client);q=changes.quote(account,oid,START,end(days))
    original=changes.change_receipts.confirmed_in
    def interrupted(*a,**kw):raise RuntimeError('isolated post-money interruption')
    monkeypatch.setattr(changes.change_receipts,'confirmed_in',interrupted)
    with pytest.raises(RuntimeError,match='interruption'):
        changes.execute(account,oid,q['quote_id'],q['difference_minor'],'CNY')
    before=balances()
    with SessionLocal() as s:assert s.get(Quote,q['quote_id']).status=='MONEY_PENDING'
    monkeypatch.setattr(changes.change_receipts,'confirmed_in',original)
    for _ in range(2):
        assert changes.execute(account,oid,q['quote_id'],q['difference_minor'],'CNY')['status']=='EXECUTED'
    assert balances()==before
