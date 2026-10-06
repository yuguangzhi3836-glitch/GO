"""Run the supplement backend boundaries through the existing C13 inventory.

These offline tests review #534, not the fifteen payment cases on #531.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.no_db
@pytest.mark.parametrize("directory,modules,count", [
    ("runtime-host-channel-v1", ["test_c1_review_inventory",
      "test_c1_c13_supplement", "test_c1_c13c14_review_transport"], 84),
    ("c13-c14-lite", ["test_lite_pg533", "test_lite_supplement_preflight",
      "test_lite_machine_inventory"], 29),
])
def test_pg533_backend_entry(directory, modules, count):
    backend = Path(__file__).resolve().parents[2] / "control-plane" / directory
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", *modules], cwd=backend,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Ran {count} tests" in result.stderr, result.stderr
    assert "skipped" not in result.stderr.lower(), result.stderr
