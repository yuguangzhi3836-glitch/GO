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
    driver = Path(__file__).with_name('c11_money_create_pg_driver.py').resolve()
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
