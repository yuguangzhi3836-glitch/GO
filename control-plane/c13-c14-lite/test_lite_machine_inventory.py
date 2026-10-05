"""Real subprocess regressions for the C13 inventory and import-root failures."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import lite_machine_inventory as inventory


class MachineInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tests = self.root / "application/tests"
        self.tests.mkdir(parents=True)
        (self.tests / "__init__.py").write_text("")
        (self.tests / "helper.py").write_text("VALUE = 42\n")
        (self.tests / "test_one.py").write_text(
            "from tests.helper import VALUE\ndef test_one(): assert VALUE == 42\n")
        (self.tests / "test_two.py").write_text("def test_two(): assert True\n")
        (self.tests / "test_bad.py").write_text("def test_bad(): assert False\n")

    def invoke(self, value):
        return subprocess.run(
            [sys.executable, str(Path(inventory.__file__).resolve()),
             "--candidate", str(self.root)],
            env={**os.environ, "MACHINE_INVENTORY": value},
            capture_output=True)

    def pytest_run(self, value):
        result = self.invoke(value)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = [str(self.root / p.removeprefix("/srv/"))
                for p in result.stdout.decode().split("\0") if p]
        # Same static shell/positional-argv contract as Docker in the workflow.
        return subprocess.run(
            ["bash", "-c", 'exec "$1" -m pytest "${@:2}" -q --junitxml=../junit.xml',
             "c13-tests", sys.executable, *args],
            cwd=self.root / "application",
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            capture_output=True, text=True)

    def test_single_file_imports_tests_helper(self):
        result = self.pytest_run("application/tests/test_one.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 passed", result.stdout)

    def test_two_paths_are_two_arguments_and_both_execute(self):
        result = self.pytest_run("application/tests/test_one.py application/tests/test_two.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("2 passed", result.stdout)

    def test_failed_assertion_stays_failed_and_retains_junit(self):
        result = self.pytest_run("application/tests/test_bad.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("failures=\"1\"", (self.root / "junit.xml").read_text())

    def test_default_directory_remains_supported(self):
        self.assertEqual(inventory.inventory_paths("application/tests", self.root),
                         ["/srv/application/tests"])

    def test_old_quoted_multi_path_fails_as_negative_control(self):
        result = subprocess.run(
            [sys.executable, "-m", "pytest",
             "application/tests/test_one.py application/tests/test_two.py", "-q"],
            cwd=self.root, capture_output=True, text=True,
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)

    def test_old_repo_cwd_cannot_import_tests_helper(self):
        (self.tests / "__init__.py").unlink()
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "application/tests/test_one.py", "-q",
             "--import-mode=importlib"],
            cwd=self.root, capture_output=True, text=True,
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("No module named 'tests", result.stdout)

    def test_unsafe_or_missing_paths_rejected_before_any_argv(self):
        for value in ("", "-q", "/etc/passwd", "application/tests/../secret.py",
                      "application/tests/missing.py", "application/tests//test_one.py",
                      "application/tests/test_one.py;touch /tmp/evil",
                      "$(touch /tmp/evil)", "application/tests/test_one.py -p evil",
                      "application/tests/test_one.py::test_one"):
            with self.subTest(value=value):
                result = self.invoke(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"MACHINE_INVENTORY_REJECTED\n")

    def test_symlink_even_inside_tests_is_rejected(self):
        (self.tests / "test_link.py").symlink_to(self.tests / "test_one.py")
        self.assertNotEqual(self.invoke("application/tests/test_link.py").returncode, 0)

    def test_escaping_symlink_is_rejected(self):
        (self.root / "outside.py").write_text("")
        (self.tests / "escape.py").symlink_to(self.root / "outside.py")
        self.assertNotEqual(self.invoke("application/tests/escape.py").returncode, 0)

    def test_workflow_preserves_failure_gate_and_argv_boundary(self):
        repo = Path(__file__).resolve().parents[2]
        text = (repo / ".github/workflows/c13-quality-acceptance.yml").read_text()
        machine, ai = text.split("  c13-ai-review:", 1)
        run = machine.split("        id: machine_run", 1)[1].split("        run: |", 1)[1]
        run = run.split("      - name: Record the machine-test manifest", 1)[0]
        self.assertNotIn("${{ inputs.machine_inventory }}", run)
        self.assertIn('python -m pytest "$@"', run)
        self.assertIn('c13-tests "${test_paths[@]}"', run)
        self.assertIn("-w /srv/application", run)
        self.assertIn('pipeline_status=("${PIPESTATUS[@]}")', run)
        self.assertNotIn("continue-on-error", machine)
        self.assertIn("    needs: c13-machine-test", ai)
        self.assertNotIn("    if:", ai.split("    steps:", 1)[0])
        for name in ("Record the machine-test manifest", "Publish the machine-test evidence"):
            header = machine.split("      - name: " + name, 1)[1].split("\n", 2)
            self.assertIn("always()", header[1])



if __name__ == "__main__":
    unittest.main()
