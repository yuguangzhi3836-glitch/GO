"""Local PostgreSQL correctness only; no performance/workload runner.

Requires MONEY_READ_TEST_URL on a local Unix socket. Each test gets its own
new schema; application guards and models are real, not mocks. Run from root.
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import (
    OmnichannelPaymentIntentRow as Intent, OmnichannelMoneyMovementRow as Movement,
    OmnichannelLedgerEntryRow as Ledger, CatalogCreditSourceRow as Source,
    OrderSupplierFulfillmentRow as Fulfillment,
    OrderSupplierFulfillmentEventRow as FulfillmentEvent,
)
from go_hotel.services import unified_money_movement as candidate

BASE = '05b108cc63b008aad4da732ac97c7e453cf59220'
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='session')
def baseline(tmp_path_factory):
    path = tmp_path_factory.mktemp('source') / 'baseline.py'
    path.write_bytes(subprocess.check_output([
        'git', 'show', BASE + ':application/src/go_hotel/services/unified_money_movement.py'], cwd=ROOT))
    spec = importlib.util.spec_from_file_location('money_baseline', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=['baseline', 'candidate'])
def db(request, baseline, monkeypatch):
    url = os.environ.get('MONEY_READ_TEST_URL')
    if not url:
        pytest.skip('MONEY_READ_TEST_URL required; no fallback to application DB')
    parsed = make_url(url)
    host = parsed.query.get('host', '')
    if parsed.get_backend_name() != 'postgresql' or parsed.host or not host.startswith('/tmp/go-money-'):
        pytest.fail('Only explicitly isolated /tmp/go-money-* Unix sockets allowed')
    admin = create_engine(url)
    schema = 'money_read_' + uuid.uuid4().hex
    with admin.begin() as c:
        c.execute(text('CREATE SCHEMA ' + schema))
    engine = create_engine(url, connect_args={'options': '-c search_path=' + schema + ' -c statement_timeout=10000'}, pool_size=5)
    tables = [Intent.__table__, Movement.__table__, Ledger.__table__, Source.__table__,
              Fulfillment.__table__, FulfillmentEvent.__table__]
    for table in tables:
        table.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    module = candidate if request.param == 'candidate' else baseline
    monkeypatch.setattr(module, 'SessionLocal', sessions)
    ctx = type('DB', (), {})()
    ctx.engine, ctx.sessions, ctx.module, ctx.url, ctx.schema = engine, sessions, module, url, schema
    ctx.service = module.UnifiedMoneyMovementService()
    ctx.candidate = request.param == 'candidate'
    yield ctx
    engine.dispose()
    with admin.begin() as c:
        c.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
    admin.dispose()


def root(db, iid='root', business='RIDE_ORDER', amount=100):
    t = candidate.now()
    with db.sessions.begin() as s:
        s.add(Intent(payment_intent_id=iid, business_type=business, business_id=iid,
            payer_id='guest', payee_id='supplier', operation='PAY', amount_minor=amount,
            currency='CNY', channel_priority_json=['LOCAL_MARKET'], selected_channel='LOCAL_MARKET',
            state='SUCCEEDED', idempotency_key='intent:' + iid, automatic_fallback_allowed=False,
            created_at=t, updated_at=t))
        s.add(Fulfillment(order_supplier_fulfillment_id='fill:' + iid, payment_intent_id=iid,
            business_type=business, business_id=iid, supplier_id='supplier',
            supplier_idempotency_key='supplier:' + iid, state='PAYMENT_CONFIRMED_AWAITING_MONEY_GRAPH',
            evidence_reference='isolated://money', created_at=t, updated_at=t))


def body(kind, amount=100, parent=None):
    return dict(movement_type=kind, amount_minor=amount, parent_movement_id=parent,
                mode='CONTRACT_SIMULATOR', evidence=['isolated://money'])


def move(db, kind, key, amount=100, parent=None, iid='root'):
    return db.service.create(iid, body(kind, amount, parent), key, 'isolated-test')


def facts(db, captures=1):
    with db.sessions() as s:
        ms = list(s.scalars(select(Movement)))
        ls = list(s.scalars(select(Ledger)))
        assert sum(x.movement_type == 'CAPTURE' for x in ms) == captures
        assert len(ls) == 2 * captures
        assert sum(x.amount_minor for x in ls if x.direction == 'DEBIT') == sum(x.amount_minor for x in ls if x.direction == 'CREDIT')
        if captures == 1 and sum(x.amount_minor for x in ms if x.movement_type == 'CAPTURE') == 100:
            assert s.get(Fulfillment, 'fill:root').state == 'CAPTURE_CONFIRMED_READY_FOR_SUPPLIER'
            assert len(list(s.scalars(select(FulfillmentEvent)))) == 1
        return ms


@contextmanager
def selects(db):
    rows = []
    def record(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith('SELECT'):
            rows.append((statement, cursor.rowcount))
    event.listen(db.engine, 'after_cursor_execute', record)
    try:
        yield rows
    finally:
        event.remove(db.engine, 'after_cursor_execute', record)


def test_sql_budget_and_replay_rows(db):
    root(db)
    with selects(db) as a:
        auth = move(db, 'AUTHORIZATION', 'auth')
    with selects(db) as c:
        cap = move(db, 'CAPTURE', 'cap', parent=auth['money_movement_id'])
    with selects(db) as r:
        replay = move(db, 'CAPTURE', 'cap', parent=auth['money_movement_id'])
        for timestamp in ('created_at', 'updated_at'):
            assert datetime.fromisoformat(replay[timestamp]) == datetime.fromisoformat(cap[timestamp])
        assert {k: v for k, v in replay.items() if k not in ('created_at', 'updated_at')} == {k: v for k, v in cap.items() if k not in ('created_at', 'updated_at')}
    assert (len(a), len(c), len(r)) == ((3, 4, 2) if db.candidate else (4, 5, 2))
    # Honest replay cost: candidate locks/returns both AUTH and CAPTURE.
    assert r[1][1] == (2 if db.candidate else 1)
    print('SQL_SELECT_COUNTS', db.candidate, len(a), len(c), len(r), 'REPLAY_MOVEMENT_ROWS', r[1][1])
    facts(db)


def test_parallel_replay_and_conflicts(db):
    root(db)
    auth = move(db, 'AUTHORIZATION', 'auth')['money_movement_id']
    barrier = threading.Barrier(2)
    def capture(_):
        barrier.wait(timeout=5)
        return move(db, 'CAPTURE', 'cap', parent=auth)['money_movement_id']
    with ThreadPoolExecutor(2) as pool:
        ids = list(pool.map(capture, range(2)))
    assert ids[0] == ids[1]
    for kind, amount, parent in [('CAPTURE', 101, auth), ('CAPTURE', 100, None), ('AUTHORIZATION', 100, auth)]:
        with pytest.raises(ValueError, match='MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'):
            move(db, kind, 'cap', amount, parent)
    root(db, 'other')
    with pytest.raises(ValueError, match='MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'):
        move(db, 'CAPTURE', 'cap', parent=auth, iid='other')
    facts(db)


def test_global_key_insert_race_rollback(db):
    root(db); root(db, 'other')
    barrier = threading.Barrier(2)
    def before_insert(conn, cursor, statement, parameters, context, many):
        if statement.startswith('INSERT INTO omnichannel_money_movement'):
            barrier.wait(timeout=5)
    event.listen(db.engine, 'before_cursor_execute', before_insert)
    def work(iid):
        with db.sessions() as s:
            try:
                db.service.create_in_session(s, iid, body('AUTHORIZATION'), 'shared', 'test')
                s.commit()
                return 'ok'
            except IntegrityError:
                s.rollback()
                assert s.scalar(text('SELECT 1')) == 1
                return 'conflict'
    try:
        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(work, ['root', 'other'])) == ['conflict', 'ok']
    finally:
        event.remove(db.engine, 'before_cursor_execute', before_insert)
    assert len(facts(db, captures=0)) == 1


def test_parent_and_shared_release_budget(db):
    root(db)
    a = move(db, 'AUTHORIZATION', 'a', 60)['money_movement_id']
    move(db, 'AUTHORIZATION', 'b', 40)
    with pytest.raises(ValueError, match='PARENT_AUTHORIZATION_BUDGET_EXCEEDED'):
        move(db, 'CAPTURE', 'bad', 70, a)
    move(db, 'RELEASE', 'release', 30, a)
    with pytest.raises(ValueError, match='PARENT_AUTHORIZATION_BUDGET_EXCEEDED'):
        move(db, 'CAPTURE', 'bad2', 40, a)
    move(db, 'CAPTURE', 'good', 30, a)
    with pytest.raises(ValueError, match='PARENT_MOVEMENT_MUST_SHARE_ROOT'):
        move(db, 'CAPTURE', 'bad3', 1, 'missing')
    facts(db)


def test_concurrent_new_keys_cannot_overspend(db):
    root(db)
    a = move(db, 'AUTHORIZATION', 'a')['money_movement_id']
    barrier = threading.Barrier(2)
    def work(key):
        barrier.wait(timeout=5)
        try:
            move(db, 'CAPTURE', key, 60, a)
            return 'ok'
        except ValueError as e:
            assert str(e) == 'CUMULATIVE_CAPTURE_EXCEEDS_AUTHORIZATION'
            return 'budget'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(work, ['one', 'two'])) == ['budget', 'ok']
    facts(db)


def test_credit_source_still_blocks_ride(db):
    root(db)
    with db.sessions.begin() as s:
        s.add(Source(capture_id='source', credit_id='credit', payment_intent_id='root',
                     funded_minor=100, prior_refund_minor=0, excluded_minor=0))
    with pytest.raises(ValueError, match='CREDIT_SOURCE_FUNDS_RESERVED'):
        move(db, 'AUTHORIZATION', 'a')
    assert facts(db, captures=0) == []


def test_capture_release_race(db):
    root(db)
    auth = move(db, 'AUTHORIZATION', 'a')['money_movement_id']
    barrier = threading.Barrier(2)
    def work(kind):
        barrier.wait(timeout=5)
        try:
            move(db, kind, kind, 60, auth)
            return 'ok'
        except ValueError as exc:
            assert str(exc) in {'CAPTURE_EXCEEDS_UNRELEASED_AUTHORIZATION', 'RELEASE_EXCEEDS_REMAINING_AUTHORIZATION'}
            return 'budget'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(work, ['CAPTURE', 'RELEASE'])) == ['budget', 'ok']
    with db.sessions() as s:
        moves = list(s.scalars(select(Movement)))
        assert sum(m.amount_minor for m in moves if m.movement_type in {'CAPTURE', 'RELEASE'}) == 60
        captured = sum(m.movement_type == 'CAPTURE' for m in moves)
    facts(db, captures=captured)


def test_credit_source_committed_during_root_wait_is_seen(db):
    root(db)
    ready = threading.Event(); ids = {}
    with db.sessions() as first:
        first.scalar(select(Intent).where(Intent.payment_intent_id == 'root').with_for_update())
        first.add(Source(capture_id='source', credit_id='credit', payment_intent_id='root',
                         funded_minor=100, prior_refund_minor=0, excluded_minor=0))
        first.flush()
        def second():
            with db.sessions() as s:
                ids['pid'] = s.scalar(text('SELECT pg_backend_pid()'))
                ready.set()
                with pytest.raises(ValueError, match='CREDIT_SOURCE_FUNDS_RESERVED'):
                    db.service.create_in_session(s, 'root', body('AUTHORIZATION'), 'a', 'test')
                s.rollback()
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(second)
            try:
                assert ready.wait(5)
                wait_blocked(db, ids['pid'])
            finally:
                first.commit()
            future.result(timeout=10)
    assert facts(db, captures=0) == []


def test_nonride_keeps_original_query_path(db):
    root(db, business='TEST_SPLIT')
    with selects(db) as queries:
        move(db, 'AUTHORIZATION', 'a')
    assert len(queries) == 4
    assert not any(' OR ' in sql for sql, _ in queries)


def wait_blocked(db, pid):
    deadline = time.monotonic() + 5
    with db.engine.connect() as c:
        while time.monotonic() < deadline:
            if c.scalar(text('SELECT cardinality(pg_blocking_pids(:pid))'), {'pid': pid}):
                return
            time.sleep(.01)
    pytest.fail('second session did not actually wait on a database lock')


def test_post_lock_statement_sees_committed_authorization(db):
    root(db)
    ready = threading.Event(); ids = {}
    with db.sessions() as first:
        auth = db.service.create_in_session(first, 'root', body('AUTHORIZATION'), 'auth', 'test')
        def second():
            with db.sessions() as s:
                ids['pid'] = s.scalar(text('SELECT pg_backend_pid()'))
                ready.set()
                result = db.service.create_in_session(s, 'root', body('CAPTURE', parent=auth['money_movement_id']), 'cap', 'test')
                s.commit()
                return result
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(second)
            try:
                assert ready.wait(5)
                wait_blocked(db, ids['pid'])
            finally:
                first.commit()
            assert future.result(timeout=10)['state'] == 'CONFIRMED'
    facts(db)


def test_same_session_flush_and_rollback(db):
    root(db)
    with db.sessions() as s:
        a = db.service.create_in_session(s, 'root', body('AUTHORIZATION'), 'a', 'test')
        db.service.create_in_session(s, 'root', body('CAPTURE', parent=a['money_movement_id']), 'c', 'test')
        s.rollback()
        assert not list(s.scalars(select(Movement)))
        assert not list(s.scalars(select(Ledger)))
        assert s.get(Fulfillment, 'fill:root').state == 'PAYMENT_CONFIRMED_AWAITING_MONEY_GRAPH'
    assert facts(db, captures=0) == []


@pytest.mark.parametrize('commit_first', [False, True])
def test_disconnect_at_capture_boundary(db, commit_first):
    root(db)
    a = move(db, 'AUTHORIZATION', 'a')['money_movement_id']
    with db.sessions() as s:
        pid = s.scalar(text('SELECT pg_backend_pid()'))
        cap = db.service.create_in_session(s, 'root', body('CAPTURE', parent=a), 'c', 'test')
        if commit_first:
            # Terminate the backend that acknowledged the commit; response is discarded.
            s.commit()
        control = create_engine(db.url)
        try:
            with control.connect() as admin:
                assert admin.scalar(text('SELECT pg_terminate_backend(:pid)'), {'pid': pid})
        finally:
            control.dispose()
        if not commit_first:
            with pytest.raises(DBAPIError):
                s.commit()
            s.rollback()
    db.engine.dispose()
    recovered = move(db, 'CAPTURE', 'c', parent=a)
    assert (recovered['money_movement_id'] == cap['money_movement_id']) == commit_first
    facts(db)


@pytest.mark.parametrize('phase', ['auth_committed', 'capture_uncommitted', 'capture_committed'])
def test_process_exit_recovery(db, phase):
    root(db)
    code = '''
import importlib.util, os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
spec=importlib.util.spec_from_file_location('child_money',os.environ['MONEY_SOURCE'])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.SessionLocal=sessionmaker(create_engine(os.environ['MONEY_READ_TEST_URL'],connect_args={'options':'-c search_path='+os.environ['MONEY_SCHEMA']}),expire_on_commit=False,autoflush=False)
b={'movement_type':'AUTHORIZATION','amount_minor':100,'mode':'CONTRACT_SIMULATOR','evidence':['isolated://exit']}
a=m.unified_money_movement_service.create('root',b,'a','test')
if os.environ['MONEY_PHASE']=='auth_committed':os._exit(73)
s=m.SessionLocal()
m.unified_money_movement_service.create_in_session(s,'root',dict(b,movement_type='CAPTURE',parent_movement_id=a['money_movement_id']),'c','test')
if os.environ['MONEY_PHASE']=='capture_committed':s.commit()
os._exit(73)
'''
    env = dict(os.environ, MONEY_SOURCE=db.module.__file__, MONEY_SCHEMA=db.schema, MONEY_PHASE=phase)
    completed = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, timeout=30)
    assert completed.returncode == 73, completed.stderr.decode()
    before = facts(db, captures=int(phase == 'capture_committed'))
    assert sum(m.movement_type == 'AUTHORIZATION' for m in before) == 1
    a = move(db, 'AUTHORIZATION', 'a')['money_movement_id']
    move(db, 'CAPTURE', 'c', parent=a)
    facts(db)
