"""Opt-in diagnostic intervals; no payment or transaction behavior changes.

Rebuilt after #433 lost its uncommitted files; #432 supplied the interval design.
Each instance belongs to one synchronous execution. Process CPU is deliberately
absent: measure it once around the whole concurrent workload, never per request.
"""
from contextlib import contextmanager
from time import perf_counter_ns


class MoneyCreateDiagnostics:
    def __init__(self, *, wall_clock=perf_counter_ns):
        self._clock = wall_clock
        self._start = wall_clock()
        self._stack = []
        self._totals = dict(wait=0, hold=0, sql=0, commit=0)
        self._sql = []
        self._closed = False

    @contextmanager
    def _interval(self, kind, label=None):
        if self._closed:
            raise ValueError("DIAGNOSTIC_FINISHED")
        parent = self._stack[-1] if self._stack else None
        if kind in ("wait", "hold"):
            allowed = parent is None
        else:
            allowed = parent == "hold"
        if not allowed:
            raise ValueError("INVALID_INTERVAL_NESTING")
        start = self._clock()
        self._stack.append(kind)
        try:
            yield
        finally:
            elapsed = self._clock() - start
            self._stack.pop()
            if elapsed < 0:
                raise ValueError("NON_MONOTONIC_CLOCK")
            self._totals[kind] += elapsed
            if kind == "sql":
                self._sql.append({"label": label, "duration_ns": elapsed})

    def measure_pool_acquire_wait(self):
        return self._interval("wait")

    def measure_connection_hold(self):
        return self._interval("hold")

    def measure_sql_stage(self, label):
        # Labels are supplied by the harness, never raw SQL/parameters or identities.
        if not isinstance(label, str) or not label or len(label) > 96:
            raise ValueError("BOUNDED_SQL_LABEL_REQUIRED")
        return self._interval("sql", label)

    def measure_commit(self):
        return self._interval("commit")

    def finish(self, outcome):
        if self._stack:
            raise ValueError("INTERVAL_STILL_OPEN")
        if self._closed:
            raise ValueError("DIAGNOSTIC_FINISHED")
        if outcome not in {"new_auth", "new_capture", "replay", "error"}:
            raise ValueError("OUTCOME_REQUIRED")
        wall = self._clock() - self._start
        t = self._totals
        if min(wall - t['wait'] - t['hold'], t['hold'] - t['sql'] - t['commit']) < 0:
            raise ValueError("INTERVAL_ACCOUNTING_INVALID")
        self._closed = True
        return dict(outcome=outcome, wall_total_ns=wall,
                    pool_acquire_wait_ns=t['wait'], connection_hold_ns=t['hold'],
                    sql_total_ns=t['sql'], commit_ns=t['commit'],
                    hold_other_ns=t['hold'] - t['sql'] - t['commit'],
                    wall_other_ns=wall - t['wait'] - t['hold'],
                    sql_stages=[dict(x) for x in self._sql])
