"""Real subprocess checks for dependency preparation's success and refusal paths."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv

SCRIPT = Path(__file__).resolve().parents[2] / "script" / "builder_python_smoke.py"


class BuilderPythonSmokeTests(unittest.TestCase):
    def run_cli(self, python, root, context="host", env=None):
        evidence = root / "evidence.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--python", str(python),
                                 "--evidence", str(evidence), "--context", context],
                                capture_output=True, text=True, env=env, timeout=180)
        return result, json.loads(evidence.read_text())

    def test_missing_interpreter_fails_and_writes_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, report = self.run_cli(root / "missing-python", root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["reason"], "FileNotFoundError")

    def test_clean_venv_missing_dependencies_fails_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            venv.EnvBuilder(with_pip=False).create(root / "empty")
            result, report = self.run_cli(root / "empty/bin/python", root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["reason"], "INTERPRETER_OR_DEPENDENCY_PROBE_FAILED")
            self.assertNotIn("pytest_exit_code", report)

    def test_real_dependency_smoke_ignores_external_pytest_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = os.environ.copy()
            env["PYTEST_ADDOPTS"] = "--deliberately-invalid-argument"
            env["PYTEST_PLUGINS"] = "nonexistent_injected_plugin"
            result, report = self.run_cli(Path(sys.executable), root, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(report["pytest_exit_code"], 0)
            self.assertIn("4 passed", report["pytest_stdout"])
            self.assertEqual(report["sandbox_validation"], "HOST_ONLY")
            self.assertFalse(report["database_tested"])
            self.assertIn("httpx", report["interpreter"]["packages"])

    def test_agent_label_alone_never_claims_verified_sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            result, report = self.run_cli(Path(sys.executable), Path(directory), "agent")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(report["sandbox_validation"], "PENDING_EXTERNAL_RUN_VERIFICATION")


if __name__ == "__main__":
    unittest.main()
