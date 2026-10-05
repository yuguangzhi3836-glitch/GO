"""Run outside conftest's SQLite environment; never mistake SQLite for PG proof."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest


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
