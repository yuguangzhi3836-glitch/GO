import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import command_center as cc
import hk_executor as hk


COMMIT = "b5732c02dd95092a63def7eaa0d2cf332b1e2996"
AT = dt.datetime(2026, 9, 12, 1, 30, tzinfo=dt.timezone.utc)


class FakeSigner(cc.TaskSigner):
    def sign(self, payload):
        return "test-signature:" + str(len(payload))


class MatchingVerifier(hk.SignatureVerifier):
    def verify(self, payload, signature):
        return signature == "test-signature:" + str(len(payload))


def request(**overrides):
    value = {
        "schema_version": "1",
        "request_id": "boss-test-pr-42-20260912",
        "action_id": cc.ACTION,
        "environment": cc.ENVIRONMENT,
        "pr_number": "42",
        "requested_at": cc.iso(AT),
    }
    value.update(overrides)
    return cc.canonical(value)


class CommandCenterTests(unittest.TestCase):
    def test_request_accepts_only_pr_number_and_fixed_policy(self):
        got = cc.validate_request(request(), AT)
        self.assertEqual(got["pr_number"], "42")
        for raw in (request(repository=cc.GO_SOURCE_REPOSITORY), request(commit_sha=COMMIT), request(action_id="HK_STAGING_DEPLOY"), request(pr_number="042")):
            with self.assertRaises(cc.Reject):
                cc.validate_request(raw, AT)

    def test_resolver_accepts_exact_mutable_ref_then_returns_immutable_sha(self):
        calls = []
        def runner(argv):
            calls.append(argv)
            return COMMIT + "\trefs/pull/42/head\n"
        resolved = cc.GitHubPullRequestResolver(runner).resolve("42")
        self.assertEqual(resolved, cc.ResolvedPullRequest("42", COMMIT))
        self.assertEqual(calls, [["/usr/bin/git", "ls-remote", cc.GO_SOURCE_REPOSITORY, "refs/pull/42/head"]])

    def test_resolver_rejects_missing_or_non_sha_head(self):
        for output in ("", "main\trefs/pull/42/head\n", COMMIT + "\trefs/heads/main\n", COMMIT + "\trefs/pull/42/head\n" + COMMIT + "\trefs/pull/42/head\n"):
            with self.assertRaises(cc.Reject):
                cc.GitHubPullRequestResolver(lambda _: output).resolve("42")

    def test_task_freezes_the_resolved_commit(self):
        parsed = cc.validate_request(request(), AT)
        task = cc.derive_task(parsed, cc.ResolvedPullRequest("42", COMMIT), FakeSigner(), AT)
        self.assertEqual(task["source"], {"repository": cc.GO_SOURCE_REPOSITORY, "pr_number": "42", "commit_sha": COMMIT})
        self.assertEqual(task["parameters"], {"builder_profile": hk.PROFILE})
        self.assertNotIn("ref", task["source"])
        self.assertEqual(len(cc.task_sha256(task)), 64)
        with self.assertRaises(cc.Reject):
            cc.derive_task(parsed, cc.ResolvedPullRequest("41", COMMIT), FakeSigner(), AT)

    def test_ledger_prevents_request_replay_and_duplicate_source(self):
        parsed = cc.validate_request(request(), AT)
        ledger = cc.ReplayLedger()
        resolved = cc.ResolvedPullRequest("42", COMMIT)
        ledger.claim(parsed, resolved)
        with self.assertRaises(cc.Reject):
            ledger.claim(parsed, resolved)
        other = cc.validate_request(request(request_id="boss-test-pr-42-second"), AT)
        with self.assertRaises(cc.Reject):
            ledger.claim(other, resolved)


