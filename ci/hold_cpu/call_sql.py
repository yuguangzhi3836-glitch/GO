"""Opt-in synchronous diagnostic: caller-labelled SQL and full lease lifetime.

Use only with controlled isolated fixtures. Labels describe asserted scenarios,
not outcomes inferred from timing. Never records SQL text, binds or exceptions.
"""
from contextlib import contextmanager
from functools import wraps
import hashlib
import threading
import time


class CallSQL:
    LABELS = {'fresh_AUTH', 'fresh_CAPTURE', 'replay_AUTH', 'replay_CAPTURE',
              'conflict'}

    def __init__(self, engine):
        from sqlalchemy import event
        self.engine, self.event = engine, event
        self.local = threading.local()
        self.lock = threading.RLock()
        self.calls, self.leases, self.errors = [], {}, set()
        self.listeners, self.originals = [], []
        self.closed = False
        for target, name, fn in [
            (engine.pool, 'checkout', self._checkout),
            (engine.pool, 'checkin', self._checkin),
            (engine, 'before_cursor_execute', self._before),
            (engine, 'after_cursor_execute', self._after),
            (engine, 'handle_error', self._error),
        ]:
            event.listen(target, name, fn)
            self.listeners.append((target, name, fn))
        for name in ('do_commit', 'do_rollback'):
            self._transaction(name)

    def _current(self):
        return getattr(self.local, 'call', None)

    @contextmanager
    def call(self, label):
        if label not in self.LABELS:
            raise ValueError('UNKNOWN_SCENARIO')
        if self.closed or self._current() is not None:
            raise RuntimeError('CLOSED_OR_NESTED_CALL')
        row = {'scenario': label, 'sql': [], 'transactions': [], 'leases': [],
               'acquisition_seconds': [], 'outcome': 'running'}
        with self.lock:
            row['call_id'] = len(self.calls) + 1
            self.calls.append(row)
        self.local.call = row
        start = time.perf_counter()
        try:
            yield row['call_id']
        except BaseException:
            row['outcome'] = 'error'
            raise
        else:
            row['outcome'] = 'returned'
        finally:
            row['wall_seconds'] = time.perf_counter() - start
            with self.lock:
                if any(v[0] is row for v in self.leases.values()):
                    self.errors.add('CALL_ENDED_WITH_LEASE')
            self.local.call = None

    @contextmanager
    def acquisition(self):
        """Optional bracket around session.connection(); NOT pure pool queue."""
        row = self._current()
        if row is None:
            raise RuntimeError('ACQUISITION_WITHOUT_CALL')
        start = time.perf_counter()
        try:
            yield
        finally:
            row['acquisition_seconds'].append(time.perf_counter() - start)

    def _checkout(self, connection, record, proxy):
        row = self._current()
        with self.lock:
            if id(record) in self.leases:
                self.errors.add('DUPLICATE_CHECKOUT')
            self.leases[id(record)] = (row, time.perf_counter(), threading.get_ident())

    def _checkin(self, connection, record):
        with self.lock:
            lease = self.leases.pop(id(record), None)
            if lease is None:
                self.errors.add('UNOBSERVED_CHECKIN')
                return
            row, start, owner = lease
            if owner != threading.get_ident() or row is not self._current():
                self.errors.add('LEASE_SCOPE_CHANGED')
            if row is not None:
                row['leases'].append(time.perf_counter() - start)

    def _before(self, conn, cursor, statement, parameters, context, many):
        row = self._current()
        if row is not None:
            with self.lock:
                if not any(v[0] is row and v[2] == threading.get_ident()
                           for v in self.leases.values()):
                    self.errors.add('SQL_WITHOUT_SCOPED_LEASE')
            context._call_sql_probe = (row, time.perf_counter(),
                                      hashlib.sha256(statement.encode()).hexdigest())

    def _finish(self, context, failed):
        token = getattr(context, '_call_sql_probe', None)
        if token is not None:
            row, start, fingerprint = token
            row['sql'].append({'fingerprint': fingerprint,
                               'seconds': time.perf_counter() - start,
                               'failed': failed})
            del context._call_sql_probe

    def _after(self, conn, cursor, statement, parameters, context, many):
        self._finish(context, False)

    def _error(self, exception_context):
        self._finish(exception_context.execution_context, True)

    def _transaction(self, name):
        dialect = self.engine.dialect
        original, own = getattr(dialect, name), name in vars(dialect)
        @wraps(original)
        def measured(*args, **kwargs):
            row, start, failed = self._current(), time.perf_counter(), False
            try:
                return original(*args, **kwargs)
            except BaseException:
                failed = True
                raise
            finally:
                if row is not None:
                    row['transactions'].append({'operation': name[3:],
                        'seconds': time.perf_counter() - start, 'failed': failed})
        setattr(dialect, name, measured)
        self.originals.append((name, original, own, measured))

    def snapshot(self):
        """Only after all workers join; unfinished calls/leases invalidate output."""
        import copy
        with self.lock:
            errors = set(self.errors)
            if self.leases:
                errors.add('OPEN_LEASES')
            if any(r['outcome'] == 'running' for r in self.calls):
                errors.add('OPEN_CALLS')
            return {'diagnostic_only': True, 'valid': not errors,
                    'errors': sorted(errors), 'calls': copy.deepcopy(self.calls),
                    'pool_queue_seconds': None,
                    'note': 'Client cursor time excludes fetch/materialization; '
                    'lease includes commit/rollback through checkin. Acquisition '
                    'is not pure queue. Scenario labels must be fixture-asserted. '
                    'No SQL/binds/results/exception text retained. Observer overhead included.'}

    def close(self):
        if self.closed:
            return
        for name, original, own, measured in reversed(self.originals):
            if getattr(self.engine.dialect, name) is measured:
                if own:
                    setattr(self.engine.dialect, name, original)
                else:
                    delattr(self.engine.dialect, name)
        for target, name, fn in reversed(self.listeners):
            self.event.remove(target, name, fn)
        self.closed = True
