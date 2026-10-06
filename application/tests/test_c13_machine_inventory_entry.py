"""Expose the backend regressions to the existing changed-test C13 inventory."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.no_db
def test_c13_machine_inventory_entry():
    backend = Path(__file__).resolve().parents[2] / "control-plane/c13-c14-lite"
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", "test_lite_machine_inventory"],
        cwd=backend,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Ran 10 tests" in result.stderr, result.stderr
    assert "skipped" not in result.stderr.lower(), result.stderr
