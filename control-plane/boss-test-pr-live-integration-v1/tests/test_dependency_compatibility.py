"""Issue184: extras must exist in the frozen image, and refusals stay specific."""
import email.message
import importlib.metadata
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hk-staging"))
from hk_agent import test_pr


class StandardDependencyTests(unittest.TestCase):
    def setUp(self):
        namespace = {"__name__": "isolated_probe_fixture"}
        exec(compile(test_pr.STANDARD_DEPENDENCIES_PROGRAM, "<trusted-probe>", "exec"), namespace)
        self.verify = namespace["verify_standard"]
        self.dists = {}
        self.add("uvicorn", "0.35", [
            "h11>=0.16", "click>=7",
            'httptools>=0.6; extra == "standard"',
            'watchfiles>=0.13; extra == "standard"',
            'irrelevant>=9; sys_platform == "never-a-platform"',
            'unused>=1; extra == "other"'
        ], extras=["standard", "other"])
        self.add("h11", "0.16")
        self.add("click", "8.2")
        self.add("httptools", "0.6.4")
        self.add("watchfiles", "1.1", ["anyio>=3"])
        self.add("anyio", "4.9", ["idna>=2.8"])
        self.add("idna", "3.10")

    def add(self, name, version, requires=None, extras=()):
        message = email.message.Message()
        for extra in extras:
            message["Provides-Extra"] = extra
        self.dists[name] = types.SimpleNamespace(version=version, metadata=message, requires=requires)

    def distribution(self, name):
        if name not in self.dists:
            raise importlib.metadata.PackageNotFoundError(name)
        return self.dists[name]

    def test_complete_active_dependency_closure_passes(self):
        self.assertEqual(self.verify(self.distribution), "UVICORN_STANDARD_DEPS_OK")

    def test_missing_direct_extra_is_rejected(self):
        del self.dists["httptools"]
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_MISSING:httptools"):
            self.verify(self.distribution)

    def test_missing_transitive_dependency_is_rejected(self):
        del self.dists["idna"]
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_MISSING:idna"):
            self.verify(self.distribution)

    def test_incompatible_root_version_is_rejected(self):
        self.dists["uvicorn"].version = "0.29"
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_VERSION_REJECT:uvicorn"):
            self.verify(self.distribution)

    def test_incompatible_extra_version_is_rejected(self):
        self.dists["httptools"].version = "0.1"
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_VERSION_REJECT:httptools"):
            self.verify(self.distribution)

    def test_unrequested_prerelease_is_rejected(self):
        self.dists["uvicorn"].version = "0.99rc1"
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_VERSION_REJECT:uvicorn"):
            self.verify(self.distribution)

    def test_undeclared_standard_extra_is_rejected(self):
        del self.dists["uvicorn"].metadata["Provides-Extra"]
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_EXTRA_REJECT:uvicorn"):
            self.verify(self.distribution)

    def test_missing_root_metadata_is_not_vacuous_success(self):
        self.dists["uvicorn"].requires = None
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_METADATA_REJECT:uvicorn"):
            self.verify(self.distribution)

    def test_selected_nested_extras_are_checked(self):
        self.dists["watchfiles"].requires = ["anyio[tls]>=3"]
        self.dists["anyio"].metadata["Provides-Extra"] = "tls"
        self.dists["anyio"].requires = ['certifi>=2024; extra == "tls"']
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_MISSING:certifi"):
            self.verify(self.distribution)

    def test_unselected_extra_and_inactive_platform_do_not_require_packages(self):
        self.assertNotIn("unused", self.dists)
        self.assertNotIn("irrelevant", self.dists)
        self.assertEqual(self.verify(self.distribution), "UVICORN_STANDARD_DEPS_OK")

    def test_direct_url_dependency_is_not_accepted(self):
        self.dists["watchfiles"].requires = ["anyio @ https://example.invalid/package.whl"]
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_GRAPH_REJECT"):
            self.verify(self.distribution)

    def test_repeated_dependency_constraints_are_all_checked(self):
        self.dists["uvicorn"].requires.extend(["anyio>=3", "anyio>=999"])
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_VERSION_REJECT:anyio"):
            self.verify(self.distribution)

    def test_metadata_cycle_terminates(self):
        self.dists["idna"].requires = ["anyio>=3"]
        self.assertEqual(self.verify(self.distribution), "UVICORN_STANDARD_DEPS_OK")

    def test_oversized_metadata_graph_is_rejected(self):
        self.dists["uvicorn"].requires.extend(["idna>=2"] * 257)
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_GRAPH_REJECT"):
            self.verify(self.distribution)

    def test_malformed_requirement_does_not_pass(self):
        self.dists["uvicorn"].requires.append("not a valid requirement ???")
        with self.assertRaises(Exception):
            self.verify(self.distribution)

    def test_legacy_profile_keeps_its_existing_path(self):
        test_pr._verify_dependency_profile(test_pr.DEPENDENCY_PROFILE_SHA256,
                                          lambda *args, **kwargs: self.fail("unexpected probe"))

    def test_unknown_profile_never_reaches_probe(self):
        with self.assertRaisesRegex(test_pr.Reject, "TEST_PR_DEPENDENCY_PROFILE_REJECT"):
            test_pr._verify_dependency_profile("f" * 64,
                                              lambda *args, **kwargs: self.fail("unexpected probe"))

    def test_standard_profile_requires_isolated_probe(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return types.SimpleNamespace(stdout="UVICORN_STANDARD_DEPS_OK\n", returncode=0)
        test_pr._verify_dependency_profile(test_pr.STANDARD_DEPENDENCY_PROFILE_SHA256, runner)
        argv, kwargs = calls[0]
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertIn("--read-only", argv)
        self.assertIn("-I", argv)
        self.assertNotIn("--mount", argv)
        self.assertNotIn("--env", argv)
        self.assertEqual(argv[-1], test_pr.STANDARD_DEPENDENCIES_PROGRAM)
        self.assertEqual(kwargs["timeout"], 60)

    def test_failed_probe_preserves_bounded_failure(self):
        def runner(*args, **kwargs):
            error = test_pr.Reject("TEST_PR_SUBPROCESS_REJECT")
            error.stderr = "DEPENDENCY_MISSING:httptools"
            error.returncode = 1
            raise error
        with self.assertRaisesRegex(test_pr.Reject, "TEST_PR_DEPENDENCY_ENVIRONMENT_REJECT") as caught:
            test_pr._verify_dependency_profile(test_pr.STANDARD_DEPENDENCY_PROFILE_SHA256, runner)
        self.assertEqual(caught.exception.stderr, "DEPENDENCY_MISSING:httptools")
        self.assertEqual(caught.exception.returncode, 1)

    def test_wrong_probe_terminal_output_is_rejected(self):
        with self.assertRaisesRegex(test_pr.Reject, "TEST_PR_DEPENDENCY_ENVIRONMENT_REJECT"):
            test_pr._verify_dependency_profile(
                test_pr.STANDARD_DEPENDENCY_PROFILE_SHA256,
                lambda *a, **kw: types.SimpleNamespace(stdout="some check passed", returncode=0))


if __name__ == "__main__":
    unittest.main()
