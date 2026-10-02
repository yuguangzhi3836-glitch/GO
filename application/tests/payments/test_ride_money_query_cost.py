"""Query-cost behavior and synthetic PostgreSQL money boundary qualification."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
import os
import subprocess
import sys
from threading import Barrier

import pytest
from sqlalchemy import event, select, func, text, create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from go_hotel.db.session import engine, SessionLocal
from go_hotel.db.models import (MobilityRideOrderRow as Ride,
    OmnichannelPaymentIntentRow as Intent, OmnichannelMoneyMovementRow as Movement,
    OmnichannelLedgerEntryRow as Ledger)
from go_hotel.mobility.ride.service import ride_service
from go_hotel.mobility.ride import cancellation_policy as policy
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from ride_cancellation_fixture import synthetic_policy, accepted_body, envelope


def root():
    t=datetime.now(timezone.utc)
    with SessionLocal.begin() as s:
        s.add(Intent(payment_intent_id='cost-root',business_type='TEST_COST',business_id='cost-order',
            payer_id='synthetic-owner',payee_id='synthetic-supplier',operation='PAY',amount_minor=10000,
            currency='CNY',channel_priority_json=['LOCAL_MARKET'],selected_channel='LOCAL_MARKET',
            state='SUCCEEDED',idempotency_key='cost-root',automatic_fallback_allowed=False,
            user_channel_consent_at=t,created_at=t,updated_at=t))


def body(kind,amount=10000,parent=None):
    return {'movement_type':kind,'amount_minor':amount,'parent_movement_id':parent,
        'mode':'CONTRACT_SIMULATOR','evidence':['isolated://query-cost']}


def move(kind,key,amount=10000,parent=None):
    return money.create('cost-root',body(kind,amount,parent),key,'synthetic-test')


def facts():
    with SessionLocal() as s:
        moves=list(s.scalars(select(Movement)))
        ledger=list(s.scalars(select(Ledger)))
        return (sorted((m.money_movement_id,m.movement_type,m.amount_minor) for m in moves),
            sum(x.amount_minor for x in ledger if x.direction=='DEBIT'),
            sum(x.amount_minor for x in ledger if x.direction=='CREDIT'),len(ledger))


@pytest.fixture
def postgres_only():
    if engine.dialect.name!='postgresql':
        if os.environ.get('GO_REQUIRE_POSTGRES')=='1':pytest.fail('PostgreSQL required')
        pytest.skip('PostgreSQL locks/disconnect/process-exit qualification')


def kill(pid):
    killer=create_engine(engine.url,poolclass=NullPool)
    try:
        with killer.begin() as c:assert c.scalar(text('SELECT pg_terminate_backend(:pid)'),{'pid':pid})
    finally:killer.dispose()


def ride_body():
    return {'offer_id':'ride_standard','pickup':'ISOLATED_A','dropoff':'ISOLATED_B',
        'pickup_at':(datetime.now(timezone.utc)+timedelta(days=10)).isoformat(),'passengers':[]}


def test_create_samples_policy_time_after_resolution_without_discarded_query(monkeypatch):
    with synthetic_policy():
        request=accepted_body(ride_service,ride_body())
        original_time=policy.db_now_ms; original_resolve=policy.resolve_policy; trace=[]
        def resolve(offer):trace.append('resolved');return original_resolve(offer)
        def clock(s):trace.append('clock');return original_time(s)
        monkeypatch.setattr(policy,'resolve_policy',resolve)
        monkeypatch.setattr(policy,'db_now_ms',clock)
        order=ride_service.create('query-owner',request)
    assert trace==['resolved','clock','clock']
    assert order['cancellation']['policy_hash']==request['cancellation_policy_hash']
    assert ride_service.get('query-owner',order['order_id'])['cancellation']==order['cancellation']


def test_policy_expiring_during_resolution_is_rejected_and_rolls_back(monkeypatch):
    with synthetic_policy():request=accepted_body(ride_service,ride_body())
    expired=[False]
    def resolve(offer):expired[0]=True;return envelope(offer)
    def clock(s):
        assert expired[0], 'No database time sample before the policy is resolved'
        return policy.instant('2099-01-01T00:00:00Z')
    monkeypatch.setattr(policy,'resolve_policy',resolve)
    monkeypatch.setattr(policy,'db_now_ms',clock)
    with pytest.raises(ValueError,match='RIDE_CANCELLATION_POLICY_INVALID'):
        ride_service.create('query-owner',request)
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(Ride))==0
    assert engine.pool.checkedout()==0


def test_bad_policy_consent_still_rolls_back_order():
    with synthetic_policy():
        request=dict(accepted_body(ride_service,ride_body()),cancellation_policy_hash='wrong')
        with pytest.raises(ValueError,match='RIDE_CANCELLATION_POLICY_ACCEPTANCE_REQUIRED'):
            ride_service.create('query-owner',request)
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(Ride))==0


def test_budget_query_omits_historical_payload_without_lazy_round_trips():
    root();auth=move('AUTHORIZATION','auth');queries=[]
    def before(c,cursor,sql,params,ctx,many):queries.append(sql)
    event.listen(engine,'before_cursor_execute',before)
    try:cap=move('CAPTURE','cap',parent=auth['money_movement_id'])
    finally:event.remove(engine,'before_cursor_execute',before)
    history=[q for q in queries if q.lstrip().startswith('SELECT') and
        'FROM omnichannel_money_movement' in q and 'WHERE omnichannel_money_movement.root_payment_intent_id' in q]
    assert len(history)==1
    assert 'evidence_json' not in history[0] and 'created_at' not in history[0]
    # Idempotency lookup + one history lookup; no deferred field is fetched later.
    assert len([q for q in queries if q.lstrip().startswith('SELECT') and 'FROM omnichannel_money_movement' in q])==2
    assert cap['evidence_json']==['isolated://query-cost']
    assert facts()[1:]==(10000,10000,2)


def test_caller_owned_pending_movement_state_is_preserved():
    root();auth=move('AUTHORIZATION','auth')
    with SessionLocal() as s:
        row=s.get(Movement,auth['money_movement_id']);row.state='EXTERNAL_EXECUTOR_REQUIRED'
        with pytest.raises(ValueError,match='CUMULATIVE_CAPTURE_EXCEEDS_AUTHORIZATION'):
            money.create_in_session(s,'cost-root',body('CAPTURE',parent=row.money_movement_id),'cap','test')
        s.rollback()
    move('CAPTURE','cap',parent=auth['money_movement_id'])
    assert facts()[1:]==(10000,10000,2)


def test_replay_preserves_full_movement_output_and_amount_conflicts():
    root();auth=move('AUTHORIZATION','auth');first=move('CAPTURE','cap',parent=auth['money_movement_id'])
    replay=move('CAPTURE','cap',parent=auth['money_movement_id'])
    for name,value in first.items():
        if name in {'created_at','updated_at'}:
            # SQLite drops timezone metadata on reload; monetary facts and
            # timestamp instants must match on both supported dialects.
            assert datetime.fromisoformat(replay[name]).replace(tzinfo=timezone.utc)==datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        else:assert replay[name]==value
    assert set(first)=={c.name for c in Movement.__table__.columns}
    before=facts()
    with pytest.raises(ValueError,match='MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'):
        move('CAPTURE','cap',amount=9999,parent=auth['money_movement_id'])
    assert facts()==before


def test_forfeiture_parent_remains_nonrefundable():
    from go_hotel.services.hosted_fare_value import FORFEITURE_KEY
    root();auth=move('AUTHORIZATION','auth');cap=move('CAPTURE',FORFEITURE_KEY+'cost',parent=auth['money_movement_id'])
    with pytest.raises(ValueError,match='HOSTED_CHANGE_FORFEITURE_NOT_REFUNDABLE'):
        move('REFUND','refund',parent=cap['money_movement_id'])
    assert facts()[1:]==(10000,10000,2)


@pytest.mark.parametrize('amounts',[(10000,10000),(10000,9999)])
def test_concurrent_capture_same_key_has_one_effect(postgres_only,amounts):
    root();auth=move('AUTHORIZATION','auth');barrier=Barrier(2)
    def capture(amount):
        barrier.wait(timeout=10)
        try:return ('ok',move('CAPTURE','cap',amount,parent=auth['money_movement_id']))
        except ValueError as e:return ('error',str(e))
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(capture,amounts))
    ok=[r for kind,r in results if kind=='ok'];errors=[r for kind,r in results if kind=='error']
    assert len({r['money_movement_id'] for r in ok})==1
    assert errors==([] if amounts[0]==amounts[1] else ['MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'])
    assert facts()[1:]==(ok[0]['amount_minor'],ok[0]['amount_minor'],2)
    assert engine.pool.checkedout()==0


def test_real_disconnect_before_capture_commit_rolls_back_and_releases(postgres_only,monkeypatch):
    root();auth=move('AUTHORIZATION','auth');original=money.create_in_session;calls=[]
    def interrupted(s,*args):
        pid=s.scalar(text('SELECT pg_backend_pid()'));result=original(s,*args);calls.append(True);kill(pid);return result
    with monkeypatch.context() as p:
        p.setattr(money,'create_in_session',interrupted)
        with pytest.raises(DBAPIError):move('CAPTURE','cap',parent=auth['money_movement_id'])
    assert calls==[True] and engine.pool.checkedout()==0
    assert len(facts()[0])==1 and facts()[1:]==(0,0,0)
    move('CAPTURE','cap',parent=auth['money_movement_id']);assert facts()[1:]==(10000,10000,2)


def test_committed_capture_survives_real_disconnect_without_second_charge(postgres_only,monkeypatch):
    root();auth=move('AUTHORIZATION','auth');original=money.create_in_session;pids=[]
    def observed(s,*args):pids.append(s.scalar(text('SELECT pg_backend_pid()')));return original(s,*args)
    with monkeypatch.context() as p:
        p.setattr(money,'create_in_session',observed)
        first=move('CAPTURE','cap',parent=auth['money_movement_id'])
    kill(pids[0]);before=facts()
    assert move('CAPTURE','cap',parent=auth['money_movement_id'])==first
    assert facts()==before and before[1:]==(10000,10000,2) and engine.pool.checkedout()==0


def test_process_exit_after_auth_before_capture_preserves_boundary(postgres_only):
    root()
    script="""import os
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
money.create('cost-root',%s,'auth','synthetic-test')
os._exit(71)
""" % repr(body('AUTHORIZATION'))
    child=subprocess.run([sys.executable,'-c',script],env=dict(os.environ),capture_output=True,text=True,timeout=30)
    assert child.returncode==71,child.stderr[-1000:]
    state=facts();assert len(state[0])==1 and state[0][0][1]=='AUTHORIZATION' and state[1:]==(0,0,0)
    move('CAPTURE','cap',parent=state[0][0][0]);assert facts()[1:]==(10000,10000,2)


def test_failed_commit_is_not_retried_and_releases_session(postgres_only,monkeypatch):
    root();auth=move('AUTHORIZATION','auth');original=money.create_in_session;calls=[]
    def observed(s,*args):
        result=original(s,*args);calls.append(True)
        def fail():raise RuntimeError('ISOLATED_COMMIT_FAILURE')
        s.commit=fail;return result
    with monkeypatch.context() as p:
        p.setattr(money,'create_in_session',observed)
        with pytest.raises(RuntimeError,match='ISOLATED_COMMIT_FAILURE'):
            move('CAPTURE','cap',parent=auth['money_movement_id'])
    assert calls==[True] and engine.pool.checkedout()==0 and facts()[1:]==(0,0,0)
    move('CAPTURE','cap',parent=auth['money_movement_id']);assert facts()[1:]==(10000,10000,2)


def test_auth_commit_disconnect_preserves_auth_and_allows_capture(postgres_only,monkeypatch):
    root();original=money.create_in_session;pids=[]
    def observed(s,*args):pids.append(s.scalar(text('SELECT pg_backend_pid()')));return original(s,*args)
    with monkeypatch.context() as p:
        p.setattr(money,'create_in_session',observed)
        auth=move('AUTHORIZATION','auth')
    kill(pids[0])
    assert len(facts()[0])==1 and facts()[1:]==(0,0,0)
    move('CAPTURE','cap',parent=auth['money_movement_id'])
    assert facts()[1:]==(10000,10000,2) and engine.pool.checkedout()==0


def test_lost_capture_commit_ack_does_not_duplicate_money(postgres_only,monkeypatch):
    import psycopg
    root();auth=move('AUTHORIZATION','auth');original=engine.dialect.do_commit;calls=[]
    def uncertain(connection):
        original(connection);calls.append(True)
        raise psycopg.OperationalError('ISOLATED_LOST_COMMIT_ACK')
    with monkeypatch.context() as p:
        p.setattr(engine.dialect,'do_commit',uncertain)
        with pytest.raises(DBAPIError):move('CAPTURE','cap',parent=auth['money_movement_id'])
    assert calls==[True] and engine.pool.checkedout()==0
    before=facts();assert before[1:]==(10000,10000,2)
    move('CAPTURE','cap',parent=auth['money_movement_id']);assert facts()==before
