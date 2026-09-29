"""Diagnostic-only, buffered observations; never records SQL text or parameters."""
from collections import Counter
from pathlib import Path
import os
import threading
import time

TICKS = os.sysconf('SC_CLK_TCK')


def proc_stat(pid):
    text = Path(f'/proc/{pid}/stat').read_text()
    fields = text[text.rindex(')') + 2:].split()
    return {'pid': int(pid), 'ppid': int(fields[1]), 'state': fields[0],
            'user_ticks': int(fields[11]), 'system_ticks': int(fields[12]),
            'start_ticks': int(fields[19]), 'rss_pages': int(fields[21])}


def process_snapshot(app_pids, postgres_pid):
    start = time.monotonic_ns()
    # The isolated container's postmaster and direct children; no unrelated PG.
    postgres = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            row = proc_stat(path.name)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if row['pid'] == postgres_pid or row['ppid'] == postgres_pid:
            postgres.append(row)
    apps = [proc_stat(pid) for pid in app_pids]
    host = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
    pressure = Path('/proc/pressure/cpu')
    cgroup = Path('/sys/fs/cgroup/cpu.stat')
    pg_cgroup_path = next(line[3:] for line in Path(f'/proc/{postgres_pid}/cgroup').read_text().splitlines() if line.startswith('0::'))
    pg_cgroup = Path('/sys/fs/cgroup') / pg_cgroup_path.lstrip('/') / 'cpu.stat'
    pg_cpu = {k: int(v) for k, v in (line.split() for line in pg_cgroup.read_text().splitlines())}
    return {'start_ns': start, 'end_ns': time.monotonic_ns(), 'apps': apps,
            'postgres_cgroup_cpu': pg_cpu, 'postgres_cgroup_path': pg_cgroup_path,
            'postgres': postgres, 'host_ticks': host,
            'host_loadavg': Path('/proc/loadavg').read_text().split()[:4],
            'host_cpu_pressure': pressure.read_text() if pressure.exists() else None,
            'observer_cgroup_cpu_stat': cgroup.read_text() if cgroup.exists() else None}


def cpu_delta(before, after, group, strict=True):
    previous = {(r['pid'], r['start_ticks']): r for r in before[group]}
    current = {(r['pid'], r['start_ticks']): r for r in after[group]}
    # A backend disappearing before the ending snapshot would lose its final CPU.
    lost = previous.keys() - current.keys()
    if strict:
        assert not lost, 'PROCESS_EXITED_INSIDE_WINDOW'
    user = system = 0
    for key, row in current.items():
        old = previous.get(key, {'user_ticks': 0, 'system_ticks': 0})
        u = row['user_ticks'] - old['user_ticks']
        s = row['system_ticks'] - old['system_ticks']
        assert min(u, s) >= 0
        user += u
        system += s
    return {'user_seconds': user / TICKS, 'system_seconds': system / TICKS,
            'total_seconds': (user + system) / TICKS,
            'end_processes': len(current), 'new_processes': len(current.keys() - previous.keys()),
            'lost_processes': len(lost), 'complete_for_boundary_processes': not lost}


STAT_FIELDS = ('calls', 'total_plan_time', 'total_exec_time', 'rows',
               'shared_blks_hit', 'shared_blks_read', 'shared_blks_written',
               'temp_blks_read', 'temp_blks_written', 'wal_records', 'wal_bytes')


def statement_snapshot(conn):
    # query text is deliberately not fetched, including normalized text.
    rows = conn.execute('SELECT queryid::text, ' + ','.join(STAT_FIELDS) +
                        ' FROM public.pg_stat_statements WHERE dbid = '
                        "(SELECT oid FROM pg_database WHERE datname=current_database())").fetchall()
    return {r[0]: dict(zip(STAT_FIELDS, map(float, r[1:]))) for r in rows}


def statement_delta(before, after):
    result = []
    for queryid, row in after.items():
        diff = {k: row[k] - before.get(queryid, {}).get(k, 0) for k in STAT_FIELDS}
        assert all(v >= -1e-6 for v in diff.values()), 'STATISTICS_RESET_INSIDE_WINDOW'
        if diff['calls']:
            result.append({'queryid': queryid, **diff})
    return sorted(result, key=lambda r: r['total_exec_time'], reverse=True)


