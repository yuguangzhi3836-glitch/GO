"""Run outside conftest's SQLite environment; never mistake SQLite for PG proof."""
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest
from go_hotel.payments.money_create_diagnostics import MoneyCreateDiagnostics

pytestmark = pytest.mark.no_db


@pytest.mark.no_db
def test_real_pg18_money_create(capsys):
    if not any(os.getenv(k) for k in ('PGHOST', 'PGDATABASE', 'PGUSER', 'PGPASSWORD')):
        if os.getenv('GITHUB_ACTIONS') == 'true' and os.getenv('PGPORT'):
            pytest.fail('Incomplete C13 PostgreSQL environment')
        pytest.skip('PG deferred: no isolated PostgreSQL environment supplied')
    assert os.environ.get('PGDATABASE') == 'c13_lite', 'Disposable c13_lite required'
    driver = Path(__file__).resolve()
    env = dict(os.environ)
    env.pop('DATABASE_URL', None)
    env['PYTHONPATH'] = str(driver.parents[2] / 'src')
    with tempfile.TemporaryDirectory(prefix='c11-pg-') as directory:
        result = subprocess.run([sys.executable, str(driver)], cwd=directory,
            env=env, text=True, capture_output=True, timeout=240)
    # C13 retains stdout even when pytest's normal passing-output capture is on.
    with capsys.disabled():
        print(result.stdout)
        print(result.stderr)
    assert result.returncode == 0, 'Real PostgreSQL diagnostic child failed; see retained output'
    assert 'C11_PG_RESULT ' in result.stdout



# Deterministic interval accounting, independent of database availability.


class Clock:
    value = 0

    def __call__(self):
        return self.value

    def advance(self, amount):
        self.value += amount


def interval(d, kind):
    return getattr(d, 'measure_' + kind)(*(['SELECT'] if kind == 'sql_stage' else []))


@pytest.mark.parametrize('outer,inner', [
    (None, 'sql_stage'), (None, 'commit'),
    ('pool_acquire_wait', 'connection_hold'), ('connection_hold', 'pool_acquire_wait'),
    ('pool_acquire_wait', 'pool_acquire_wait'), ('connection_hold', 'connection_hold'),
    ('pool_acquire_wait', 'sql_stage'), ('pool_acquire_wait', 'commit'),
    ('sql_stage', 'sql_stage'), ('sql_stage', 'commit'),
    ('commit', 'sql_stage'), ('commit', 'commit'),
    ('sql_stage', 'pool_acquire_wait'), ('commit', 'connection_hold'),
])
def test_invalid_nesting_refused_at_entry(outer, inner):
    d = MoneyCreateDiagnostics()
    with ExitStack() as stack:
        if outer in {'sql_stage', 'commit'}:
            stack.enter_context(d.measure_connection_hold())
        if outer:
            stack.enter_context(interval(d, outer))
        with pytest.raises(ValueError, match='INVALID_INTERVAL_NESTING'):
            with interval(d, inner):
                pytest.fail('invalid body executed')
    d.finish('error')


def test_repeated_cycles_accumulate_and_conserve_wall_time():
    clock = Clock(); d = MoneyCreateDiagnostics(wall_clock=clock)
    for _ in range(2):
        with d.measure_pool_acquire_wait(): clock.advance(3)
        with d.measure_connection_hold():
            with d.measure_sql_stage('SELECT'): clock.advance(5)
            with d.measure_commit(): clock.advance(7)
            clock.advance(11)
        clock.advance(13)
    result = d.finish('new_capture')
    assert {k: result[k] for k in ('wall_total_ns', 'pool_acquire_wait_ns',
        'connection_hold_ns', 'sql_total_ns', 'commit_ns', 'hold_other_ns', 'wall_other_ns')} == {
        'wall_total_ns': 78, 'pool_acquire_wait_ns': 6, 'connection_hold_ns': 46,
        'sql_total_ns': 10, 'commit_ns': 14, 'hold_other_ns': 22, 'wall_other_ns': 26}
    assert len(result['sql_stages']) == 2
    assert not hasattr(d, 'set_commit_ns')
    assert not any('cpu' in key for key in result)


@pytest.mark.parametrize('kind', ['pool_acquire_wait', 'sql_stage', 'commit'])
def test_exception_unwinds_and_still_accumulates(kind):
    clock = Clock(); d = MoneyCreateDiagnostics(wall_clock=clock)
    with pytest.raises(RuntimeError, match='injected'):
        with ExitStack() as stack:
            if kind != 'pool_acquire_wait':
                stack.enter_context(d.measure_connection_hold())
            stack.enter_context(interval(d, kind))
            clock.advance(17)
            raise RuntimeError('injected')
    result = d.finish('error')
    key = {'pool_acquire_wait': 'pool_acquire_wait_ns', 'sql_stage': 'sql_total_ns', 'commit': 'commit_ns'}[kind]
    assert result[key] == 17


