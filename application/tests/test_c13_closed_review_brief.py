"""C13 inventory entry for the closed-candidate reader's actual offline tests.

The full backend suite remains in backend CI. This adapter executes the focused
reader suite from the same frozen checkout; it does not test application behavior.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.no_db
def test_closed_review_brief_reader(capsys):
    root = Path(__file__).resolve().parents[2]
    backend = root / "control-plane" / "c13-c14-lite"
    assert (backend / "test_lite_review_brief_closed.py").is_file()
    script = """
import json, unittest
suite = unittest.defaultTestLoader.discover('.', pattern='test_lite_review_brief_closed.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
summary = dict(tests=result.testsRun, failures=len(result.failures),
               errors=len(result.errors), skipped=len(result.skipped))
print(json.dumps(summary, sort_keys=True))
raise SystemExit(not (result.wasSuccessful() and result.testsRun == 12 and not result.skipped))
"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-c", script], cwd=backend,
                            env=env, capture_output=True, text=True, timeout=60)
    with capsys.disabled():
        print(result.stderr)
        print("C13_CLOSED_READER_RESULT " + result.stdout.strip())
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout.strip())
    assert summary == {"tests": 12, "failures": 0, "errors": 0, "skipped": 0}
