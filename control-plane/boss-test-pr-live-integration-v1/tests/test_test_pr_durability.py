"""B4-B1 regression: a TEST_PR result may only claim a *durable* artifact.

The defect this closes: TEST_PR V2 built an image, reported ``built_image_id`` in
signed Evidence, and deleted the image in its ``finally`` block.  The Evidence was
true and the artifact was gone, so nothing could later CANARY or DEPLOY it.  The
distinction the contract now has to keep is

    BUILD_IDENTITY_PROVEN   !=   ARTIFACT_DURABILITY_PROVEN

and that distinction is what these tests hold:

* a build whose gates fail is never sealed (no ``docker save`` happens at all)
* a build whose gates pass is sealed *after* them, and the sealed package identity
  is the one the Evidence carries
* the temporary build tag is still removed, so the sealed package — not a stray
  Docker image — is the only delivery path
* Evidence refuses a TEST_PR result that reports a build identity with no durable
  artifact, or a package whose image identity is not the image that was built

No Docker daemon and no host store are used; the runner is a recording fixture and
the store is a temporary directory.
"""
import hashlib
import io
import json
import os
import pathlib
import stat
import sys
import tarfile
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hk-staging"))

from hk_agent import artifact_store, test_pr, transport  # noqa: E402

POSIX = os.name == "posix"
COMMIT = "c" * 40
CONFIG = b'{"architecture":"amd64"}'
# The build's image id is the SHA256 of its config blob, which is exactly what the
# sealed package has to reproduce.
IMAGE_ID = "sha256:" + hashlib.sha256(CONFIG).hexdigest()
PROFILE_SHA = test_pr.DEPENDENCY_PROFILE_SHA256


class Completed:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def save_archive(path, config_bytes):
    digest = hashlib.sha256(config_bytes).hexdigest()
    index = json.dumps([{"Config": digest, "RepoTags": [], "Layers": []}]).encode()
    with tarfile.open(path, "w") as tar:
        for name, payload in ((digest, config_bytes), ("manifest.json", index)):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return "sha256:" + digest