def test_finish_open_and_reuse_are_rejected():
    d = MoneyCreateDiagnostics()
    with d.measure_connection_hold():
        with pytest.raises(ValueError, match='INTERVAL_STILL_OPEN'): d.finish('new_auth')
    d.finish('new_auth')
    with pytest.raises(ValueError, match='DIAGNOSTIC_FINISHED'): d.finish('new_auth')
    with pytest.raises(ValueError, match='DIAGNOSTIC_FINISHED'):
        with d.measure_pool_acquire_wait(): pass


def run_pg_driver():
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
    import re
    import selectors
    import signal
    from pathlib import Path
    from threading import Barrier
    from time import perf_counter_ns, process_time_ns, monotonic, sleep
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
            'no server CPU sample', 'faults at known pre/post-commit boundaries, not ambiguous in-flight COMMIT',
            'backend termination closes real socket; not a network-partition simulation'],
        'runs': [], 'fault_cases': [], 'statement_shapes': {}}


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
                shape = hashlib.sha256(statement.encode()).hexdigest()[:16]
                verb = statement.split(None, 1)[0]
                # Only known schema table names, never SQL text or bound values.
                matched = sorted(t.name for t in tables if re.search(r'\b' + t.name + r'\b', statement))
                evidence['statement_shapes'][shape] = {'verb': verb, 'tables': matched}
                label = verb + ':' + shape
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


    def verify_fault(mode, typ, boundary):
        iid = seed(1)[0]
        parent = None
        if typ == 'CAPTURE':
            auth, _ = execute(iid, 'AUTHORIZATION', iid + ':auth')
            parent = auth['money_movement_id']
        key = iid + (':auth' if typ == 'AUTHORIZATION' else ':cap')
        tag = schema + '_' + uuid.uuid4().hex[:8]
        payload = dict(schema=schema, iid=iid, key=key, typ=typ, parent=parent,
            boundary=boundary, tag=tag)
        env = dict(os.environ, C11_FAULT_SPEC=json.dumps(payload))
        worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--fault-worker'],
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(worker.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=30), 'Fault worker did not reach boundary'
                line = worker.stdout.readline()
            assert line.startswith('C11_FAULT_READY '), 'Worker failed before fault boundary'
            ready = json.loads(line.removeprefix('C11_FAULT_READY '))
            assert ready['boundary'] == boundary
            backend = ready['backend_pid']
            with admin.connect() as c:
                # Ownership proof before either kind of destructive fault injection.
                assert c.scalar(text('select count(*) from pg_stat_activity where pid=:p '
                    'and datname=:d and application_name=:a'),
                    dict(p=backend, d='c13_lite', a=tag)) == 1
            if mode == 'socket_disconnect':
                with admin.connect() as c:
                    terminated = c.scalar(text('select pg_terminate_backend(pid) from pg_stat_activity '
                        'where pid=:p and datname=:d and application_name=:a'),
                        dict(p=backend, d='c13_lite', a=tag))
                    assert terminated is True
                deadline = monotonic() + 10
                while True:
                    with admin.connect() as c:
                        still_alive = c.scalar(text('select count(*) from pg_stat_activity '
                            'where pid=:p and application_name=:a'), dict(p=backend, a=tag))
                    if not still_alive: break
                    assert monotonic() < deadline, 'Backend termination did not complete'
                    sleep(.05)
                stdout, stderr = worker.communicate('resume\n', timeout=20)
                assert worker.returncode == 0, 'Disconnect worker failed: ' + stderr[-1000:]
                outcome = json.loads(stdout.strip().removeprefix('C11_FAULT_OBSERVED '))
                assert outcome['connection_invalidated'] is True
                assert outcome['checkedout'] == 0 and outcome['fresh_connection_ok'] is True
            else:
                worker.kill()  # Real SIGKILL: no Python finally, rollback or atexit.
                worker.communicate(timeout=20)
                assert worker.returncode == -signal.SIGKILL
                outcome = {'signal': 'SIGKILL'}
            # Wait only for this owned backend, then prove durable state before retry.
            deadline = monotonic() + 10
            while True:
                with admin.connect() as c:
                    alive = c.scalar(text('select count(*) from pg_stat_activity where pid=:p '
                        'and application_name=:a'), dict(p=backend, a=tag))
                if not alive: break
                assert monotonic() < deadline, 'Fault backend still holds resources'
                sleep(.05)
            with Session(engine) as s:
                before = s.scalar(select(Movement).where(Movement.idempotency_key == key))
                assert (before is not None) == (boundary == 'after_commit')
                if before: assert before.money_movement_id == ready['movement_id']
                ledger_count = s.scalar(select(func.count()).select_from(Ledger).where(Ledger.payment_intent_id == iid))
                assert ledger_count == (2 if typ == 'CAPTURE' and boundary == 'after_commit' else 0)
            # Recovery uses a new session/connection and identical business request.
            recovered, _ = execute(iid, typ, key, parent)
            replay, _ = execute(iid, typ, key, parent)
            assert replay == recovered
            if boundary == 'after_commit': assert recovered['money_movement_id'] == ready['movement_id']
            try:
                execute(iid, typ, key, parent, amount=999)
                raise AssertionError('Changed amount accepted after recovery')
            except ValueError as exc:
                assert str(exc) == 'MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'
            if typ == 'AUTHORIZATION':
                execute(iid, 'CAPTURE', iid + ':cap', recovered['money_movement_id'])
            verify_graph([iid])
            assert engine.pool.checkedout() == 0
            evidence['fault_cases'].append(dict(mode=mode, operation=typ, boundary=boundary,
                durable_before_retry=boundary == 'after_commit', ledger_before_retry=ledger_count,
                replay_same_id=True, amount_conflict_refused=True, balanced_graph=True,
                backend_gone=True, pool_released=True, observed=outcome))
        finally:
            if worker.poll() is None:
                worker.kill(); worker.communicate(timeout=10)


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
        for mode in ('socket_disconnect', 'process_exit'):
            for typ in ('AUTHORIZATION', 'CAPTURE'):
                for boundary in ('before_commit', 'after_commit'):
                    verify_fault(mode, typ, boundary)
        assert len(evidence['fault_cases']) == 8
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


