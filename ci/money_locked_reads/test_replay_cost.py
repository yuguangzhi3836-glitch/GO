"""Serial local probes, not a load test or ABBA/performance acceptance gate."""
import json
import os
from pathlib import Path
from statistics import median
import time

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError

from test_correctness import baseline, db, root, move, facts, body
from go_hotel.services import unified_money_movement as money
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement


def save(db, name, result):
    directory = os.environ.get('MONEY_REPLAY_OUTPUT')
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        (path / (name + '-' + ('candidate' if db.candidate else 'baseline') + '.json')).write_text(
            json.dumps(result, indent=2, default=str) + '\n')


@pytest.mark.parametrize('history_size', [2, 20, 200, 2000])
def test_serial_replay_cardinality_and_plan(db, history_size):
    root(db)
    auth = move(db, 'AUTHORIZATION', 'auth')['money_movement_id']
    cap = move(db, 'CAPTURE', 'cap', parent=auth)['money_movement_id']
    now = money.now()
    def row(idx, iid):
        return dict(money_movement_id=f'extra-{iid}-{idx:06}', root_payment_intent_id=iid,
                    parent_movement_id=None, movement_type='AUTHORIZATION', business_type='RIDE_ORDER',
                    business_id=iid, amount_minor=1, currency='CNY', state='FAILED',
                    idempotency_key=f'extra-key-{iid}-{idx:06}', external_reference=None,
                    evidence_json=['isolated://history-cost'], created_at=now, updated_at=now)
    # Synthetic failed history does not change the confirmed budget. Background
    # rows keep the planner from seeing a table containing only the target root.
    with db.engine.begin() as c:
        rows = [row(i, 'root') for i in range(history_size - 2)]
        rows += [row(i, 'background') for i in range(8000)]
        c.execute(Movement.__table__.insert(), rows)
        c.execute(text('ANALYZE omnichannel_money_movement'))
    for _ in range(3):
        assert move(db, 'CAPTURE', 'cap', parent=auth)['money_movement_id'] == cap
    wall, cpu = [], []
    for _ in range(30):
        start_wall, start_cpu = time.perf_counter(), time.thread_time()
        result = move(db, 'CAPTURE', 'cap', parent=auth)
        wall.append((time.perf_counter() - start_wall) * 1000)
        cpu.append((time.thread_time() - start_cpu) * 1000)
        assert result['money_movement_id'] == cap
    statements = []
    def record(conn, cursor, statement, parameters, context, many):
        if statement.startswith(('SELECT', 'WITH')):
            statements.append((statement, parameters, cursor.rowcount))
    event.listen(db.engine, 'after_cursor_execute', record)
    try:
        move(db, 'CAPTURE', 'cap', parent=auth)
    finally:
        event.remove(db.engine, 'after_cursor_execute', record)
    assert len(statements) == 2
    assert statements[1][2] == 1
    sql, parameters, _ = statements[1]
    with db.engine.connect() as c:
        cursor = c.connection.cursor()
        cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql, parameters)
        plan = cursor.fetchone()[0]
        cursor.close()
        c.rollback()
    if db.candidate:
        def walk(node):
            yield node
            for child in node.get('Plans', []):
                yield from walk(child)
        history_plans = [n for n in walk(plan[0]['Plan']) if n.get('Subplan Name') == 'CTE money_history']
        assert len(history_plans) == 1
        scans = [n for n in walk(history_plans[0]) if n.get('Relation Name') == Movement.__tablename__]
        assert scans and all(n['Actual Loops'] == 0 for n in scans)
    output = dict(history_size=history_size, background_rows=8000,
                  implementation='candidate' if db.candidate else 'baseline',
                  samples=30, warmup=3, sequential_only=True, performance_acceptance=False,
                  select_count=2, movement_rows_returned=statements[1][2],
                  wall_ms=wall, calling_thread_cpu_ms=cpu,
                  median_wall_ms=median(wall), median_calling_thread_cpu_ms=median(cpu),
                  explain=plan)
    save(db, 'history-' + str(history_size), output)
    print('REPLAY_COST', output['implementation'], history_size,
          round(median(wall), 3), round(median(cpu), 3), statements[1][2])
    facts(db)


