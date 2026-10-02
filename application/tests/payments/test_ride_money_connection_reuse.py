"""Actual commits, locks, backend disconnects and process death; synthetic money only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import sys
from threading import Barrier

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from go_hotel.db.session import engine, SessionLocal
from go_hotel.db.models import (OmnichannelPaymentIntentRow as Intent,
    OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Ledger,
    OrderSupplierFulfillmentRow as Fulfillment)
from go_hotel.mobility.ride.service import ride_service
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payments
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge
from ride_cancellation_fixture import create_ride


def prepared():
    oid=create_ride(ride_service,'boundary-owner',{
        'offer_id':'ride_standard','pickup':'ISOLATED_A','dropoff':'ISOLATED_B',
        'pickup_at':(datetime.now(timezone.utc)+timedelta(days=10)).isoformat(),
        'passengers':[{'full_name':'ISOLATED'}]})['order_id']
    intent=payments.create_intent({'business_type':'RIDE_ORDER','business_id':oid,
        'channel_priority':['LOCAL_MARKET']},'ride-checkout:'+oid,'boundary-owner')
    iid=intent['payment_intent_id']
    bridge._confirm_contract_payment(iid,'boundary-owner')
    return oid,iid


def graph(oid,iid):
    return bridge._ride_money_graph(iid,oid,'isolated://connection-boundary')


def facts(iid):
    with SessionLocal() as s:
        moves=list(s.scalars(select(Movement).where(Movement.root_payment_intent_id==iid)))
        ledger=list(s.scalars(select(Ledger).where(Ledger.payment_intent_id==iid)))
        f=s.scalar(select(Fulfillment).where(Fulfillment.payment_intent_id==iid))
        return {'moves':[(x.money_movement_id,x.movement_type,x.amount_minor,x.parent_movement_id) for x in moves],
            'debit':sum(x.amount_minor for x in ledger if x.direction=='DEBIT'),'credit':sum(x.amount_minor for x in ledger if x.direction=='CREDIT'),
            'ledger_count':len(ledger),'fulfillment_state':f.state if f else None}


def assert_complete(iid):
    state=facts(iid)
    assert sorted(x[1] for x in state['moves'])==['AUTHORIZATION','CAPTURE']
    assert state['debit']==state['credit']==16800
    assert state['ledger_count']==2
    assert state['fulfillment_state']=='CAPTURE_CONFIRMED_READY_FOR_SUPPLIER'
    return state


@pytest.fixture
def postgres_only():
    if engine.dialect.name!='postgresql':
        if os.environ.get('GO_REQUIRE_POSTGRES')=='1':pytest.fail('PostgreSQL required; no skip allowed')
        pytest.skip('real PostgreSQL commit/lock/disconnect proof')


def test_same_graph_replays_and_changed_amount_never_adds_money():
    oid,iid=prepared(); first=graph(oid,iid)
    replay=graph(oid,iid)
    assert (replay[0]['money_movement_id'],replay[1]['money_movement_id'],replay[2])==(first[0]['money_movement_id'],first[1]['money_movement_id'],first[2])
    before=assert_complete(iid)
    with pytest.raises(ValueError,match='MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'):
        money.create(iid,{'movement_type':'CAPTURE','parent_movement_id':first[0]['money_movement_id'],
            'amount_minor':16801,'mode':'CONTRACT_SIMULATOR','evidence':['isolated://conflict']},
            'ride-cap:'+oid,'isolated-test')
    assert facts(iid)==before


def test_postgres_uses_one_checkout_and_fresh_sessions(postgres_only,monkeypatch):
    oid,iid=prepared(); acquisitions=[]; sessions=[]; original=money.create_in_session
    def checkout(*args):acquisitions.append(True)
    def observed(s,*args,**kwargs):
        sessions.append(s); return original(s,*args,**kwargs)
    monkeypatch.setattr(money,'create_in_session',observed)
    event.listen(engine,'checkout',checkout)
    try:graph(oid,iid)
    finally:event.remove(engine,'checkout',checkout)
    assert len(acquisitions)==1 and len(sessions)==2 and sessions[0] is not sessions[1]
    assert engine.pool.checkedout()==0
    assert_complete(iid)


def test_postgres_simultaneous_graph_replay_has_one_effect(postgres_only):
    oid,iid=prepared(); barrier=Barrier(6)
    def run(_):barrier.wait(timeout=10);return graph(oid,iid)
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(run,range(6)))
    assert len({(result[0]['money_movement_id'],result[1]['money_movement_id'],result[2]) for result in results})==1
    assert_complete(iid)
    assert engine.pool.checkedout()==0


def test_capture_reads_state_changed_after_auth_commit(postgres_only,monkeypatch):
    oid,iid=prepared(); original=money.create_in_session
    def changed(s,intent,body,*args):
        if body['movement_type']=='CAPTURE':
            with SessionLocal.begin() as other:
                row=other.get(Intent,iid,with_for_update=True)
                row.state='FAILED'
        return original(s,intent,body,*args)
    monkeypatch.setattr(money,'create_in_session',changed)
    with pytest.raises(ValueError,match='ROOT_PAYMENT_SUCCESS_REQUIRED'):graph(oid,iid)
    state=facts(iid)
    assert [x[1] for x in state['moves']]==['AUTHORIZATION']
    assert state['ledger_count']==0 and engine.pool.checkedout()==0


def test_capture_failure_rolls_back_only_capture_and_retry_resumes(postgres_only,monkeypatch):
    oid,iid=prepared(); original=money.create_in_session
    def fail(s,intent,body,*args):
        result=original(s,intent,body,*args)
        if body['movement_type']=='CAPTURE':raise RuntimeError('ISOLATED_AFTER_CAPTURE_FLUSH')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(money,'create_in_session',fail)
        with pytest.raises(RuntimeError,match='ISOLATED_AFTER_CAPTURE_FLUSH'):graph(oid,iid)
    state=facts(iid)
    assert [x[1] for x in state['moves']]==['AUTHORIZATION'] and state['ledger_count']==0
    assert engine.pool.checkedout()==0
    auth=state['moves'][0][0]
    assert graph(oid,iid)[0]['money_movement_id']==auth
    assert_complete(iid)


def test_real_backend_disconnect_after_auth_is_not_implicitly_retried(postgres_only,monkeypatch):
    oid,iid=prepared(); original=money.create_in_session; pid=[]; captures=[]
    def disconnected(s,intent,body,*args):
        if body['movement_type']=='AUTHORIZATION':pid.append(s.scalar(text('SELECT pg_backend_pid()')))
        else:
            captures.append(True)
            with engine.begin() as killer:
                assert killer.scalar(text('SELECT pg_terminate_backend(:pid)'),{'pid':pid[0]})
        return original(s,intent,body,*args)
    with monkeypatch.context() as patch:
        patch.setattr(money,'create_in_session',disconnected)
        with pytest.raises(DBAPIError):graph(oid,iid)
    assert len(captures)==1 and engine.pool.checkedout()==0
    state=facts(iid)
    assert [x[1] for x in state['moves']]==['AUTHORIZATION'] and state['ledger_count']==0
    graph(oid,iid);assert_complete(iid)


def test_real_disconnect_after_capture_commit_resumes_without_second_capture(postgres_only,monkeypatch):
    oid,iid=prepared(); original=money.create_in_session; pid=[]
    def observed(s,intent,body,*args):
        if body['movement_type']=='AUTHORIZATION':pid.append(s.scalar(text('SELECT pg_backend_pid()')))
        s.info['isolated_boundary_phase']=body['movement_type']
        return original(s,intent,body,*args)
    def after_commit(s):
        if s.info.get('isolated_boundary_phase')=='CAPTURE':
            with engine.begin() as killer:
                assert killer.scalar(text('SELECT pg_terminate_backend(:pid)'),{'pid':pid[0]})
    with monkeypatch.context() as patch:
        patch.setattr(money,'create_in_session',observed)
        event.listen(Session,'after_commit',after_commit)
        try:
            with pytest.raises(DBAPIError):graph(oid,iid)
        finally:event.remove(Session,'after_commit',after_commit)
    before=assert_complete(iid)
    graph(oid,iid)
    assert facts(iid)==before and engine.pool.checkedout()==0


def test_process_exit_before_capture_leaves_durable_auth_and_recoverable_pool(postgres_only):
    oid,iid=prepared()
    script='''import os
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge
original=money.create_in_session
def die(s,intent,body,*args):
    if body['movement_type']=='CAPTURE':os._exit(71)
    return original(s,intent,body,*args)
money.create_in_session=die
bridge._ride_money_graph(%s,%s,'isolated://process-exit')
''' % (json.dumps(iid),json.dumps(oid))
    child=subprocess.run([sys.executable,'-c',script],env=dict(os.environ),timeout=30,capture_output=True,text=True)
    assert child.returncode==71,child.stderr[-1000:]
    state=facts(iid)
    assert [x[1] for x in state['moves']]==['AUTHORIZATION'] and state['ledger_count']==0
    auth=state['moves'][0][0]
    assert graph(oid,iid)[0]['money_movement_id']==auth
    assert_complete(iid)


def test_authorization_flush_failure_rolls_back_and_releases_checkout(postgres_only,monkeypatch):
    oid,iid=prepared(); original=money.create_in_session
    def failed(s,*args):
        original(s,*args)
        raise RuntimeError('ISOLATED_AUTH_NOT_COMMITTED')
    with monkeypatch.context() as patch:
        patch.setattr(money,'create_in_session',failed)
        with pytest.raises(RuntimeError,match='ISOLATED_AUTH_NOT_COMMITTED'):graph(oid,iid)
    assert facts(iid)['moves']==[] and facts(iid)['ledger_count']==0
    assert engine.pool.checkedout()==0
    graph(oid,iid);assert_complete(iid)


def test_conflicting_amounts_race_on_one_key_have_one_effect(postgres_only):
    oid,iid=prepared(); auth=money.create(iid,{'movement_type':'AUTHORIZATION',
        'mode':'CONTRACT_SIMULATOR','evidence':['isolated://auth']},'ride-auth:'+oid,'isolated')
    barrier=Barrier(2)
    def capture(amount):
        barrier.wait(timeout=10)
        try:
            with engine.connect() as connection:
                with SessionLocal(bind=connection) as s:
                    result=money.create_in_session(s,iid,{'movement_type':'CAPTURE',
                        'parent_movement_id':auth['money_movement_id'],'amount_minor':amount,
                        'mode':'CONTRACT_SIMULATOR','evidence':['isolated://amount-race']},
                        'ride-cap:'+oid,'isolated')
                    s.commit();return ('ok',result['amount_minor'])
        except ValueError as exc:return ('rejected',str(exc))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(capture,[16800,16799]))
    accepted=[v for kind,v in results if kind=='ok']
    assert len(accepted)==1
    assert [v for kind,v in results if kind=='rejected']==['MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT']
    state=facts(iid)
    assert state['debit']==state['credit']==accepted[0] and state['ledger_count']==2
    assert len(state['moves'])==2 and engine.pool.checkedout()==0


def test_commit_failure_does_not_retry_or_leak_session(postgres_only,monkeypatch):
    oid,iid=prepared(); original=money.create_in_session; calls=[]
    def observed(s,intent,body,*args):
        result=original(s,intent,body,*args);calls.append(body['movement_type'])
        if body['movement_type']=='CAPTURE':
            def fail():raise RuntimeError('ISOLATED_COMMIT_FAILURE')
            s.commit=fail
        return result
    with monkeypatch.context() as patch:
        patch.setattr(money,'create_in_session',observed)
        with pytest.raises(RuntimeError,match='ISOLATED_COMMIT_FAILURE'):graph(oid,iid)
    assert calls==['AUTHORIZATION','CAPTURE']
    assert [m[1] for m in facts(iid)['moves']]==['AUTHORIZATION']
    assert engine.pool.checkedout()==0
    graph(oid,iid);assert_complete(iid)
