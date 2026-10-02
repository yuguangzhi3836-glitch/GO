"""Merge guard: the v4 runtime-root gate and the live dependency-graph gate must
BOTH remain reachable and actually execute in the merged TEST_PR executor.

Neither source PR can prove this on its own.  PR #311 tests only the runtime-root
capability; the PR172/PR245 line tests only the dependency capability.  The real
risk of a three-way merge is that one side silently overwrote the other, so this
module drives the merged executor end to end with the shared recording runner and
asserts that a single build both

  * runs the frozen, networkless uvicorn[standard] dependency-graph probe, and
  * runs the ``/app`` runtime-root + source-digest gate,

and that a failure in either one still fails the build closed (no sealing).

No Docker daemon, no host store and no live host are used: the runner is the
recording fixture from ``test_test_pr_durability``, and the "image" is that
fixture's synthetic OCI save.
"""
import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hk-staging"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_test_pr_durability as durability  # noqa: E402
from hk_agent import test_pr  # noqa: E402

SOURCE = ROOT / "hk-staging" / "hk_agent" / "test_pr.py"
PROBE = test_pr.STANDARD_DEPENDENCIES_PROGRAM
STANDARD = test_pr.STANDARD_DEPENDENCY_PROFILE_SHA256
LEGACY = test_pr.DEPENDENCY_PROFILE_SHA256


class ProfileBuilderRunner(durability.BuilderRunner):
    """The shared recording runner, told what the two dependency probes answer."""

    def __init__(self, profile_digest, probe_output="UVICORN_STANDARD_DEPS_OK\n",
                 fail_runtime_gate=False, **kwargs):
        super().__init__(**kwargs)
        self.profile_digest = profile_digest
        self.probe_output = probe_output
        self.fail_runtime_gate = fail_runtime_gate

    def __call__(self, argv, *, cwd=None, env=None, timeout=300):
        is_docker_run = bool(argv) and argv[0] == "/usr/bin/docker" and len(argv) > 1 and argv[1] == "run"
        if is_docker_run:
            if "--mount" in argv:                       # profile digest computation
                self.calls.append(list(argv))
                return durability.Completed(self.profile_digest)
            if argv[-1] == PROBE:                       # dependency-graph probe
                self.calls.append(list(argv))
                return durability.Completed(self.probe_output)
            if self.fail_runtime_gate and any("find_spec('go_hotel')" in a for a in argv):
                self.calls.append(list(argv))
                raise test_pr.Reject("TEST_PR_SUBPROCESS_REJECT")
        return super().__call__(argv, cwd=cwd, env=env, timeout=timeout)

    def probe_argv(self):
        return [c for c in self.calls if c and c[0] == "/usr/bin/docker" and c[-1] == PROBE]

    def runtime_gate_argv(self):
        return [c for c in self.calls
                if c and c[0] == "/usr/bin/docker"
                and any("find_spec('go_hotel')" in a for a in c)]


class MergeGuardTests(unittest.TestCase):
    def setUp(self):
        fixture = durability.TestPrDurabilityTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        self.fixture = fixture

    def run_build(self, **kwargs):
        runner = ProfileBuilderRunner(**kwargs)
        try:
            return runner, test_pr.execute(self.fixture.task(), runner=runner)
        except test_pr.Reject:
            return runner, None

    # ------------------------------------------------------- both checks live
    def test_one_build_executes_both_the_dependency_probe_and_the_runtime_gate(self):
        runner, result = self.run_build(profile_digest=STANDARD)
        self.assertIsNotNone(result, "merged executor rejected a standard-profile build")
        self.assertEqual(result["executor_version"], "test-pr-v4-runtime-root")
        self.assertEqual(result["result"], "TEST_PR_OK")

        probes = runner.probe_argv()
        self.assertEqual(len(probes), 1,
                         "the dependency-graph probe must run exactly once, not zero times")
        probe = probes[0]
        self.assertEqual(probe[probe.index("--network") + 1], "none")
        self.assertIn("--read-only", probe)
        self.assertIn("-I", probe)
        self.assertNotIn("--mount", probe)
        self.assertNotIn("--env", probe)

        gates = runner.runtime_gate_argv()
        self.assertEqual(len(gates), 1,
                         "the runtime-root gate must run exactly once, not zero times")
        gate = gates[0]
        self.assertEqual(gate[gate.index("--workdir") + 1], "/app")
        self.assertIn("PYTHONPATH=/app/src", gate)
        script = gate[-1]
        self.assertIn("find_spec('go_hotel')", script)
        self.assertIn("/app/src/go_hotel/__init__.py", script)
        self.assertIn("runtime_source_digest", script)
        self.assertIn("compileall -q /app/src", script)
        self.assertIn("alembic heads", script)
        self.assertNotIn("/workspace", script)

        self.assertIn("save", runner.verbs())

    def test_the_legacy_profile_keeps_its_old_path_and_needs_no_probe(self):
        """The call site must still route by profile, not pin one recipe."""
        runner, result = self.run_build(profile_digest=LEGACY)
        self.assertIsNotNone(result)
        self.assertEqual(runner.probe_argv(), [],
                         "a legacy-profile build must not be forced through the standard probe")

    # ------------------------------------------------------- both checks bite
    def test_a_failing_dependency_probe_fails_the_build_closed(self):
        runner, result = self.run_build(profile_digest=STANDARD,
                                        probe_output="DEPENDENCY_MISSING:httptools\n")
        self.assertIsNone(result, "a failed dependency graph must not produce a build")
        self.assertNotIn("save", runner.verbs())
        self.assertEqual(len(runner.probe_argv()), 1)

    def test_an_unrecognised_profile_digest_fails_the_build_closed(self):
        runner, result = self.run_build(profile_digest="f" * 64)
        self.assertIsNone(result)
        self.assertNotIn("save", runner.verbs())
        self.assertEqual(runner.probe_argv(), [],
                         "an unknown recipe must be refused before any probe runs")

    def test_a_failing_runtime_root_gate_fails_the_build_closed(self):
        runner, result = self.run_build(profile_digest=LEGACY, fail_runtime_gate=True)
        self.assertIsNone(result, "an import-root mismatch must not produce a build")
        self.assertNotIn("save", runner.verbs())
        self.assertEqual(len(runner.runtime_gate_argv()), 1)

    # ------------------------------------------------------- structural proof
    def test_execute_references_both_checks_structurally(self):
        """AST, not grep: `execute` must call the dependency verifier AND build a
        source-digest assertion from `runtime_source_digest`."""
        module = ast.parse(SOURCE.read_text(encoding="utf-8"))
        defined = {n.name for n in ast.walk(module)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn("_verify_dependency_profile", defined)
        self.assertIn("runtime_source_digest", defined)

        execute = next(n for n in ast.walk(module)
                       if isinstance(n, ast.FunctionDef) and n.name == "execute")
        called = {n.func.id for n in ast.walk(execute)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_verify_dependency_profile", called,
                      "execute must call the dependency verifier")
        referenced = {n.id for n in ast.walk(execute) if isinstance(n, ast.Name)}
        self.assertIn("runtime_source_digest", referenced,
                      "execute must bind the runtime source digest gate")


if __name__ == "__main__":
    unittest.main()
