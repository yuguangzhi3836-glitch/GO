"""Expose exact candidate Runtime regressions through the existing C13 test path."""
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


@pytest.mark.no_db
def test_frozen_review_base_regressions():
    backend = Path(__file__).resolve().parents[2] / "control-plane/runtime-host-channel-v1"
    # The installed C13 image has no Git/PyYAML. Those five integration cases
    # run in Runtime CI; this bootstrap review executes all ten pure ingress/
    # transport cases from this exact candidate without changing the image.
    result = subprocess.run([sys.executable, "-m", "unittest", "-v", "test_c1_frozen_review_base.FrozenBaseIngress"],
                            cwd=backend, capture_output=True, text=True, timeout=90,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    count = re.search(r"^Ran (\d+) tests? in ", result.stderr, re.MULTILINE)
    assert count and int(count.group(1)) >= 10, result.stderr
    assert "skipped" not in result.stderr.lower(), result.stderr
