from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter_ns, process_time_ns
from typing import Callable, Iterator, Literal


MoneyCreateOutcome = Literal[
    "idempotent_replay",
    "new_authorization_write",
    "new_capture_write",
    "new_refund_write",
    "new_compensation_write",
    "new_payout_write",
    "new_release_write",
]


@dataclass(frozen=True)
class MoneyCreateSqlStage:
    label: str
    duration_ns: int
    rowcount: int | None = None

    def as_dict(self) -> dict:
        result = {"label": self.label, "duration_ns": self.duration_ns}
        if self.rowcount is not None:
            result["rowcount"] = self.rowcount
        return result


@dataclass(frozen=True)
class MoneyCreateDiagnosticsSummary:
    wall_total_ns: int
    app_cpu_ns: int
    pool_acquire_wait_ns: int
    connection_hold_ns: int
    commit_ns: int
    instrumentation_overhead_ns: int
    outcome: MoneyCreateOutcome
    sql_stages: tuple[MoneyCreateSqlStage, ...]

    @property
    def sql_total_ns(self) -> int:
        return sum(stage.duration_ns for stage in self.sql_stages)

    @property
    def in_connection_unattributed_ns(self) -> int:
        return self.connection_hold_ns - self.sql_total_ns - self.commit_ns

    @property
    def wall_unattributed_ns(self) -> int:
        return self.wall_total_ns - self.pool_acquire_wait_ns - self.connection_hold_ns

    @property
    def largest_sql_stage(self) -> MoneyCreateSqlStage | None:
        if not self.sql_stages:
            return None
        return max(self.sql_stages, key=lambda stage: stage.duration_ns)

    def as_dict(self) -> dict:
        largest = self.largest_sql_stage
        return {
            "wall_total_ns": self.wall_total_ns,
            "app_cpu_ns": self.app_cpu_ns,
            "instrumentation_overhead_ns": self.instrumentation_overhead_ns,
            "pool_acquire_wait_ns": self.pool_acquire_wait_ns,
            "connection_hold_ns": self.connection_hold_ns,
            "commit_ns": self.commit_ns,
            "sql_total_ns": self.sql_total_ns,
            "in_connection_unattributed_ns": self.in_connection_unattributed_ns,
            "wall_unattributed_ns": self.wall_unattributed_ns,
            "outcome": self.outcome,
            "sql_stages": [stage.as_dict() for stage in self.sql_stages],
            "largest_sql_stage": None if largest is None else largest.as_dict(),
        }


