"""Expose the backend regressions to the existing changed-test C13 inventory."""
import os
from pathlib import Path
import re
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
    match = re.search(r"^Ran (\d+) tests? in ", result.stderr, re.MULTILINE)
    assert match, result.stderr
    # A NON-VACUITY FLOOR, not a frozen total: this module grew from 10 to 13 as the
    # machine-inventory cases were added, and a literal total would go stale again on the
    # next one. The floor still refuses a collection that silently ran nothing.
    assert int(match.group(1)) >= 13, result.stderr
    assert "skipped" not in result.stderr.lower(), result.stderr