@pytest.mark.parametrize('request_kind', ['replay', 'amount_conflict', 'root_conflict'])
def test_unrelated_auth_row_lock_does_not_block_replay(db, request_kind):
    """A lock-footprint witness, not proof of a production writer's lock order."""
    root(db)
    auth = move(db, 'AUTHORIZATION', 'auth')['money_movement_id']
    cap = move(db, 'CAPTURE', 'cap', parent=auth)['money_movement_id']
    if request_kind == 'root_conflict':
        root(db, 'other')
    with db.sessions() as blocker:
        # Deliberately hold AUTH alone. Existing root-first money calls cannot
        # form this schedule; this exposes the newly introduced row dependency.
        blocker.scalar(select(Movement).where(Movement.money_movement_id == auth).with_for_update())
        with db.sessions() as replay:
            replay.execute(text("SET LOCAL lock_timeout='150ms'"))
            start = time.perf_counter()
            try:
                iid = 'other' if request_kind == 'root_conflict' else 'root'
                request = body('CAPTURE', amount=101 if request_kind == 'amount_conflict' else 100, parent=auth)
                if request_kind == 'replay':
                    result = db.service.create_in_session(replay, iid, request, 'cap', 'test')
                    assert result['money_movement_id'] == cap
                    outcome = 'returned'
                else:
                    with pytest.raises(ValueError, match='MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'):
                        db.service.create_in_session(replay, iid, request, 'cap', 'test')
                    outcome = 'idempotency_conflict'
            except DBAPIError as exc:
                pytest.fail('Replay acquired an unrelated history lock: ' + str(exc.orig.sqlstate))
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                replay.rollback()
        blocker.rollback()
    assert move(db, 'CAPTURE', 'cap', parent=auth)['money_movement_id'] == cap
    facts(db)
    output = dict(implementation='candidate' if db.candidate else 'baseline',
                  outcome=outcome, wall_ms=elapsed, lock_timeout_ms=150,
                  production_writer_schedule_proven=False)
    save(db, 'auth-lock-witness-' + request_kind, output)
    print('REPLAY_LOCK', output)


def test_hit_keeps_matching_movement_locked_until_transaction_end(db):
    root(db)
    auth = move(db, 'AUTHORIZATION', 'auth')['money_movement_id']
    cap = move(db, 'CAPTURE', 'cap', parent=auth)['money_movement_id']
    with db.sessions() as hit:
        result = db.service.create_in_session(hit, 'root', body('CAPTURE', parent=auth), 'cap', 'test')
        assert result['money_movement_id'] == cap
        with db.sessions() as contender:
            with pytest.raises(DBAPIError) as error:
                contender.scalar(select(Movement).where(Movement.money_movement_id == cap).with_for_update(nowait=True))
            assert error.value.orig.sqlstate == '55P03'
            contender.rollback()
        hit.rollback()
    with db.sessions() as released:
        assert released.scalar(select(Movement).where(Movement.money_movement_id == cap).with_for_update(nowait=True))


def test_waiting_same_key_sees_committed_hit(db):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from test_correctness import wait_blocked
    root(db)
    ready = threading.Event(); ids = {}
    with db.sessions() as first:
        auth = db.service.create_in_session(first, 'root', body('AUTHORIZATION'), 'auth', 'test')
        def second():
            with db.sessions() as s:
                ids['pid'] = s.scalar(text('SELECT pg_backend_pid()'))
                ready.set()
                result = db.service.create_in_session(s, 'root', body('AUTHORIZATION'), 'auth', 'test')
                s.commit()
                return result
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(second)
            try:
                assert ready.wait(5)
                wait_blocked(db, ids['pid'])
            finally:
                first.commit()
            assert future.result(timeout=10)['money_movement_id'] == auth['money_movement_id']
    assert len(facts(db, captures=0)) == 1


def test_serial_money_slice_budget(db):
    """Five money calls only; no order/API/transport or concurrency load."""
    measurements = []
    for index in range(23):
        iid = f'slice-{index}'
        root(db, iid)
        counts = []
        def count(conn, cursor, statement, parameters, context, many):
            counts.append(statement.split(None, 1)[0])
        event.listen(db.engine, 'after_cursor_execute', count)
        try:
            wall, cpu = time.perf_counter(), time.thread_time()
            auth = move(db, 'AUTHORIZATION', iid + ':auth', iid=iid)['money_movement_id']
            cap = move(db, 'CAPTURE', iid + ':cap', parent=auth, iid=iid)['money_movement_id']
            for _ in range(2):
                assert move(db, 'CAPTURE', iid + ':cap', parent=auth, iid=iid)['money_movement_id'] == cap
            with pytest.raises(ValueError, match='MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'):
                move(db, 'CAPTURE', iid + ':cap', amount=101, parent=auth, iid=iid)
            wall_ms, cpu_ms = (time.perf_counter() - wall) * 1000, (time.thread_time() - cpu) * 1000
        finally:
            event.remove(db.engine, 'after_cursor_execute', count)
        assert len(counts) == (18 if db.candidate else 20)
        if index >= 3:
            measurements.append(dict(wall_ms=wall_ms, calling_thread_cpu_ms=cpu_ms, statements=len(counts)))
    result = dict(implementation='candidate' if db.candidate else 'baseline',
                  warmup=3, samples=measurements, serial_money_slice_only=True,
                  full_transaction_or_abba=False,
                  median_wall_ms=median(x['wall_ms'] for x in measurements),
                  median_calling_thread_cpu_ms=median(x['calling_thread_cpu_ms'] for x in measurements))
    save(db, 'money-slice', result)
    print('MONEY_SLICE', result['implementation'], round(result['median_wall_ms'], 3),
          round(result['median_calling_thread_cpu_ms'], 3), measurements[0]['statements'])