class HKExecutorTests(unittest.TestCase):
    def task(self):
        parsed = cc.validate_request(request(), AT)
        return cc.derive_task(parsed, cc.ResolvedPullRequest("42", COMMIT), FakeSigner(), AT)

    def test_hk_refuses_ref_repository_profile_and_signature_overrides(self):
        task = self.task()
        self.assertEqual(hk.validate_task(task, MatchingVerifier(), AT)["commit_sha"], COMMIT)
        for mutate in (
            lambda x: x["source"].update({"ref": "refs/pull/42/head"}),
            lambda x: x["source"].update({"repository": "https://evil.example/GO.git"}),
            lambda x: x["parameters"].update({"command": "id"}),
            lambda x: x.update({"services": ["api"]}),
        ):
            bad = self.task()
            mutate(bad)
            with self.assertRaises(hk.Reject):
                hk.validate_task(bad, MatchingVerifier(), AT)

    def test_source_reader_clears_interactive_and_global_git_credentials(self):
        env = hk.source_reader_environment({"GIT_ASKPASS": "bad", "GIT_CONFIG_GLOBAL": "bad", "PATH": "/usr/bin"})
        self.assertNotIn("GIT_ASKPASS", env)
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertIn(hk.DEPLOY_KEY, env["GIT_SSH_COMMAND"])

    def test_fetch_uses_the_sha_not_mutable_pr_ref(self):
        with tempfile.TemporaryDirectory() as root:
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                if argv[-2:] == ["rev-parse", "FETCH_HEAD"]:
                    return hk.Completed(0, COMMIT + "\n")
                return hk.Completed(0)
            executor = hk.IsolatedTestPRExecutor(runner=runner, build_root=root, clock=lambda: AT)
            # The source layout check is an independent filesystem assertion;
            # seed the directory only when checkout is requested by the fake.
            original = executor._checked
            def checked(argv, **kwargs):
                result = original(argv, **kwargs)
                if len(argv) >= 2 and argv[-2] == "--quiet" and argv[-1] == COMMIT:
                    Path(argv[2], hk.SOURCE_SUBDIRECTORY).mkdir(parents=True, exist_ok=True)
                    Path(argv[2], hk.SOURCE_SUBDIRECTORY, "pyproject.toml").write_text("[project]\nname='x'\n")
                return result
            executor._checked = checked
            workspace = executor.fetch_exact_source(COMMIT)
            try:
                joined = "\n".join(" ".join(call) for call in calls)
                self.assertIn("fetch --no-tags --depth 1 origin " + COMMIT, joined)
                self.assertNotIn("refs/pull", joined)
            finally:
                import shutil
                shutil.rmtree(workspace, ignore_errors=True)

    def test_e2e_simulation_builds_only_with_fixed_profile_and_isolation(self):
        with tempfile.TemporaryDirectory() as root:
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                if argv[:5] == [hk.DOCKER, "image", "inspect", hk.IsolatedTestPRExecutor.image_tag(COMMIT), "--format"]:
                    return hk.Completed(0, "sha256:" + "a" * 64 + "\n")
                return hk.Completed(0)
            executor = hk.IsolatedTestPRExecutor(runner=runner, build_root=root, clock=lambda: AT)
            source = Path(root, "fixture")
            Path(source, hk.SOURCE_SUBDIRECTORY).mkdir(parents=True)
            Path(source, hk.SOURCE_SUBDIRECTORY, "pyproject.toml").write_text("[project]\nname='x'\n")
            executor.fetch_exact_source = lambda sha: str(source)
            result = executor.run(self.task(), MatchingVerifier())
            self.assertEqual(result["result"], "TEST_PR_OK")
            commands = [" ".join(call) for call in calls]
            build = next(item for item in commands if item.startswith(hk.DOCKER + " build"))
            runtime = next(item for item in commands if item.startswith(hk.DOCKER + " run"))
            self.assertIn("--network none", build)
            self.assertIn(hk.DOCKERFILE, build)
            self.assertIn("--network none --read-only --cap-drop ALL", runtime)
            self.assertNotIn("compose", "\n".join(commands))
            evidence = hk.evidence_payload(self.task(), result)
            self.assertFalse(evidence["deployment_performed"])
            self.assertFalse(evidence["application_health_proven"])


if __name__ == "__main__":
    unittest.main()
