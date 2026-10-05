"""C13 entry: execute the actual ingress recovery suites in the frozen checkout."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.no_db
def test_runtime_ingress_recovery(capsys):
    backend = Path(__file__).resolve().parents[2] / "control-plane" / "runtime-host-channel-v1"
    names = ["test_c1_issue_consumer", "test_c1_issue_ingress", "test_c1_ingress_recovery", "test_c1_ghaw_registration"]
    for name in names:
        assert (backend / (name + ".py")).is_file()
    script = """
import json, unittest
suite = unittest.defaultTestLoader.loadTestsFromNames(
    ['test_c1_issue_consumer', 'test_c1_issue_ingress', 'test_c1_ingress_recovery', 'test_c1_ghaw_registration'])
result = unittest.TextTestRunner(verbosity=2).run(suite)
summary = dict(tests=result.testsRun, failures=len(result.failures),
               errors=len(result.errors), skipped=len(result.skipped))
print(json.dumps(summary, sort_keys=True))
raise SystemExit(not (result.wasSuccessful() and result.testsRun == 139 and not result.skipped))
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=backend,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                            capture_output=True, text=True, timeout=60)
    with capsys.disabled():
        print(result.stderr)
        print("C13_RUNTIME_INGRESS_RESULT " + result.stdout.strip())
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip()) == dict(tests=139, failures=0, errors=0, skipped=0)

