"""Reproduce the split-root import defect without Docker or a live host.

Real Python subprocess imports are used; image assembly below is a filesystem
model, not a claim that a Docker image or a public HTTP endpoint was tested.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hk-staging'))
sys.path.insert(0, str(Path(__file__).parent))
import test_test_pr_durability as durability
from hk_agent import test_pr


class SourceRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = self.root / 'app'
        self.workspace = self.root / 'workspace'
        for root, brand, calendar in [(self.app, 'AI DIRECT+', 'native-two-confirm'),
                                      (self.workspace, 'SI DIRECT+', 'single-range-confirm')]:
            (root / 'src/go_hotel').mkdir(parents=True)
            (root / 'frontend').mkdir()
            (root / 'src/go_hotel/__init__.py').write_text('')
            (root / 'frontend/logo.svg').write_text(brand)
            (root / 'frontend/date-range.js').write_text(calendar)
            (root / 'src/go_hotel/main.py').write_text(
                "from pathlib import Path\n"
                "root=Path(__file__).resolve().parents[2]/'frontend'\n"
                "print((root/'logo.svg').read_text())\n"
                "print((root/'date-range.js').read_text())\n")

    def load(self, path):
        env = dict(os.environ, PYTHONPATH=str(path / 'src'), PYTHONDONTWRITEBYTECODE='1')
        return subprocess.check_output([sys.executable, '-m', 'go_hotel.main'],
                                       cwd=self.workspace, env=env, text=True).splitlines()

    def test_old_builder_passes_candidate_checks_but_compose_loads_old_frontend(self):
        self.assertEqual(self.load(self.workspace), ['SI DIRECT+', 'single-range-confirm'])
        self.assertEqual(self.load(self.app), ['AI DIRECT+', 'native-two-confirm'])

    def test_replacing_deployed_root_loads_both_fixes_and_removes_deleted_files(self):
        (self.app / 'src/obsolete.py').write_text('old base-only module')
        shutil.rmtree(self.app)  # isolated, test-owned fixture only
        shutil.copytree(self.workspace, self.app)
        self.assertEqual(self.load(self.app), ['SI DIRECT+', 'single-range-confirm'])
        self.assertFalse((self.app / 'src/obsolete.py').exists())

    def test_recipe_and_deployment_share_one_source_root(self):
        recipe = (ROOT / 'hk-staging/Dockerfile.go-application-python-v2').read_text()
        commands = [line for line in recipe.splitlines() if line and not line.startswith('#')]
        self.assertIn('WORKDIR /app', commands)
        self.assertIn('COPY . /app', commands)
        self.assertIn('ENV PYTHONPATH=/app/src', commands)
        self.assertLess(commands.index('RUN rm -rf /app'), commands.index('COPY . /app'))
        self.assertFalse(any('/workspace' in line for line in commands))
        compose = (ROOT.parents[1] / 'deploy/hk-staging/docker-compose.business-runtime.yml').read_text()
        self.assertIn('PYTHONPATH: /app/src', compose)

    def test_source_digest_rejects_old_frontend_and_extra_base_files(self):
        expected = test_pr.runtime_source_digest(self.workspace)
        self.assertNotEqual(test_pr.runtime_source_digest(self.app), expected)
        shutil.rmtree(self.app)
        shutil.copytree(self.workspace, self.app)
        self.assertEqual(test_pr.runtime_source_digest(self.app), expected)
        (self.app / 'src/old.py').write_text('stale')
        self.assertNotEqual(test_pr.runtime_source_digest(self.app), expected)

    def test_digest_gate_program_runs_and_refuses_stale_bytes(self):
        import inspect
        program = ('import hashlib,pathlib\n' + inspect.getsource(test_pr.runtime_source_digest)
                   + '\nassert runtime_source_digest(pathlib.Path(' + repr(str(self.app))
                   + ')) == ' + repr(test_pr.runtime_source_digest(self.workspace)))
        rejected = subprocess.run([sys.executable, '-c', program], capture_output=True)
        self.assertNotEqual(rejected.returncode, 0)
        shutil.rmtree(self.app)
        shutil.copytree(self.workspace, self.app)
        accepted = subprocess.run([sys.executable, '-c', program], capture_output=True)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)


class RuntimeGateTests(unittest.TestCase):
    def test_gate_uses_deployment_override_not_only_image_default(self):
        fixture = durability.TestPrDurabilityTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        runner, result = fixture.build()
        gate = next(call for call in runner.calls if 'python -c ' in call[-1])
        self.assertIn('PYTHONPATH=/app/src', gate)
        self.assertEqual(gate[gate.index('--workdir') + 1], '/app')
        self.assertIn("find_spec('go_hotel')", gate[-1])
        self.assertIn('/app/src/go_hotel/__init__.py', gate[-1])
        self.assertNotIn('/workspace', gate[-1])
        self.assertEqual(result['executor_version'], 'test-pr-v4-runtime-root')


if __name__ == '__main__':
    unittest.main()
