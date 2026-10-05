"""Disposable PG18.4 diagnostic, not a production/full-transaction benchmark.

No service/SQL/transaction edits. Synthetic confirmed FLIGHT_ORDER intents exercise
real AUTH/CAPTURE/replay. Process CPU covers this one client process, not PG CPU.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from threading import Barrier
from time import perf_counter_ns, process_time_ns
import uuid

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

assert os.environ.get('PGDATABASE') == 'c13_lite', 'Disposable database required'
assert os.environ.get('PGHOST') and os.environ.get('PGUSER'), 'Explicit PG endpoint required'
url = URL.create('postgresql+psycopg', username=os.environ['PGUSER'],
    password=os.environ.get('PGPASSWORD'), host=os.environ['PGHOST'],
    port=int(os.environ.get('PGPORT', '5432')), database='c13_lite')
os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)

from go_hotel.db.models import (OmnichannelPaymentIntentRow as Intent,
    OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Ledger,
    CatalogCreditSourceRow, OrderSupplierFulfillmentRow, OrderSupplierFulfillmentEventRow)
from go_hotel.services.unified_money_movement import UnifiedMoneyMovementService
from go_hotel.payments.money_create_diagnostics import MoneyCreateDiagnostics

schema = 'c11_diag_' + uuid.uuid4().hex
tables = [m.__table__ for m in (Intent, Movement, Ledger, CatalogCreditSourceRow,
    OrderSupplierFulfillmentRow, OrderSupplierFulfillmentEventRow)]
admin = create_engine(url, hide_parameters=True, connect_args={'connect_timeout': 10})
engine = None
service = UnifiedMoneyMovementService()
evidence = {'scope': 'synthetic confirmed FLIGHT_ORDER money graph; not HTTP/full transaction',
    'cpu_scope': 'one Python client process, all worker threads; excludes PostgreSQL',
    'clocks': ['perf_counter_ns wall', 'process_time_ns workload CPU'],
    'pool': {'size': 8, 'max_overflow': 0, 'timeout_seconds': 30, 'pre_ping': False},
    'acquire_scope': 'engine.connect incl checkout/setup; not pure pool queue time',
    'sql_scope': 'DBAPI cursor execute roundtrip, including lock waits; fetch/ORM in hold_other',
    'limitations': ['not ABBA', 'not production data distribution',
        'no server CPU sample', 'no socket disconnect or process-exit fault injection',
        'lost acknowledgement simulated after successful real commit'],
    'runs': []}


def seed(count):
    ids = ['diag_' + uuid.uuid4().hex for _ in range(count)]
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        s.add_all([Intent(payment_intent_id=i, business_type='FLIGHT_ORDER', business_id=i,
            payer_id='diagnostic-payer', payee_id='diagnostic-payee', operation='PAY',
            amount_minor=1000, currency='CNY', channel_priority_json=['MOCK'],
            selected_channel='MOCK', state='SUCCEEDED', idempotency_key=i,
            created_at=now, updated_at=now) for i in ids])
        s.commit()
    return ids


def execute(iid, typ, key, parent=None, enabled=True, amount=1000, rollback=False, lose_ack=False):
    d = MoneyCreateDiagnostics() if enabled else None
    cm = lambda name: getattr(d, name)() if d else nullcontext()
    active = []
    with cm('measure_pool_acquire_wait'):
        conn = engine.connect()
    with cm('measure_connection_hold'):
        # Connection-scoped observers are never attached globally/shared by threads.
        def before(c, cursor, statement, parameters, context, many):
            label = statement.split(None, 1)[0] + ':' + hashlib.sha256(statement.encode()).hexdigest()[:16]
            interval = d.measure_sql_stage(label)
            interval.__enter__(); active.append(interval)

        def after(c, cursor, statement, parameters, context, many):
            active.pop().__exit__(None, None, None)

        if d:
            event.listen(conn, 'before_cursor_execute', before)
            event.listen(conn, 'after_cursor_execute', after)
        s = Session(bind=conn, autoflush=False, expire_on_commit=False)
        try:
            try:
                result = service.create_in_session(s, iid, {
                    'movement_type': typ, 'amount_minor': amount,
                    'parent_movement_id': parent, 'mode': 'CONTRACT_SIMULATOR',
                    'evidence': ['diagnostic://isolated']}, key, 'c11-diagnostic')
                s.flush()
                if rollback:
                    s.rollback()
                else:
                    with cm('measure_commit'): s.commit()
                if lose_ack: raise RuntimeError('SIMULATED_ACK_LOST_AFTER_COMMIT')
            except BaseException:
                # End a failed cursor interval before rollback/connection cleanup.
                while active: active.pop().__exit__(None, None, None)
                s.rollback()
                raise
        finally:
            # An execute error has no after_cursor_execute event: unwind before release.
            while active: active.pop().__exit__(None, None, None)
            if d:
                event.remove(conn, 'before_cursor_execute', before)
                event.remove(conn, 'after_cursor_execute', after)
            s.close()
            conn.close()
    outcome = 'new_auth' if typ == 'AUTHORIZATION' else 'new_capture'
    return result, d.finish(outcome) if d else None


def run(iids, typ, keys, parents, enabled, label):
    n = len(iids); starts = {}
    def start_window():
        starts['cpu'] = process_time_ns(); starts['wall'] = perf_counter_ns()
    barrier = Barrier(n + 1, action=start_window, timeout=30)
    def work(index):
        barrier.wait()
        start = perf_counter_ns()
        result, diagnostic = execute(iids[index], typ, keys[index], parents[index], enabled)
        wall = perf_counter_ns() - start
        if diagnostic:
            diagnostic['outcome'] = label
        return result, diagnostic, wall
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(work, i) for i in range(n)]
        barrier.wait()
        records = [f.result(timeout=60) for f in futures]
        cpu = process_time_ns() - starts['cpu']; wall = perf_counter_ns() - starts['wall']
    assert engine.pool.checkedout() == 0, 'Connection leaked'
    walls = sorted(r[2] for r in records)
    evidence['runs'].append({'concurrency': n, 'operation': label, 'instrumented': enabled,
        'process_cpu_ns': cpu, 'workload_wall_ns': wall,
        'request_p95_ns': walls[math.ceil(n * .95) - 1], 'request_wall_ns': walls,
        'samples': [r[1] for r in records] if enabled else []})
    return [r[0] for r in records]


def verify_graph(iids):
    with Session(engine) as s:
        moves = s.scalars(select(Movement).where(Movement.root_payment_intent_id.in_(iids))).all()
        rows = s.scalars(select(Ledger).where(Ledger.payment_intent_id.in_(iids))).all()
        assert len(moves) == 2 * len(iids) and len(rows) == 2 * len(iids)
        for iid in iids:
            pair = [m for m in moves if m.root_payment_intent_id == iid]
            auth = next(m for m in pair if m.movement_type == 'AUTHORIZATION')
            cap = next(m for m in pair if m.movement_type == 'CAPTURE')
            assert cap.parent_movement_id == auth.money_movement_id
            assert all(m.amount_minor == 1000 and m.state == 'CONFIRMED' for m in pair)
            ledger = [r for r in rows if r.payment_intent_id == iid]
            assert {r.direction for r in ledger} == {'DEBIT', 'CREDIT'}
            assert all(r.amount_minor == 1000 and r.transaction_id == cap.money_movement_id for r in ledger)


try:
    with admin.begin() as c:
        assert c.scalar(text('select current_database()')) == 'c13_lite'
        version = c.scalar(text('show server_version_num'))
        assert str(version) == '180004', 'Exact PostgreSQL18.4 required'
        evidence['postgres_version'] = c.scalar(text('select version()'))
        evidence['settings'] = {k: c.scalar(text('show ' + k)) for k in
            ('max_connections', 'shared_buffers', 'synchronous_commit', 'fsync')}
        c.execute(text('CREATE SCHEMA ' + schema))
    engine = create_engine(url, hide_parameters=True, pool_size=8, max_overflow=0,
        pool_timeout=30, connect_args={'connect_timeout': 10,
        'options': '-csearch_path=' + schema + ' -cstatement_timeout=20000 -clock_timeout=15000'})
    Intent.metadata.create_all(engine, tables=tables)
    # Import/warm actual service paths and all eight physical connections before load.
    warm = seed(1)[0]
    execute(warm, 'AUTHORIZATION', warm + ':warm', enabled=False)
    connections = [engine.connect() for _ in range(8)]
    for c in connections: c.close()
    # Safety before diagnostic workloads; all statements/commits really reach PG.
    iid = seed(1)[0]
    execute(iid, 'AUTHORIZATION', iid + ':auth', rollback=True)
    auth, _ = execute(iid, 'AUTHORIZATION', iid + ':auth')
    caps = run([iid] * 20, 'CAPTURE', [iid + ':cap'] * 20,
        [auth['money_movement_id']] * 20, True, 'concurrent_same_key')
    assert len({r['money_movement_id'] for r in caps}) == 1
    try:
        execute(iid, 'CAPTURE', iid + ':cap', auth['money_movement_id'], amount=999)
        raise AssertionError('Amount conflict accepted')
    except ValueError as exc:
        assert str(exc) == 'MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'
    verify_graph([iid])
    ack_iid = seed(1)[0]
    try:
        execute(ack_iid, 'AUTHORIZATION', ack_iid + ':auth', lose_ack=True)
        raise AssertionError('Fault was not injected')
    except RuntimeError as exc:
        assert str(exc) == 'SIMULATED_ACK_LOST_AFTER_COMMIT'
    ack_auth, _ = execute(ack_iid, 'AUTHORIZATION', ack_iid + ':auth')
    execute(ack_iid, 'CAPTURE', ack_iid + ':cap', ack_auth['money_movement_id'])
    verify_graph([ack_iid])
    evidence['safety'] = ['rollback then retry', 'concurrent same-key capture once',
        'amount conflict refused', 'lost acknowledgement replay', 'balanced ledger', 'pool released']
    for n in (20, 100):
        # Disabled/enabled are diagnostic overhead observations, not an optimization A/B gate.
        for enabled in (False, True):
            ids = seed(n); keys = [i + ':auth' for i in ids]
            auths = run(ids, 'AUTHORIZATION', keys, [None] * n, enabled, 'new_auth')
            auth_replays = run(ids, 'AUTHORIZATION', keys, [None] * n, enabled, 'auth_replay')
            assert auth_replays == auths
            parents = [a['money_movement_id'] for a in auths]; keys = [i + ':cap' for i in ids]
            caps = run(ids, 'CAPTURE', keys, parents, enabled, 'new_capture')
            replays = run(ids, 'CAPTURE', keys, parents, enabled, 'capture_replay')
            assert replays == caps
            verify_graph(ids)
    with engine.connect() as c:
        evidence['row_counts'] = {t.name: c.scalar(select(func.count()).select_from(t)) for t in tables}
        evidence['indexes'] = list(c.execute(text(
            'select tablename,indexdef from pg_indexes where schemaname=:s order by tablename,indexname'),
            {'s': schema}).mappings())
    evidence['indexes'] = [dict(row) for row in evidence['indexes']]
    src = Path(__file__).resolve().parents[2] / 'src/go_hotel'
    evidence['source_sha256'] = {p: hashlib.sha256((src / p).read_bytes()).hexdigest() for p in
        ['payments/money_create_diagnostics.py', 'services/unified_money_movement.py']}
    assert engine.pool.checkedout() == 0
    print('C11_PG_RESULT ' + json.dumps(evidence, sort_keys=True), flush=True)
finally:
    if engine is not None: engine.dispose()
    # Schema is an internally generated identifier; never drop public or supplied names.
    with admin.begin() as c: c.execute(text('DROP SCHEMA IF EXISTS ' + schema + ' CASCADE'))
    admin.dispose()
