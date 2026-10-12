"""C13 entry: execute the V80 cell-channel acceptance suites in the frozen checkout."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SUITES = [
    "test_c1_cell_generalization",
    "test_c1_ingress_recovery",
    "test_c1_c13c14_review_transport",
]

EXPECTED = {
    "test_c1_cell_generalization": {"tests": 48, "failures": 0, "errors": 0, "skipped": 0},
    "test_c1_ingress_recovery": {"tests": 13, "failures": 0, "errors": 0, "skipped": 0},
    "test_c1_c13c14_review_transport": {"tests": 65, "failures": 0, "errors": 0, "skipped": 0},
}


@pytest.mark.no_db
def test_v80_cell_channel_acceptance(capsys):
    backend = Path(__file__).resolve().parents[2] / "control-plane" / "runtime-host-channel-v1"
    for name in SUITES:
        assert (backend / (name + ".py")).is_file()
    script = """
import json, unittest
suites = [
    'test_c1_cell_generalization',
    'test_c1_ingress_recovery',
    'test_c1_c13c14_review_transport',
]
summary = {'suites': []}
loader = unittest.defaultTestLoader
all_ok = True
for name in suites:
    suite = loader.loadTestsFromName(name)
    result = unittest.TestResult()
    suite.run(result)
    entry = {
        'name': name,
        'tests': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
    }
    summary['suites'].append(entry)
    all_ok = all_ok and result.wasSuccessful() and result.testsRun > 0 and not result.skipped
summary['total'] = {
    'tests': sum(item['tests'] for item in summary['suites']),
    'failures': sum(item['failures'] for item in summary['suites']),
    'errors': sum(item['errors'] for item in summary['suites']),
    'skipped': sum(item['skipped'] for item in summary['suites']),
}
print(json.dumps(summary, sort_keys=True))
raise SystemExit(0 if all_ok else 1)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        capture_output=True,
        text=True,
        timeout=120,
    )
    with capsys.disabled():
        print(result.stderr)
        print("C13_V80_CELL_CHANNEL_RESULT " + result.stdout.strip())
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout.strip())
    actual = {entry["name"]: {k: entry[k] for k in ("tests", "failures", "errors", "skipped")}
              for entry in summary["suites"]}
    assert actual == EXPECTED
    assert summary["total"] == {"tests": 126, "failures": 0, "errors": 0, "skipped": 0}
