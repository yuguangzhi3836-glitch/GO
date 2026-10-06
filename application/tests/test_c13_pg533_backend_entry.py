"""Run the supplement backend boundaries through the existing C13 inventory.

These offline tests review #534, not the fifteen payment cases on #531.
"""
import os
import re
from pathlib import Path
import subprocess
import sys

import pytest


def _assert_unittest_success(result, count):
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(rf"^Ran {count} tests? in ", result.stderr, re.MULTILINE), result.stderr
    # Names may contain "skipped"; reject skips in the terminal summary only.
    assert result.stderr.rstrip().splitlines()[-1] == "OK", result.stderr


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
    _assert_unittest_success(result, count)


@pytest.mark.no_db
@pytest.mark.parametrize("body,accepted", [
    ("def test_skipped_word(self): pass", True),
    ("@unittest.skip('controlled skip')\ndef test_case(self): pass", False),
    ("def test_case(self): self.fail('controlled failure')", False),
])
def test_pg533_unittest_summary_gate(body, accepted):
    import textwrap
    source = "import unittest\nclass Probe(unittest.TestCase):\n" + textwrap.indent(body, "    ") + "\nunittest.main(verbosity=2)\n"
    result = subprocess.run([sys.executable, "-c", source],
                            capture_output=True, text=True, timeout=30)
    try:
        _assert_unittest_success(result, 1)
        passed = True
    except AssertionError:
        passed = False
    assert passed is accepted, result.stderr
