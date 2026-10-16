"""Isolated synchronous SQLAlchemy lease/CPU diagnostics, never an acceptance gate.

Union held-thread CPU is counted once even with nested leases. Per-lease resource
costs may overlap and must not be added to that union. No SQL text/values recorded.
"""
from collections import defaultdict
from contextlib import contextmanager
from functools import wraps
import threading
import time


class HoldCPU:
    def __init__(self, engine):
        from sqlalchemy import event
        from sqlalchemy.orm import Mapper
        self.engine = engine
        self.event = event
        self.local = threading.local()
        self.lock = threading.RLock()
        self.leases = {}
        self.states = []
        self.rows = defaultdict(lambda: [0.0, 0.0])
        self.errors = set()
        self.listeners = []
        self.originals = []
        self.closed = False
        self.checkouts = self.checkins = 0
        self._listen(engine.pool, 'checkout', self._checkout)
        self._listen(engine.pool, 'checkin', self._checkin)
        self._listen(engine, 'before_cursor_execute', self._sql_before)
        self._listen(engine, 'after_cursor_execute', self._sql_after)
        self._listen(engine, 'handle_error', self._sql_error)
        self._listen(Mapper, 'before_configured', self._mapper_before)
        self._listen(Mapper, 'after_configured', self._mapper_after)

    def _listen(self, target, name, fn):
        self.event.listen(target, name, fn)
        self.listeners.append((target, name, fn))

    def _state(self):
        if not hasattr(self.local, 'state'):
            self.local.state = {'leases': set(), 'phases': [],
                                'wall': time.monotonic(), 'cpu': time.thread_time()}
            with self.lock:
                self.states.append(self.local.state)
        return self.local.state

    def _advance(self):
        state = self._state()
        wall, cpu = time.monotonic(), time.thread_time()
        if state['leases']:
            phase = state['phases'][-1][1] if state['phases'] else 'other_while_held'
            with self.lock:
                row = self.rows[phase]
                row[0] += wall - state['wall']
                row[1] += cpu - state['cpu']
        state['wall'], state['cpu'] = wall, cpu
        return state

    def _push(self, label):
        state = self._advance()
        token = object()
        state['phases'].append((token, label))
        return token

    def _pop(self, token):
        state = self._advance()
        if not state['phases'] or state['phases'][-1][0] is not token:
            with self.lock:
                self.errors.add('NON_LIFO_PHASE')
            return
        state['phases'].pop()

    @contextmanager
    def phase(self, label):
        token = self._push(label)
        try:
            yield
        finally:
            self._pop(token)

    def _checkout(self, connection, record, proxy):
        state = self._advance()
        key = id(record)
        with self.lock:
            if key in self.leases:
                self.errors.add('DUPLICATE_CHECKOUT')
            self.leases[key] = threading.get_ident()
            self.checkouts += 1
        state['leases'].add(key)

    def _checkin(self, connection, record):
        state = self._advance()
        key = id(record)
        with self.lock:
            owner = self.leases.pop(key, None)
            if owner != threading.get_ident():
                self.errors.add('CROSS_THREAD_OR_UNOBSERVED_CHECKIN')
            self.checkins += 1
        state['leases'].discard(key)

    def _sql_before(self, conn, cursor, statement, parameters, context, many):
        context._hold_cpu_token = self._push('dbapi.execute')

    def _sql_after(self, conn, cursor, statement, parameters, context, many):
        token = getattr(context, '_hold_cpu_token', None)
        if token is not None:
            self._pop(token)
            del context._hold_cpu_token

    def _sql_error(self, exception_context):
        context = exception_context.execution_context
        token = getattr(context, '_hold_cpu_token', None)
        if token is not None:
            self._pop(token)
            del context._hold_cpu_token

    def _mapper_before(self):
        self.local.mapper_token = self._push('orm.configure')

    def _mapper_after(self):
        token = getattr(self.local, 'mapper_token', None)
        if token is not None:
            self._pop(token)
            self.local.mapper_token = None

    def wrap(self, obj, method, label):
        """Call before workers start; no import of application modules here."""
        original = getattr(obj, method)
        own = method in vars(obj)
        @wraps(original)
        def measured(*args, **kwargs):
            with self.phase(label):
                return original(*args, **kwargs)
        setattr(obj, method, measured)
        self.originals.append((obj, method, original, own, measured))

    def wrap_transactions(self):
        for name in ('do_commit', 'do_rollback'):
            self.wrap(self.engine.dialect, name, 'dbapi.' + name[3:])

    def snapshot(self):
        """Read only after all workers joined and sessions returned their leases."""
        with self.lock:
            errors = set(self.errors)
            if any(s['phases'] for s in self.states):
                errors.add('UNFINISHED_PHASES')
            if self.leases or self.checkouts != self.checkins:
                errors.add('OPEN_OR_UNBALANCED_LEASES')
            return {'diagnostic_only': True, 'valid': not errors,
                    'errors': sorted(errors), 'checkouts': self.checkouts,
                    'checkins': self.checkins,
                    'held_thread_by_phase': {
                        k: {'wall_seconds': v[0], 'cpu_seconds': v[1]}
                        for k, v in sorted(self.rows.items())},
                    'note': 'Exclusive phase buckets; held-thread union, not per-connection sum. '
                            'Wall includes scheduling and IO. CPU is calling-thread CPU, '
                            'not database CPU. Observer overhead included. Pool queue '
                            'before checkout and imports before installation are excluded. '
                            'Cross-thread lease transfer invalidates the report.'}

    def close(self):
        if self.closed:
            return
        self.closed = True
        for obj, method, original, own, measured in reversed(self.originals):
            if getattr(obj, method) is measured:
                if own:
                    setattr(obj, method, original)
                else:
                    delattr(obj, method)
        for target, name, fn in reversed(self.listeners):
            self.event.remove(target, name, fn)
