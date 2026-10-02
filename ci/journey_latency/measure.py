"""Two persistent processes per operation; separate process-cold and continued batches.

This supplements, and never changes or passes, the original formal staircase.
No warmup is discarded: batch 0 and all three subsequent batches are retained.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import threading
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'application'
sys.path.insert(0, str(ROOT / 'ci/multi_instance'))
from run import guard, write, imports

TIERS = (20, 100)
BATCHES = 4
OPERATIONS = ('create_order', 'payment_confirm', 'order_query')


def summarize(rows):
    assert rows and all(r['end_ns'] >= r['start_ns'] for r in rows), 'INVALID_TIMING'
    values = sorted((r['end_ns'] - r['start_ns']) / 1e6 for r in rows)
    events = sorted([(r['start_ns'], 1) for r in rows] + [(r['end_ns'], -1) for r in rows])
    active = peak = 0
    for _, delta in events:
        active += delta
        peak = max(peak, active)
    seconds = (max(r['end_ns'] for r in rows) - min(r['start_ns'] for r in rows)) / 1e9
    return {'requests': len(rows), 'errors': sum(not r['ok'] for r in rows),
        'p50_ms': values[math.ceil(len(values) * .5) - 1],
        'p95_ms': values[math.ceil(len(values) * .95) - 1],
        'p99_ms': values[math.ceil(len(values) * .99) - 1],
        'max_ms': values[-1], 'observed_peak_inflight': peak,
        'batch_span_seconds': seconds,
        'successful_per_second_in_burst': sum(r['ok'] for r in rows) / seconds,
        'pids': sorted({r['pid'] for r in rows})}


def cpu():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def wait(path, processes=(), timeout=120):
    until = time.monotonic() + timeout
    while not path.exists():
        assert all(p.poll() is None for p in processes), 'WORKER_EXITED_EARLY'
        if time.monotonic() > until:
            raise TimeoutError('JOURNEY_BARRIER_TIMEOUT')
        time.sleep(.005)


def atomic(path, data):
    temporary = path.with_name(path.name + '.tmp')
    write(temporary, data)
    temporary.replace(path)



def synchronized_batch(pool, tasks, invoke, ready_file, start_file):
    """One release watcher per process; request clocks stay inside invoke.

    A shared coordinator marker releases both processes. Never hold request
    completion or move its start clock before admission to fabricate overlap.
    """
    barrier = threading.Barrier(len(tasks) + 1)
    released = threading.Event()
    cancelled = threading.Event()
    def admitted(task):
        barrier.wait(60)
        if not released.wait(130):
            raise TimeoutError('JOURNEY_RELEASE_TIMEOUT')
        if cancelled.is_set():
            raise RuntimeError('JOURNEY_RELEASE_CANCELLED')
        return invoke(task)
    futures = [pool.submit(admitted, task) for task in tasks]
    try:
        barrier.wait(60)
        atomic(ready_file, {'pid': os.getpid()})
        wait(start_file)
    except BaseException:
        cancelled.set()
        barrier.abort()
        raise
    finally:
        released.set()
    return [future.result() for future in futures]


def worker(job_path):
    started = time.monotonic_ns(); initial_cpu = cpu()
    imports()
    from operations import Operations
    from go_hotel.db.session import engine
    operations = Operations()
    # Imports construct an engine but do not open its connections or configure mappers.
    assert engine.pool.size() == int(os.environ['DATABASE_POOL_SIZE']) and engine.pool.checkedout() == 0
    assert engine.pool.checkedin() == 0, 'COLD_POOL_ALREADY_USED'
    from sqlalchemy.orm import Mapper
    # Passive inspection only: querying mapper.configured does not initialize it.
    from go_hotel.db.models import Base
    configured = sum(m.configured for m in Base.registry.mappers)
    assert configured == 0, 'COLD_MAPPERS_ALREADY_CONFIGURED'
    job = json.loads(job_path.read_text()); directory = Path(job['directory'])
    startup = {'pid': os.getpid(), 'child_entry_ns': started,
        'ready_ns': time.monotonic_ns(), 'import_cpu_seconds': cpu() - initial_cpu,
        'initial_pool_connections': engine.pool.checkedin(), 'initial_configured_mappers': configured,
        'scope': 'Application imports only; interpreter launch is measured by coordinator'}
    atomic(directory / 'startup.json', startup)
    workers = len(job['batches'][0])
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for number, tasks in enumerate(job['batches']):
                assert len(tasks) == workers
                def request(task):
                    start = time.monotonic_ns()
                    row = {'pid': os.getpid(), 'owner': task['owner'], 'start_ns': start,
                        'operation': job['operation'], 'batch': number, 'ok': False}
                    try:
                        row['value'] = operations.execute(job['operation'], task)
                        row['ok'] = True
                    except Exception as exc:
                        # Never expose database URLs or arbitrary exception text.
                        row['error_type'] = type(exc).__name__
                    row['end_ns'] = time.monotonic_ns()
                    row['duration_ms'] = (row['end_ns'] - start) / 1e6
                    return row
                before = cpu()
                rows = synchronized_batch(pool, tasks, request,
                    directory / f'batch-{number}.ready',
                    Path(job['release_directory']) / f'batch-{number}.start')
                atomic(directory / f'batch-{number}.json', {'rows': rows,
                    'process_cpu_seconds': cpu() - before,
                    'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
                if any(not row['ok'] for row in rows):
                    raise AssertionError('OPERATION_FAILED')
    finally:
        engine.dispose()


def measure(operation, batches, directory):
    directory.mkdir()
    processes = []; launches = []; result = []
    instances = int(os.environ.get('GO_JOURNEY_INSTANCES', '2'))
    assert instances in (2, 4), 'INVALID_JOURNEY_INSTANCE_COUNT'
    try:
        for index in range(instances):
            child_dir = directory / f'worker-{index}'; child_dir.mkdir()
            job = {'directory': str(child_dir), 'release_directory': str(directory), 'operation': operation,
                'batches': [batch[index::instances] for batch in batches]}
            path = child_dir / 'job.json'; write(path, job)
            with (child_dir / 'worker.log').open('w') as log:
                launched = time.monotonic_ns()
                p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', str(path)],
                    stdout=log, stderr=subprocess.STDOUT)
            processes.append(p); launches.append(launched)
        startups = []
        for index in range(instances):
            path = directory / f'worker-{index}' / 'startup.json'; wait(path, processes)
            startup = json.loads(path.read_text())
            startup['launch_ns'] = launches[index]
            startup['process_launch_to_ready_ms'] = (startup['ready_ns'] - launches[index]) / 1e6
            startups.append(startup)
        write(directory / 'startups.json', startups)
        for number, tasks in enumerate(batches):
            for index in range(instances):
                wait(directory / f'worker-{index}/batch-{number}.ready', processes)
            release_ns = time.monotonic_ns()
            (directory / f'batch-{number}.start').touch()
            rows = []; counters = []
            for index in range(instances):
                path = directory / f'worker-{index}/batch-{number}.json'
                # A worker may exit successfully immediately after its last result.
                wait(path)
                data = json.loads(path.read_text()); rows += data['rows']; counters.append(data)
            assert len(rows) == len(tasks) and {r['owner'] for r in rows} == {t['owner'] for t in tasks}
            assert all(r['start_ns'] >= release_ns for r in rows), 'RELEASE_TIMING'
            item = {'batch': number, 'mode': 'PROCESS_COLD_FIRST_BATCH' if number == 0 else 'CONTINUED_PROCESS',
                'requested_concurrency': len(tasks), 'release_ns': release_ns, **summarize(rows),
                'process_cpu_seconds': sum(c['process_cpu_seconds'] for c in counters),
                'max_worker_rss_kib': max(c['peak_rss_kib'] for c in counters)}
            assert item['pids'] == sorted(p.pid for p in processes), 'WORKER_PID_CHANGED'
            write(directory / f'batch-{number}-raw.json', rows)
            write(directory / f'batch-{number}-summary.json', item)
            result.append({'summary': item, 'rows': rows})
            assert item['errors'] == 0, 'NORMAL_OPERATION_FAILED'
        for p in processes:
            assert p.wait(timeout=30) == 0, 'WORKER_FAILED'
        return result
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill(); p.wait()


def coordinator(out):
    imports()
    from go_hotel.db.models import Base
    from go_hotel.db.session import engine
    from go_hotel.mobility.ride.service import ride_service
    from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier
    from go_hotel.api.routes.mobility import order
    from fastapi import HTTPException
    from types import SimpleNamespace
    import ride_workload
    Base.metadata.create_all(engine)
    result = {'status': 'RUNNING', 'operations': [], 'checks': [], 'normal_actor_count': 0,
        'scope': 'Service/route function latency; no HTTP, authentication, external PSP or supplier latency',
        'phase_totals_are_not_a_journey_percentile': True,
        'cold_scope': 'New application process, no mapper configuration or pool connections; DB/OS caches are not cold',
        'continued_scope': 'Three subsequent bursts on identical worker PIDs and pools; not a long-duration soak'}
    cumulative = []
    try:
        for n in TIERS:
            folder = out / f'tier-{n}'; folder.mkdir()
            pickup = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
            offer = ride_service.search('ISOLATED_A', 'ISOLATED_B', pickup, 'CNY')[0]
            body = {'offer_id': 'ride_standard', 'pickup': 'ISOLATED_A', 'dropoff': 'ISOLATED_B',
                'pickup_at': pickup, 'currency': 'CNY',
                'cancellation_policy_hash': offer['cancellation']['policy_hash'],
                'passengers': [{'full_name': 'ISOLATED JOURNEY TEST'}]}
            batches = []
            for batch in range(BATCHES):
                batches.append([{'owner': f'mi-load-journey-{n}-{batch}-{i}',
                    'key': f'journey-{n}-{batch}-{i}', 'body': body} for i in range(n)])
            created = measure('create_order', batches, folder / 'create_order')
            payment_tasks = [[r['value'] for r in batch['rows']] for batch in created]
            paid = measure('payment_confirm', payment_tasks, folder / 'payment_confirm')
            # Supplier/fulfillment are explicit untimed fixtures for completed-order reads.
            # They are still validated with the frozen full ledger verifier below.
            values = [r['value'] for batch in paid for r in batch['rows']]
            for value in values:
                oid = value['order_id']; owner = value['owner']
                supplier.record_supplier_fact(value['supplier_fulfillment_id'], {
                    'state': 'SUPPLIER_CONFIRMED', 'external_operation_id': owner + '-supplier',
                    'supplier_confirmation_reference': owner,
                    'evidence_reference': 'isolated://journey/supplier/' + oid})
                ride_service.fulfill(owner, oid, 'START', 'isolated://journey/start/' + oid)
                ride_service.fulfill(owner, oid, 'COMPLETE', 'isolated://journey/complete/' + oid)
            queried = measure('order_query', payment_tasks, folder / 'order_query')
            cumulative += values
            full_tasks = [[{'owner': f'mi-load-journey-full-{n}-{batch}-{i}',
                'index': f'journey-full-{n}-{batch}-{i}'} for i in range(n)]
                for batch in range(BATCHES)]
            full = measure('full_transaction', full_tasks, folder / 'full_transaction')
            cumulative += [row['value'] for batch in full for row in batch['rows']]
            result['operations'].append({'concurrency': n, 'operation': 'full_transaction',
                'batches': [x['summary'] for x in full]})
            facts = ride_workload.verify(cumulative)
            assert len(facts) == len(cumulative)
            write(folder / 'ledger-facts.json', facts)
            # Direct function call still enforces business ownership (HTTP auth is excluded).
            try:
                order(values[0]['order_id'], SimpleNamespace(user_id='isolated-wrong-owner'))
            except HTTPException as exc:
                assert exc.status_code == 404, 'WRONG_OWNER_WRONG_STATUS'
            else:
                raise AssertionError('WRONG_OWNER_READ_ACCEPTED')
            for operation, data in zip(OPERATIONS, (created, paid, queried)):
                result['operations'].append({'concurrency': n, 'operation': operation,
                    'batches': [x['summary'] for x in data]})
            result['checks'].append({'concurrency': n, 'sql': 'PASS', 'ownership_denial': 'PASS',
                'cumulative_orders': len(cumulative)})
            result['normal_actor_count'] += n * BATCHES
            result['completed_actor_count'] = len(cumulative)
            write(out / 'result.json', result)
        result['status'] = 'MEASUREMENT_COMPLETE_NOT_CAPACITY_ACCEPTANCE'
        return 0
    except Exception as exc:
        result.update(status='FAILED', error_type=type(exc).__name__)
        raise
    finally:
        write(out / 'result.json', result); engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--coordinator', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--application-tree')
    parser.add_argument('--instances-per-operation', type=int, choices=(2, 4), default=2)
    parser.add_argument('--pool-per-instance', type=int, choices=(4, 5), default=5)
    args = parser.parse_args()
    sys.addaudithook(guard)
    if args.worker:
        worker(args.worker); return 0
    if args.coordinator:
        return coordinator(args.coordinator)
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from importlib.metadata import version
    frozen = json.loads(Path(__file__).with_name('baseline.json').read_text())
    for file, digest in frozen['frozen_sha256'].items():
        assert hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == digest, 'FORMAL_BASELINE_CHANGED'
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    app = subprocess.check_output(['git', 'rev-parse', 'HEAD:application'], cwd=ROOT, text=True).strip()
    assert head == os.environ['EXPECTED_HEAD'] and app == (args.application_tree or frozen['application_tree'])
    url = make_url(os.environ['GO_MULTI_DATABASE_URL'])
    assert (url.drivername, url.host, url.port, url.username, url.database) == (
        'postgresql+psycopg', '127.0.0.1', 5432, 'go_ci', 'go_c11_isolated') and not url.query
    if (args.instances_per_operation, args.pool_per_instance) != (2, 5) and args.out is None:
        parser.error('Non-default journey configuration requires a separate output directory')
    out = args.out or ROOT / 'journey-latency-evidence'; out.mkdir(exist_ok=False)
    schema = 'mi_' + uuid4().hex; engine = create_engine(url); code = 1
    binding = {'head': head, 'application_tree': app, 'baseline': frozen,
        'tiers': TIERS, 'batches_per_operation': BATCHES, 'instances_per_operation': args.instances_per_operation,
        'pool_per_instance': args.pool_per_instance, 'max_overflow': 0, 'schema': schema,
        'python': sys.version, 'platform': platform.platform(), 'cpu_count': os.cpu_count(),
        'cpu_model': next((s.split(':', 1)[1].strip() for s in Path('/proc/cpuinfo').read_text().splitlines()
                           if s.startswith('model name')), None),
        'packages': {p: version(p) for p in ('sqlalchemy', 'psycopg', 'fastapi', 'pydantic')},
        'harness_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(__file__).parent.glob('*') if p.is_file()},
        'original_formal_p95_ms': 5000, 'original_formal_p99_ms': 10000,
        'formal_result': 'UNCHANGED_NOT_EVALUATED_BY_THIS_SUPPLEMENT',
        'supplier_and_psp': 'SIMULATED', 'http_auth_network': 'NOT_MEASURED'}
    try:
        with engine.begin() as c:
            binding['postgresql'] = c.scalar(text('select version()'))
            c.execute(text('CREATE SCHEMA ' + schema))
        write(out / 'binding.json', binding)
        env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'TZ') if k in os.environ}
        env.update(DATABASE_URL=url.update_query_dict({'options': '-csearch_path=' + schema +
            ' -cstatement_timeout=15000 -clock_timeout=10000 -cidle_in_transaction_session_timeout=30000',
            'connect_timeout': '5'}).render_as_string(hide_password=False),
            APP_ENV='test', MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false', TRAVEL_INTELLIGENCE_ENABLED='false',
            DATABASE_POOL_SIZE=str(args.pool_per_instance), DATABASE_MAX_OVERFLOW='0', DATABASE_POOL_TIMEOUT_SECONDS='10',
            GO_JOURNEY_INSTANCES=str(args.instances_per_operation),
            PYTHONPATH=str(APP / 'src'),
            GO_RIDE_ISOLATED_CANCELLATION_POLICY_FILE=str(APP / 'scripts/fixtures/ride-cancellation.synthetic.json'))
        with (out / 'coordinator.log').open('w') as log:
            p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--coordinator', str(out)],
                env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = p.wait(timeout=900)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL); p.wait(); code = 124
    finally:
        with engine.begin() as c:
            c.execute(text('DROP SCHEMA IF EXISTS ' + schema + ' CASCADE'))
        engine.dispose()
        write(out / 'exit.json', {'exit_code': code})
        write(out / 'SHA256.json', {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob('*') if p.is_file() and p.name != 'SHA256.json'})
    return code


if __name__ == '__main__':
    raise SystemExit(main())
