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
        if statement.startswith('SELECT'):
            statements.append((statement, parameters, cursor.rowcount))
    event.listen(db.engine, 'after_cursor_execute', record)
    try:
        move(db, 'CAPTURE', 'cap', parent=auth)
    finally:
        event.remove(db.engine, 'after_cursor_execute', record)
    assert len(statements) == 2
    assert statements[1][2] == (history_size if db.candidate else 1)
    sql, parameters, _ = statements[1]
    with db.engine.connect() as c:
        cursor = c.connection.cursor()
        cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql, parameters)
        plan = cursor.fetchone()[0]
        cursor.close()
        c.rollback()
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


def test_unrelated_auth_row_lock_changes_replay_dependency(db):
    """A lock-footprint witness, not proof of a production writer's lock order."""
    root(db)
    auth = move(db, 'AUTHORIZATION', 'auth')['money_movement_id']
    cap = move(db, 'CAPTURE', 'cap', parent=auth)['money_movement_id']
    with db.sessions() as blocker:
        # Deliberately hold AUTH alone. Existing root-first money calls cannot
        # form this schedule; this exposes the newly introduced row dependency.
        blocker.scalar(select(Movement).where(Movement.money_movement_id == auth).with_for_update())
        with db.sessions() as replay:
            replay.execute(text("SET LOCAL lock_timeout='150ms'"))
            start = time.perf_counter()
            try:
                result = db.service.create_in_session(replay, 'root', body('CAPTURE', parent=auth), 'cap', 'test')
                assert result['money_movement_id'] == cap
                outcome = 'returned'
                assert not db.candidate
            except DBAPIError as exc:
                assert db.candidate
                assert exc.orig.sqlstate == '55P03'
                outcome = 'lock_timeout_55P03'
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                replay.rollback()
        blocker.rollback()
    assert move(db, 'CAPTURE', 'cap', parent=auth)['money_movement_id'] == cap
    facts(db)
    output = dict(implementation='candidate' if db.candidate else 'baseline',
                  outcome=outcome, wall_ms=elapsed, lock_timeout_ms=150,
                  production_writer_schedule_proven=False)
    save(db, 'auth-lock-witness', output)
    print('REPLAY_LOCK', output)
