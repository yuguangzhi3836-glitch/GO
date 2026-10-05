from go_hotel.payments.money_create_diagnostics import MoneyCreateDiagnostics


class FakeClock:
    def __init__(self, value: int = 0):
        self.value = value

    def __call__(self) -> int:
        return self.value

    def advance(self, delta: int) -> None:
        self.value += delta


def test_summary_reports_non_overlapping_capture_write_buckets():
    wall = FakeClock()
    cpu = FakeClock()
    diag = MoneyCreateDiagnostics(
        wall_clock=wall,
        cpu_clock=cpu,
        instrumentation_overhead_ns=17,
    )

    diag.set_pool_acquire_wait(100)
    diag.set_connection_hold(800)
    diag.add_sql_stage("lock-intent", 200, rowcount=1)
    diag.add_sql_stage("check-idempotency", 50, rowcount=1)
    diag.add_sql_stage("insert-movement", 120, rowcount=1)
    diag.set_commit(80)
    diag.mark_new_write("CAPTURE")

    wall.advance(900)
    cpu.advance(300)
    summary = diag.finish()

    assert summary.outcome == "new_capture_write"
    assert summary.sql_total_ns == 370
    assert summary.in_connection_unattributed_ns == 350
    assert summary.wall_unattributed_ns == 0
    assert summary.instrumentation_overhead_ns == 17
    assert summary.largest_sql_stage is not None
    assert summary.largest_sql_stage.label == "lock-intent"
    assert summary.as_dict()["largest_sql_stage"]["duration_ns"] == 200


def test_context_helpers_measure_replay_timing_from_clocks():
    wall = FakeClock()
    cpu = FakeClock()
    diag = MoneyCreateDiagnostics(wall_clock=wall, cpu_clock=cpu)

    with diag.measure_pool_acquire_wait():
        wall.advance(20)
    with diag.measure_connection_hold():
        wall.advance(10)
        with diag.measure_sql_stage("select-existing", rowcount=1):
            wall.advance(15)
        wall.advance(5)
        with diag.measure_commit():
            wall.advance(12)
        wall.advance(8)
    wall.advance(3)
    cpu.advance(40)
    diag.mark_idempotent_replay()

    summary = diag.finish()

    assert summary.outcome == "idempotent_replay"
    assert summary.pool_acquire_wait_ns == 20
    assert summary.connection_hold_ns == 50
    assert summary.commit_ns == 12
    assert summary.sql_total_ns == 15
    assert summary.in_connection_unattributed_ns == 23
    assert summary.wall_unattributed_ns == 3
    assert summary.app_cpu_ns == 40


def test_finish_rejects_overlapping_connection_substages():
    wall = FakeClock()
    cpu = FakeClock()
    diag = MoneyCreateDiagnostics(wall_clock=wall, cpu_clock=cpu)

    diag.set_pool_acquire_wait(5)
    diag.set_connection_hold(50)
    diag.add_sql_stage("load-intent", 30)
    diag.add_sql_stage("load-movements", 25)
    diag.set_commit(10)
    diag.mark_new_write("AUTHORIZATION")

    wall.advance(55)
    cpu.advance(1)

    try:
        diag.finish()
    except ValueError as exc:
        assert str(exc) == "SQL_AND_COMMIT_EXCEED_CONNECTION_HOLD"
    else:
        raise AssertionError("expected SQL/commit overlap validation to fail")


def test_finish_requires_outcome_classification():
    wall = FakeClock()
    cpu = FakeClock()
    diag = MoneyCreateDiagnostics(wall_clock=wall, cpu_clock=cpu)

    diag.set_connection_hold(10)
    wall.advance(10)

    try:
        diag.finish()
    except ValueError as exc:
        assert str(exc) == "MONEY_CREATE_OUTCOME_REQUIRED"
    else:
        raise AssertionError("expected outcome validation to fail")