class Sampler:
    def __init__(self, conn, app_pids, postgres_pid, interval=.1):
        self.conn = conn
        self.app_pids = app_pids
        self.postgres_pid = postgres_pid
        self.interval = interval
        self.rows = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.loop, name='cost-observer')
        self.error = None

    def sample(self):
        start = time.monotonic_ns()
        # Activity, wait class and blockers only. No query text or bind values.
        states = self.conn.execute("""SELECT pid, state, wait_event_type, wait_event,
            cardinality(pg_blocking_pids(pid)) FROM pg_stat_activity
            WHERE datname=current_database() AND application_name='go_cost_worker'""").fetchall()
        processes = process_snapshot(self.app_pids, self.postgres_pid)
        self.rows.append({'start_ns': start, 'end_ns': time.monotonic_ns(),
                          'activity': states, 'processes': processes})

    def loop(self):
        try:
            while not self.stop_event.wait(self.interval):
                self.sample()
        except Exception as exc:
            self.error = type(exc).__name__

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=10)
        assert not self.thread.is_alive() and self.error is None, 'SAMPLER_FAILED'

    def summary(self):
        waits = Counter()
        for sample in self.rows:
            for pid, state, kind, wait, blockers in sample['activity']:
                waits[f'{state}|{kind}|{wait}'] += 1
        return {'sample_count': len(self.rows), 'interval_seconds': self.interval,
                'sample_cost_ms': [(r['end_ns'] - r['start_ns']) / 1e6 for r in self.rows],
                'backend_observations': dict(waits),
                'blocked_backend_observations': sum(bool(r[4]) for s in self.rows for r in s['activity']),
                'note': 'Sample counts are occupancy observations, not exact wait durations. '
                        'Short waits can be missed; active/NULL wait does not prove CPU execution.'}


class ClientEvents:
    """Hold and DBAPI commit timing without wrapping business services."""
    def __init__(self, engine):
        from sqlalchemy import event
        self.local = threading.local()
        self.events = []
        self.lock = threading.Lock()
        self.engine = engine
        self.original_commit = engine.dialect.do_commit
        def commit(connection):
            begin = time.monotonic_ns()
            try:
                return self.original_commit(connection)
            finally:
                self.add('commit', begin, time.monotonic_ns())
        engine.dialect.do_commit = commit

        @event.listens_for(engine, 'before_cursor_execute')
        def before(conn, cursor, statement, parameters, context, many):
            context._cost_start = time.monotonic_ns()

        @event.listens_for(engine, 'after_cursor_execute')
        def after(conn, cursor, statement, parameters, context, many):
            self.add('cursor', context._cost_start, time.monotonic_ns())

        @event.listens_for(engine.pool, 'checkout')
        def checkout(connection, record, proxy):
            record.info['_cost_hold'] = time.monotonic_ns()

        @event.listens_for(engine.pool, 'checkin')
        def checkin(connection, record):
            begin = record.info.pop('_cost_hold', None)
            if begin is not None:
                self.add('hold', begin, time.monotonic_ns())

        original_get = engine.pool._pool.get
        def get(block=True, timeout=None):
            begin = time.monotonic_ns()
            try:
                return original_get(block, timeout)
            finally:
                if block:
                    self.add('pool_queue', begin, time.monotonic_ns())
        engine.pool._pool.get = get

    def add(self, kind, start, end):
        with self.lock:
            self.events.append({'kind': kind, 'start_ns': start, 'end_ns': end,
                                'thread': threading.get_ident()})

    def snapshot(self):
        totals = {}
        for kind in ('cursor', 'commit', 'hold', 'pool_queue'):
            durations = [(r['end_ns'] - r['start_ns']) / 1e9 for r in self.events if r['kind'] == kind]
            totals[kind] = {'count': len(durations), 'sum_seconds': sum(durations),
                            'max_seconds': max(durations, default=0)}
        return {'events': self.events, 'totals': totals,
                'note': 'Concurrent wall durations overlap. Client cursor/commit includes '
                        'loopback transport and scheduling; differences from server time '
                        'are not a GIL measurement. Holds include cursor and commit time.'}
