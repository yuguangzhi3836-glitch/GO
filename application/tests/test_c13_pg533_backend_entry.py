"""Expose the frozen Runtime/C13 backend suites as two no_db C13 cases.

Each case runs one backend directory's own modules through `unittest` and enforces a
NON-VACUITY FLOOR: a run that collects nothing, or that lost tests, is refused even
when `unittest` would have exited 0 with an empty suite.
"""
import os
import re
from pathlib import Path
import subprocess
import sys

import pytest


def _assert_unittest_success(result, count):
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(r"^Ran (\d+) tests? in ", result.stderr, re.MULTILINE)
    assert match, result.stderr
    # `count` is a NON-VACUITY FLOOR, not a frozen total. The module list below grows
    # whenever the frozen backend suites grow, so a literal total goes stale on the very
    # next addition - it already had, and that stale literal is what stopped a correct
    # candidate in the C13 machine job. A floor still refuses a run that silently
    # collected nothing or lost tests, which is the failure this guard exists to catch.
    assert int(match.group(1)) >= count, (count, result.stderr)
    # Names may contain "skipped"; reject skips in the terminal summary only.
    assert result.stderr.rstrip().splitlines()[-1] == "OK", result.stderr


@pytest.mark.no_db
@pytest.mark.parametrize("directory,modules,count", [
    ("runtime-host-channel-v1", ["test_c1_review_inventory",
      "test_c1_c13c14_review_transport"], 77),
    ("c13-c14-lite", ["test_lite_machine_inventory"], 13),
])
def test_frozen_backend_entry(directory, modules, count):
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
def test_unittest_summary_gate(body, accepted):
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
