"""Isolated attribution, not the formal staircase or a capacity acceptance gate.

The original multi_instance/run.py and its latency/SQL gates are unchanged.
Control/observed/observed/control rounds estimate this observer's perturbation.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'application'
MULTI = ROOT / 'ci/multi_instance'
sys.path.insert(0, str(MULTI))
spec = importlib.util.spec_from_file_location('multi_base', MULTI / 'run.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
from observe import ClientEvents, Sampler, cpu_delta, process_snapshot, statement_delta, statement_snapshot

write = base.write
read = lambda path: json.loads(Path(path).read_text())


def child(path):
    job = read(path)
    base.imports()
    events = None
    if job.get('observe') and job.get('cost_window'):
        from go_hotel.db.session import engine
        events = ClientEvents(engine)
    base.child(path)
    # Keep service processes and pool backends alive until the shared end sample.
    if job.get('cost_window'):
        Path(job['result'] + '.done').touch()
        base.wait_file(Path(job['result'] + '.release'))
        if events:
            write(Path(job['result'] + '.events.json'), events.snapshot())


class Runner(base.Runner):
    def __init__(self, out, observer=None, observe=False):
        super().__init__(out)
        self.observer = observer
        self.observe = observe
        self.last_window = None

    def launch(self, tasks):
        self.counter += 1
        stem = self.out / f'group-{self.counter}'
        job = {'tasks': tasks, 'start': str(stem) + '.start', 'ready': str(stem) + '.ready',
               'result': str(stem) + '.json',
               'cost_window': all(t['op'] == 'ride' for t in tasks), 'observe': self.observe}
        path = Path(str(stem) + '.job')
        write(path, job)
        with Path(str(stem) + '.log').open('w') as log:
            proc = subprocess.Popen([sys.executable, __file__, '--child', str(path)],
                                    stdout=log, stderr=subprocess.STDOUT)
        self.processes.append(proc)
        return proc, job

    def group(self, tasks):
        if not all(t['op'] == 'ride' for t in tasks):
            return super().group(tasks)
        jobs = [self.launch(tasks[i::2]) for i in range(2)]
        sampler = None
        try:
            for proc, job in jobs:
                base.wait_file(Path(job['ready']))
            pids = [p.pid for p, j in jobs]
            pgpid = int(os.environ['GO_COST_POSTGRES_PID'])
            before_stats = statement_snapshot(self.observer)
            sampler = Sampler(self.observer, pids, pgpid) if self.observe else None
            # Bounds are sampled after all workers are ready, before any release.
            before = process_snapshot(pids, pgpid)
            release_ns = time.monotonic_ns()
            if sampler:
                sampler.start()
            for proc, job in jobs:
                Path(job['start']).touch()
            for proc, job in jobs:
                base.wait_file(Path(job['result'] + '.done'))
            if sampler:
                sampler.stop()
            after = process_snapshot(pids, pgpid)
            after_stats = statement_snapshot(self.observer)
            rows = [row for proc, job in jobs for row in read(job['result'])]
            assert all(before['end_ns'] <= r['start_ns'] <= r['end_ns'] <= after['start_ns'] for r in rows)
            assert len(rows) == len(tasks) and len({r['pid'] for r in rows}) == 2
            self.last_window = {'release_ns': release_ns, 'before': before, 'after': after,
                'elapsed_seconds': (after['start_ns'] - before['end_ns']) / 1e9,
                'application_cpu': cpu_delta(before, after, 'apps'),
                'postgres_process_cpu_including_observer': cpu_delta(before, after, 'postgres', strict=False),
                'postgres_cgroup_cpu_delta': {k: after['postgres_cgroup_cpu'][k] - v
                    for k, v in before['postgres_cgroup_cpu'].items()},
                'server_statements': statement_delta(before_stats, after_stats),
                'server_before': before_stats, 'server_after': after_stats,
                'sampler': sampler.summary() if sampler else None,
                'samples': sampler.rows if sampler else [],
                'boundary_note': 'One host monotonic clock; snapshots bracket every actor. '
                    'Worker imports are excluded. Window includes release skew and completion detection. '
                    'Postgres CPU includes observer backend and background processes. '
                    'Snapshot read spans and 10ms CPU ticks bound measurement resolution.'}
            for proc, job in jobs:
                Path(job['result'] + '.release').touch()
                assert proc.wait(timeout=60) == 0
            return rows
        finally:
            if sampler and sampler.thread.is_alive():
                sampler.stop()
            for proc, job in jobs:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()


def round_record(number, observation_mode, schema, result):
    return {**result, 'diagnostic_mode': result['mode'], 'number': number,
            'mode': observation_mode, 'schema': schema}


def stage_summary(rows):
    n = len(rows)
    latency = sorted(r['duration_ms'] for r in rows)
    events = sorted([(r['start_ns'], 1) for r in rows] + [(r['end_ns'], -1) for r in rows])
    active = peak = 0
    for stamp, change in events:
        active += change
        peak = max(peak, active)
    assert peak == n, 'INVALID_BURST_OVERLAP'
    result = {'actors': n, 'p95_ms': latency[math.ceil(n * .95) - 1],
              'p99_ms': latency[math.ceil(n * .99) - 1], 'peak_inflight': peak,
              'start_skew_ms': (max(r['start_ns'] for r in rows) - min(r['start_ns'] for r in rows)) / 1e6,
              'errors': sum(not r['ok'] for r in rows)}
    result['within_original_latency_limits'] = result['p95_ms'] <= 5000 and result['p99_ms'] <= 10000
    return result


def lifespan_probe(out):
    import asyncio
    from go_hotel.db.models import Base
    from sqlalchemy import event
    from sqlalchemy.orm import Mapper
    start = time.monotonic_ns()
    events = []
    @event.listens_for(Mapper, 'before_configured')
    def before(): events.append({'event': 'before_configured', 'at_ns': time.monotonic_ns()})
    @event.listens_for(Mapper, 'after_configured')
    def after(): events.append({'event': 'after_configured', 'at_ns': time.monotonic_ns()})
    def count(): return sum(m.configured for m in Base.registry.mappers)
    result = {'configured_before_main_import': count(), 'total_mappers': len(list(Base.registry.mappers))}
    from go_hotel.main import app
    result['configured_after_main_import'] = count()
    async def probe():
        entered = time.monotonic_ns()
        async with app.router.lifespan_context(app):
            result.update(configured_at_ready=count(), lifespan_to_ready_ms=(time.monotonic_ns()-entered)/1e6,
                          import_and_lifespan_ms=(time.monotonic_ns()-start)/1e6)
    asyncio.run(probe())
    result.update(events=events, note='Real FastAPI lifespan, background expiry workers disabled only '
                  'for isolation. No HTTP latency/capacity claim; this verifies mapper timing on target packages.')
    write(out, result)


def coordinator(out):
    base.imports()
    import psycopg
    from sqlalchemy.engine import make_url
    from go_hotel.db.models import Base
    from go_hotel.db.session import engine
    from ride_workload import verify
    Base.metadata.create_all(engine)
    url = make_url(os.environ['DATABASE_URL'])
    with psycopg.connect(host=url.host, port=url.port, user=url.username, password=url.password,
                         dbname=url.database, autocommit=True, application_name='go_cost_observer') as conn:
        conn.execute("SET pg_stat_statements.track='none'")
        runner = Runner(out, conn, os.environ['GO_COST_OBSERVE'] == '1')
        result = {'mode': 'SAME_WINDOW_DIAGNOSTIC_NOT_ACCEPTANCE', 'stages': [], 'correctness': 'PENDING'}
        try:
            # Every fresh schema retains the complete multi-instance prerequisite.
            base.correctness(runner, out)
            result['correctness'] = 'PASS'
            raw = []
            for n in (20, 100):
                rows = runner.group([{'op': 'ride', 'index': i} for i in range(len(raw), len(raw) + n)])
                write(out / f'load-{n}.json', rows)
                write(out / f'window-{n}.json', runner.last_window)
                assert all(r['ok'] for r in rows), 'ACTOR_ERROR'
                raw.extend(r['value'] for r in rows)
                facts = verify(raw)
                write(out / f'ride-sql-{n}.json', facts)
                stage = stage_summary(rows)
                stage['sql'] = 'PASS'
                result['stages'].append(stage)
                if not stage['within_original_latency_limits']:
                    break
            # Fresh process: prove actual target startup configuration separately.
            with (out / 'lifespan.log').open('w') as log:
                subprocess.run([sys.executable, __file__, '--lifespan', str(out / 'lifespan.json')],
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
            result['status'] = 'DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE'
        finally:
            runner.stop()
            write(out / 'result.json', result)
            engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', type=Path)
    parser.add_argument('--coordinator', type=Path)
    parser.add_argument('--lifespan', type=Path)
    args = parser.parse_args()
    sys.addaudithook(base.guard)
    if args.child: child(args.child); return
    if args.coordinator: coordinator(args.coordinator); return
    if args.lifespan: lifespan_probe(args.lifespan); return
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from importlib.metadata import version
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    assert head == os.environ['EXPECTED_HEAD']
    url = make_url(os.environ['GO_MULTI_DATABASE_URL'])
    assert (url.drivername, url.host, url.port, url.username, url.database) == (
        'postgresql+psycopg', '127.0.0.1', 5432, 'go_ci', 'go_c11_isolated') and not url.query
    out = ROOT / 'cost-attribution-evidence'
    out.mkdir(exist_ok=False)
    engine = create_engine(url)
    summary = {'head': head, 'application_tree': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD:application'], cwd=ROOT, text=True).strip(),
        'order': ['control', 'observed', 'observed', 'control'], 'rounds': [],
        'python': sys.version, 'platform': platform.platform(), 'cpu_count': os.cpu_count(),
        'packages': {p: version(p) for p in ('sqlalchemy', 'psycopg', 'fastapi')},
        'pool_per_instance': 5, 'max_overflow': 0, 'service_instances': 2,
        'clock_ticks_per_second': os.sysconf('SC_CLK_TCK'),
        'scope': 'Complete cold synthetic RIDE actors; two processes, loopback PostgreSQL. '
            'pg_stat_statements is enabled in BOTH control and observed rounds. '
            'Observer overhead comparison is exploratory; formal gate uses its unchanged server configuration.'}
    try:
        with engine.connect() as conn:
            summary['postgres_version'] = conn.scalar(text('select version()'))
            summary['postgres_settings'] = {k: conn.scalar(text('show ' + k)) for k in (
                'shared_preload_libraries', 'pg_stat_statements.track_planning', 'track_io_timing',
                'track_wal_io_timing', 'autovacuum', 'max_connections')}
        for number, mode in enumerate(summary['order'], 1):
            folder = out / f'{number}-{mode}'
            folder.mkdir()
            schema = 'mi_' + uuid4().hex
            with engine.begin() as conn:
                conn.execute(text('CREATE SCHEMA ' + schema))
            env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'TZ') if k in os.environ}
            env.update(DATABASE_URL=url.update_query_dict({
                'options': '-csearch_path=' + schema + ' -cstatement_timeout=15000 -clock_timeout=10000 -cidle_in_transaction_session_timeout=30000 -cpg_stat_statements.track_planning=on',
                'application_name': 'go_cost_worker', 'connect_timeout': '5'}).render_as_string(hide_password=False),
                APP_ENV='test', MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false', TRAVEL_INTELLIGENCE_ENABLED='false',
                DATABASE_POOL_SIZE='5', DATABASE_MAX_OVERFLOW='0', DATABASE_POOL_TIMEOUT_SECONDS='10',
                PYTHONPATH=str(APP / 'src'), GO_COST_OBSERVE='1' if mode == 'observed' else '0',
                GO_COST_POSTGRES_PID=os.environ['GO_COST_POSTGRES_PID'],
                HOSTED_RESERVATION_EXPIRY_WORKER_ENABLED='false', VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED='false',
                GO_RIDE_ISOLATED_CANCELLATION_POLICY_FILE=str(APP / 'scripts/fixtures/ride-cancellation.synthetic.json'))
            try:
                with (folder / 'coordinator.log').open('w') as log:
                    subprocess.run([sys.executable, __file__, '--coordinator', str(folder)],
                                   env=env, cwd=folder, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=420)
                result = read(folder / 'result.json')
                assert result['correctness'] == 'PASS'
                summary['rounds'].append(round_record(number, mode, schema, result))
                write(out / 'summary.json', summary)
                print(json.dumps(summary['rounds'][-1]), flush=True)
            finally:
                with engine.begin() as conn:
                    conn.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        pairs = {mode: [stage['p95_ms'] for r in summary['rounds'] if r['mode'] == mode
                        for stage in r['stages'] if stage['actors'] == 100] for mode in ('control', 'observed')}
        assert all(len(values) == 2 for values in pairs.values()), 'TWENTY_TIER_FAILED'
        summary['observer_p95_median_ratio'] = statistics.median(pairs['observed']) / statistics.median(pairs['control'])
        summary['status'] = 'DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE'
    finally:
        engine.dispose()
        write(out / 'summary.json', summary)
        write(out / 'SHA256.json', {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in out.rglob('*') if p.is_file() and p.name != 'SHA256.json'})


if __name__ == '__main__':
    main()
