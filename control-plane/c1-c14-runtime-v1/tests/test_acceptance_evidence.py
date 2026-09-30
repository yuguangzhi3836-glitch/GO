"""Regression tests for acceptance evidence that must never fail open."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from acceptance_harness import REQUIRED, Scenario, evaluate


class EvidenceRegressionTests(unittest.TestCase):
    def test_truthy_non_boolean_does_not_grant_pass(self):
        for value in ("false", "PASS", 1, None):
            rows = [Scenario(name, True, {}) for name in REQUIRED]
            rows[0] = Scenario(REQUIRED[0], value, {})
            self.assertEqual(evaluate(rows)["verdict"], "FAIL")

    def test_duplicate_success_cannot_hide_failure(self):
        rows = [Scenario(name, True, {}) for name in REQUIRED]
        rows.insert(0, Scenario(REQUIRED[0], False, {}))
        self.assertEqual(evaluate(rows)["verdict"], "FAIL")

    def test_missing_and_malformed_results_emit_failed_evidence(self):
        for contents in (None, "not json", '{"scenarios": []}'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as temp:
                src = Path(temp)/"input.json"
                if contents is not None:
                    src.write_text(contents)
                out = Path(temp)/"evidence"
                result = subprocess.run([sys.executable, str(HERE/"acceptance_harness.py"),
                                         str(src), "--out", str(out)], capture_output=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(json.loads((out/"summary.json").read_text())["verdict"], "FAIL")
                self.assertEqual(len(ET.parse(out/"junit.xml").findall('.//failure')), len(REQUIRED))
                for line in (out/"SHA256SUMS").read_text().splitlines():
                    self.assertTrue((out/line.split('  ', 1)[1]).exists())


if __name__ == "__main__":
    unittest.main()
