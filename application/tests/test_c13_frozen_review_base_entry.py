"""Expose exact candidate Runtime regressions through the existing C13 test path."""
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

# The classes below are the frozen-base ones the C13 image CAN execute: no Git checkout
# history, no PyYAML, no Docker. The real-Git cases stay in Runtime CI; this bootstrap
# review executes the pure ingress / transport / identity cases from this exact candidate
# without installing anything into the image.
FROZEN_BASE_CLASSES = (
    "test_c1_frozen_review_base.FrozenBaseIngress",
    "test_c1_frozen_review_base.AutoFrozenRoundCarriesItsIdentity",
    "test_c1_review_issue_ingress.D_TheCandidateIsFrozen",
    "test_c1_review_issue_ingress.J_ARoundCanBeRaisedOnlyByRevision",
)
# 11 frozen-base ingress cases + 6 auto-frozen round cases + 6 candidate-frozen cases
# + 19 explicit-revision round cases (the round identity, and the one door a human may
# open on it). The count is a floor, not an equality: this bootstrap exists to run the
# classes the C13 image can execute, not to pin their size.
MINIMUM_FROZEN_BASE_TESTS = 41


@pytest.mark.no_db
def test_frozen_review_base_regressions():
    backend = Path(__file__).resolve().parents[2] / "control-plane/runtime-host-channel-v1"
    result = subprocess.run([sys.executable, "-m", "unittest", "-v", *FROZEN_BASE_CLASSES],
                            cwd=backend, capture_output=True, text=True, timeout=90,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    count = re.search(r"^Ran (\d+) tests? in ", result.stderr, re.MULTILINE)
    assert count and int(count.group(1)) >= MINIMUM_FROZEN_BASE_TESTS, result.stderr
    assert "skipped" not in result.stderr.lower(), result.stderr