class BuilderRunner:
    """A TEST_PR build with no Docker: only the argv the builder would use."""

    def __init__(self, fail_gate=None):
        self.workspace = None
        self.fail_gate = fail_gate
        self.calls = []

    def __call__(self, argv, *, cwd=None, env=None, timeout=300):
        self.calls.append(list(argv))
        if argv[0] == "/usr/bin/git":
            if argv[1] == "init":
                self.workspace = pathlib.Path(argv[-1])
                return Completed("")
            if "checkout" in argv:
                context = self.workspace / "application"
                context.mkdir(parents=True, exist_ok=True)
                (context / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
                return Completed("")
            if "rev-parse" in argv:
                return Completed(COMMIT)
            return Completed("")
        if argv[0] != "/usr/bin/docker":
            raise AssertionError(argv)
        verb = argv[1]
        if verb == "image":
            # The builder base is pinned by id; the freshly built tag reports the
            # build's own image id.
            return Completed(test_pr.BUILDER_IMAGE_ID
                             if argv[3] == test_pr.BUILDER_IMAGE else IMAGE_ID)
        if verb == "run":
            if self.fail_gate == "dependency_profile":
                return Completed("not-a-digest")
            if self.fail_gate == "isolated_checks":
                raise test_pr.Reject("TEST_PR_SUBPROCESS_REJECT")
            if "--mount" in argv:
                return Completed(PROFILE_SHA)
            return Completed("")
        if verb == "build":
            return Completed("")
        if verb == "load":
            return Completed("Loaded image")
        if verb == "save":
            destination = argv[argv.index("--output") + 1]
            save_archive(destination, CONFIG)
            return Completed("")
        raise AssertionError(argv)

    def verbs(self):
        return [call[1] for call in self.calls]


class TestPrDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.store = self.root / "store"
        self.store.mkdir(mode=0o700)
        (self.store / "objects").mkdir(mode=0o700)
        self._patch(test_pr, "_build_root", lambda: self.root)
        self._patch(test_pr, "ARTIFACT_STORE", str(self.store))
        self._patch(test_pr, "BUILDER_IMAGE", "go-hotel:depth48-runtime-6d0fd905")
        # The store's trust anchor is the account that writes it.  In production
        # that is go-hk-agent (systemd User=go-hk-agent); here it is whatever owns
        # the temporary store, so the ownership rule itself stays live.
        self.identity = (os.stat(self.store).st_uid, os.stat(self.store).st_gid)
        self._patch(artifact_store, "_IDENTITY_RESOLVER", lambda: self.identity)
        # ... and the writer gate compares the running account with that anchor, so
        # pin it too: this suite is about durability, not about who is running.
        self._patch(artifact_store, "_process_identity", lambda: self.identity)
        if not POSIX:
            self._patch(artifact_store, "DIRECTORY_MODE",
                        stat.S_IMODE(os.stat(self.store).st_mode))
            self._patch(artifact_store, "FILE_MODE", 0o666)
            self._patch(artifact_store, "UNTRUSTED_BITS", 0)
        # The build path writes its own tag; keep it out of any real Docker state.
        self._patch(test_pr, "DOCKERFILE", str(self.root / "Dockerfile.stub"))
        (self.root / "Dockerfile.stub").write_text("FROM scratch\n", encoding="utf-8")
        # `execute` removes the temporary tag in its `finally`.  That subprocess is
        # the one call the fixture runner does not own, so it is stubbed out here.
        self._patch(test_pr, "subprocess", types.SimpleNamespace(
            run=lambda *a, **k: None, PIPE=None, DEVNULL=None,
            CalledProcessError=test_pr.subprocess.CalledProcessError,
            SubprocessError=test_pr.subprocess.SubprocessError))

    def _patch(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(setattr, module, name, original)

    def task(self):
        return {"task_id": "go-boss-test-pr-52-" + "a" * 12, "nonce": "n" * 16,
                "action_id": "HK_STAGING_TEST_PR", "environment": "HK-STAGING-01",
                "authority": "GO-COMMAND-CENTER",
                "parameters": {"builder_profile": test_pr.PROFILE,
                               "source": {"repository": test_pr.REPOSITORY,
                                          "pr_number": "52", "commit_sha": COMMIT}}}

    def build(self, **kwargs):
        """Run one TEST_PR execution; return the runner and the result (or None)."""
        runner = BuilderRunner(**kwargs)
        try:
            return runner, test_pr.execute(self.task(), runner=runner)
        except test_pr.Reject:
            return runner, None

    # ------------------------------------------------------------------ gates
    def test_a_build_whose_isolated_checks_fail_is_never_sealed(self):
        runner, result = self.build(fail_gate="isolated_checks")
        self.assertIsNone(result)
        self.assertNotIn("save", runner.verbs())

    def test_a_build_whose_profile_check_fails_is_never_sealed(self):
        runner, result = self.build(fail_gate="dependency_profile")
        self.assertIsNone(result)
        self.assertNotIn("save", runner.verbs())

    # ------------------------------------------------------------------ seal
    def test_a_passing_build_seals_last_and_reports_the_package(self):
        runner, result = self.build()
        self.assertEqual(result["result"], "TEST_PR_OK")
        self.assertEqual(result["executor_version"], "test-pr-v3")
        self.assertEqual(result["built_image_id"], IMAGE_ID)
        self.assertEqual(result["artifact_durability"], "PROVEN")
        self.assertEqual(result["artifact_package"]["image_id"], IMAGE_ID)
        self.assertEqual(result["artifact_package"]["schema"], artifact_store.SCHEMA)
        self.assertEqual(result["gate_results"]["artifact_sealed"], "PASS")
        # The seal is the last Docker verb: nothing after it can invalidate the
        # package, and nothing before it could have been sealed by accident.
        self.assertEqual(runner.verbs()[-1], "save")
        stored = self.store / "objects" / (result["artifact_package"]["package_sha256"] + ".tar")
        self.assertTrue(stored.is_file())

    def test_the_build_tag_is_still_removed_after_sealing(self):
        # The finally block runs `docker image rm`; the durable copy is the package,
        # not a second, untracked image in Docker.
        source = (ROOT / "hk-staging" / "hk_agent" / "test_pr.py").read_text(encoding="utf-8")
        self.assertIn('"image", "rm", "--force", image', source)
        runner, _ = self.build()
        self.assertIn("save", runner.verbs())

    def test_the_sealed_package_resolves_back_to_the_built_image(self):
        _, result = self.build()
        package = result["artifact_package"]["package_sha256"]
        runner = BuilderRunner()
        loaded = artifact_store.load(runner, package, result["built_image_id"],
                                     str(self.store))
        self.assertEqual(loaded["load"], "PASS")
        self.assertEqual(runner.verbs()[-1], "image")
        self.assertEqual(hashlib.sha256(b'{"architecture":"amd64"}').hexdigest(),
                         result["built_image_id"].split(":", 1)[1])

    # --------------------------------------------------------------- evidence
    def evidence_for(self, result):
        task = {"task_id": "go-boss-test-pr-52-" + "a" * 12, "nonce": "n" * 16,
                "action_id": "HK_STAGING_TEST_PR", "environment": "HK-STAGING-01",
                "parameters": {}}
        return transport.evidence(task, result)

    def test_evidence_refuses_a_build_identity_with_no_durable_artifact(self):
        _, result = self.build()
        for missing in ("artifact_package", "artifact_durability"):
            broken = {k: v for k, v in result.items() if k != missing}
            with self.assertRaisesRegex(transport.Reject, "EXECUTOR_RESULT_REJECT"):
                self.evidence_for(broken)
        not_proven = dict(result, artifact_durability="NOT_PROVEN")
        with self.assertRaisesRegex(transport.Reject, "ARTIFACT_DURABILITY_REJECT"):
            self.evidence_for(not_proven)

    def test_evidence_refuses_a_package_that_is_not_the_built_image(self):
        _, result = self.build()
        wrong = dict(result, artifact_package=dict(result["artifact_package"],
                                                   image_id="sha256:" + "e" * 64))
        with self.assertRaisesRegex(transport.Reject, "ARTIFACT_DURABILITY_REJECT"):
            self.evidence_for(wrong)

    def test_evidence_refuses_a_package_with_no_content_address(self):
        _, result = self.build()
        for value in ("not-a-digest", "", None, "A" * 64):
            wrong = dict(result, artifact_package=dict(result["artifact_package"],
                                                       package_sha256=value))
            with self.assertRaisesRegex(transport.Reject, "ARTIFACT_DURABILITY_REJECT"):
                self.evidence_for(wrong)

    def test_evidence_carries_the_package_when_it_is_durable(self):
        _, result = self.build()
        record = self.evidence_for(result)
        self.assertEqual(record["artifact_durability"], "PROVEN")
        self.assertEqual(record["artifact_package"]["image_id"], record["built_image_id"])
        self.assertEqual(record["status"], "SUCCESS")

    def test_the_durability_failure_is_its_own_stage(self):
        """A build with no durable artifact is not an executor refusal."""
        self.assertEqual(transport.FAILURE_KIND_BY_STAGE[transport.STAGE_ARTIFACT_DURABILITY],
                         "ARTIFACT_DURABILITY_FAILED")
        self.assertEqual(transport.FAILURE_REASON_BY_STAGE[transport.STAGE_ARTIFACT_DURABILITY],
                         "ARTIFACT_DURABILITY_REJECT")
        self.assertIn("ARTIFACT_DURABILITY_REJECT", transport.FAILURE_REASON_CODES)
        self.assertNotIn(transport.STAGE_ARTIFACT_DURABILITY, transport.EXECUTION_STAGES)


if __name__ == "__main__":
    unittest.main()