class MoneyCreateDiagnostics:
    """Collect non-overlapping wall-clock buckets for a money.create call.

    Pool wait and connection hold are sibling wall-clock buckets. SQL stages and commit
    are child buckets inside connection hold. App CPU is reported separately and is
    intentionally not mixed into the wall-clock sums.
    """

    _MOVEMENT_TYPES = {
        "AUTHORIZATION": "new_authorization_write",
        "CAPTURE": "new_capture_write",
        "REFUND": "new_refund_write",
        "COMPENSATION": "new_compensation_write",
        "PAYOUT": "new_payout_write",
        "RELEASE": "new_release_write",
    }

    def __init__(
        self,
        *,
        wall_clock: Callable[[], int] = perf_counter_ns,
        cpu_clock: Callable[[], int] = process_time_ns,
        instrumentation_overhead_ns: int = 0,
    ) -> None:
        if instrumentation_overhead_ns < 0:
            raise ValueError("INSTRUMENTATION_OVERHEAD_NON_NEGATIVE_REQUIRED")
        self._wall_clock = wall_clock
        self._cpu_clock = cpu_clock
        self._wall_start_ns = wall_clock()
        self._cpu_start_ns = cpu_clock()
        self._pool_acquire_wait_ns = 0
        self._connection_hold_ns = 0
        self._commit_ns = 0
        self._instrumentation_overhead_ns = instrumentation_overhead_ns
        self._sql_stages: list[MoneyCreateSqlStage] = []
        self._outcome: MoneyCreateOutcome | None = None
        self._pool_wait_open_ns: int | None = None
        self._connection_hold_open_ns: int | None = None
        self._commit_open_ns: int | None = None

    def set_pool_acquire_wait(self, duration_ns: int) -> None:
        if duration_ns < 0:
            raise ValueError("POOL_ACQUIRE_WAIT_NON_NEGATIVE_REQUIRED")
        self._pool_acquire_wait_ns = duration_ns

    def set_connection_hold(self, duration_ns: int) -> None:
        if duration_ns < 0:
            raise ValueError("CONNECTION_HOLD_NON_NEGATIVE_REQUIRED")
        self._connection_hold_ns = duration_ns

    def set_commit(self, duration_ns: int) -> None:
        if duration_ns < 0:
            raise ValueError("COMMIT_NON_NEGATIVE_REQUIRED")
        self._commit_ns = duration_ns

    def add_sql_stage(self, label: str, duration_ns: int, *, rowcount: int | None = None) -> None:
        if not label:
            raise ValueError("SQL_STAGE_LABEL_REQUIRED")
        if duration_ns < 0:
            raise ValueError("SQL_STAGE_DURATION_NON_NEGATIVE_REQUIRED")
        self._sql_stages.append(MoneyCreateSqlStage(label=label, duration_ns=duration_ns, rowcount=rowcount))

    def mark_idempotent_replay(self) -> None:
        self._outcome = "idempotent_replay"

    def mark_new_write(self, movement_type: str) -> None:
        try:
            self._outcome = self._MOVEMENT_TYPES[movement_type]
        except KeyError as exc:
            raise ValueError("UNSUPPORTED_MONEY_MOVEMENT_TYPE") from exc

    @contextmanager
    def measure_pool_acquire_wait(self) -> Iterator[None]:
        if self._pool_wait_open_ns is not None:
            raise ValueError("POOL_ACQUIRE_WAIT_ALREADY_OPEN")
        self._pool_wait_open_ns = self._wall_clock()
        try:
            yield
        finally:
            start = self._pool_wait_open_ns
            self._pool_wait_open_ns = None
            self.set_pool_acquire_wait(self._wall_clock() - start)

    @contextmanager
    def measure_connection_hold(self) -> Iterator[None]:
        if self._connection_hold_open_ns is not None:
            raise ValueError("CONNECTION_HOLD_ALREADY_OPEN")
        self._connection_hold_open_ns = self._wall_clock()
        try:
            yield
        finally:
            start = self._connection_hold_open_ns
            self._connection_hold_open_ns = None
            self.set_connection_hold(self._wall_clock() - start)

    @contextmanager
    def measure_sql_stage(self, label: str, *, rowcount: int | None = None) -> Iterator[None]:
        start = self._wall_clock()
        try:
            yield
        finally:
            self.add_sql_stage(label, self._wall_clock() - start, rowcount=rowcount)

    @contextmanager
    def measure_commit(self) -> Iterator[None]:
        if self._commit_open_ns is not None:
            raise ValueError("COMMIT_ALREADY_OPEN")
        self._commit_open_ns = self._wall_clock()
        try:
            yield
        finally:
            start = self._commit_open_ns
            self._commit_open_ns = None
            self.set_commit(self._wall_clock() - start)

    def finish(self) -> MoneyCreateDiagnosticsSummary:
        if self._pool_wait_open_ns is not None:
            raise ValueError("POOL_ACQUIRE_WAIT_STILL_OPEN")
        if self._connection_hold_open_ns is not None:
            raise ValueError("CONNECTION_HOLD_STILL_OPEN")
        if self._commit_open_ns is not None:
            raise ValueError("COMMIT_STILL_OPEN")
        if self._outcome is None:
            raise ValueError("MONEY_CREATE_OUTCOME_REQUIRED")

        wall_total_ns = self._wall_clock() - self._wall_start_ns
        app_cpu_ns = self._cpu_clock() - self._cpu_start_ns
        sql_total_ns = sum(stage.duration_ns for stage in self._sql_stages)

        if self._commit_ns > self._connection_hold_ns:
            raise ValueError("COMMIT_EXCEEDS_CONNECTION_HOLD")
        if sql_total_ns + self._commit_ns > self._connection_hold_ns:
            raise ValueError("SQL_AND_COMMIT_EXCEED_CONNECTION_HOLD")
        if self._pool_acquire_wait_ns + self._connection_hold_ns > wall_total_ns:
            raise ValueError("POOL_AND_HOLD_EXCEED_WALL_TOTAL")

        return MoneyCreateDiagnosticsSummary(
            wall_total_ns=wall_total_ns,
            app_cpu_ns=app_cpu_ns,
            pool_acquire_wait_ns=self._pool_acquire_wait_ns,
            connection_hold_ns=self._connection_hold_ns,
            commit_ns=self._commit_ns,
            instrumentation_overhead_ns=self._instrumentation_overhead_ns,
            outcome=self._outcome,
            sql_stages=tuple(self._sql_stages),
        )