def run_fault_worker():
    """Owned disposable backend only; parent coordinates fault at a proven barrier."""
    import json
    import re
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session

    spec = json.loads(os.environ['C11_FAULT_SPEC'])
    assert os.environ.get('PGDATABASE') == 'c13_lite'
    assert re.fullmatch(r'c11_diag_[0-9a-f]{32}', spec['schema'])
    assert re.fullmatch(re.escape(spec['schema']) + r'_[0-9a-f]{8}', spec['tag'])
    assert spec['boundary'] in ('before_commit', 'after_commit')
    url = URL.create('postgresql+psycopg', username=os.environ['PGUSER'],
        password=os.environ.get('PGPASSWORD'), host=os.environ['PGHOST'],
        port=int(os.environ.get('PGPORT', '5432')), database='c13_lite')
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    from go_hotel.services.unified_money_movement import UnifiedMoneyMovementService

    engine = create_engine(url, hide_parameters=True, pool_size=1, max_overflow=0,
        pool_timeout=5, connect_args={'connect_timeout': 10, 'application_name': spec['tag'],
        'options': '-csearch_path=' + spec['schema'] + ' -cstatement_timeout=15000 -clock_timeout=10000'})
    try:
        with engine.connect() as conn:
            backend = conn.scalar(text('select pg_backend_pid()'))
            assert conn.scalar(text('show server_version_num')) == '180004'
            conn.rollback()  # Session below must own its transaction/commit.
            with Session(bind=conn, autoflush=False, expire_on_commit=False) as s:
                result = UnifiedMoneyMovementService().create_in_session(s, spec['iid'], {
                    'movement_type': spec['typ'], 'amount_minor': 1000,
                    'parent_movement_id': spec['parent'], 'mode': 'CONTRACT_SIMULATOR',
                    'evidence': ['diagnostic://isolated-fault']}, spec['key'], 'c11-fault')
                if spec['boundary'] == 'after_commit': s.commit()
                print('C11_FAULT_READY ' + json.dumps(dict(backend_pid=backend,
                    boundary=spec['boundary'], movement_id=result['money_movement_id'])), flush=True)
                assert sys.stdin.readline().strip() == 'resume'
                try:
                    if spec['boundary'] == 'before_commit': s.commit()
                    else: s.execute(text('select 1'))
                    raise AssertionError('Real disconnect was not observed')
                except DBAPIError as exc:
                    assert exc.connection_invalidated
                    s.rollback()
        assert engine.pool.checkedout() == 0
        with engine.connect() as fresh:
            assert fresh.scalar(text('select 1')) == 1
        print('C11_FAULT_OBSERVED ' + json.dumps(dict(connection_invalidated=True,
            checkedout=engine.pool.checkedout(), fresh_connection_ok=True)), flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    if sys.argv[1:] == ['--fault-worker']: run_fault_worker()
    else: run_pg_driver()
