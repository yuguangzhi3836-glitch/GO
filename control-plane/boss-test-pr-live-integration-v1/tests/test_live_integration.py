import datetime as dt
import hashlib
import importlib.machinery
import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.modules.setdefault("fcntl", types.SimpleNamespace(LOCK_EX=0, LOCK_UN=0, flock=lambda *args, **kwargs: None))
loader = importlib.machinery.SourceFileLoader("bridge_candidate", str(ROOT / "command-center" / "go-boss-request-bridge"))
spec = importlib.util.spec_from_loader(loader.name, loader)
bridge = importlib.util.module_from_spec(spec)
loader.exec_module(bridge)
sys.path.insert(0, str(ROOT / "hk-staging"))
from hk_agent import test_pr, transport


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.request = {
            "schema_version": "1", "request_id": "test-pr-request-001",
            "action_id": "HK_STAGING_TEST_PR", "environment": "HK-STAGING-01",
            "pr_number": "42", "requested_at": bridge.iso(self.at),
        }

    def test_verify_contract_is_still_accepted(self):
        request = {"schema_version": "1", "request_id": "verify-request-001",
                   "action_id": "HK_STAGING_VERIFY", "environment": "HK-STAGING-01",
                   "requested_at": bridge.iso(self.at)}
        self.assertEqual(bridge.validate_request(bridge.canonical(request), self.at)["action_id"], "HK_STAGING_VERIFY")

    def test_test_pr_rejects_every_caller_override(self):
        self.assertEqual(bridge.validate_request(bridge.canonical(self.request), self.at)["pr_number"], "42")
        for key, value in (("repository", "https://invalid"), ("ref", "refs/heads/main"),
                           ("commit_sha", "a" * 40), ("build_command", "id"),
                           ("dockerfile", "Dockerfile"), ("network", "host"),
                           ("services", ["api"])):
            bad = dict(self.request)
            bad[key] = value
            with self.assertRaises(bridge.Reject):
                bridge.validate_request(bridge.canonical(bad), self.at)

    def test_real_ed25519_signature_and_hk_evidence_adapter(self):
        task = bridge.derive_test_pr(self.request, self.at, lambda _: "b5732c02dd95092a63def7eaa0d2cf332b1e2996")
        self.assertNotIn("ref", task["parameters"]["source"])
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = pathlib.Path(raw)
            private = Ed25519PrivateKey.generate()
            pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            public = private.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
            (root / "signer.pem").write_bytes(pem)
            (root / "verify.pub").write_bytes(public)
            signed = bridge.sign(task, root / "signer.pem")
            private.public_key().verify(bytes.fromhex(signed["signature"]), bridge.canonical(task))
            ledger = transport.Ledger(str(root / "ledger.sqlite3"))
            transport.validate(signed, {"environment": "HK-STAGING-01", "authority": "GO-COMMAND-CENTER", "task_verify_key": str(root / "verify.pub")}, ledger)
            original = test_pr.execute
            try:
                test_pr.execute = lambda _: {
                    "schema_version": "1", "executor_version": "test-pr-v1", "action_id": "HK_STAGING_TEST_PR",
                    "status": "SUCCESS", "result": "TEST_PR_OK", "source_pr_number": "42",
                    "source_commit_sha": task["parameters"]["source"]["commit_sha"],
                    "task_canonical_sha256": hashlib.sha256(transport.canonical(signed)).hexdigest(),
                    "built_image_id": "sha256:" + "a" * 64, "gate_results": {"source_commit": "PASS"},
                    "application_health_proven": False, "deployment_performed": False,
                }
                evidence = transport.evidence(signed, transport.dispatch_action(signed))
            finally:
                test_pr.execute = original
            self.assertFalse(evidence["application_health_proven"])
            self.assertFalse(evidence["deployment_performed"])
            self.assertEqual(evidence["source_commit_sha"], task["parameters"]["source"]["commit_sha"])

    def test_fixed_fetch_and_isolation_literals(self):
        source = (ROOT / "hk-staging" / "hk_agent" / "test_pr.py").read_text(encoding="utf-8")
        self.assertIn('["/usr/bin/git", "-C", str(workspace), "fetch", "--no-tags", "--depth", "1", "origin", commit]', source)
        self.assertIn('"--network", "none"', source)
        self.assertIn('"--read-only", "--cap-drop", "ALL"', source)
        self.assertNotIn("docker compose", source.lower())

    def test_persistent_replay_and_publish_shape_remain_integrated(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = pathlib.Path(raw)
            channel = root / "channel.json"
            channel.write_text('{"version":3,"mode":"PERSISTENT","publish_enabled":true,"allowed_actions":["HK_STAGING_VERIFY","HK_STAGING_TEST_PR"],"allowed_environment":"HK-STAGING-01"}')
            private = Ed25519PrivateKey.generate()
            (root / "signer.pem").write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            request = dict(self.request)
            proposal = {"path": "requests/test-pr-request-001.json", "raw": bridge.canonical(request)}
            task = bridge.derive_test_pr(request, self.at, lambda _: "b5732c02dd95092a63def7eaa0d2cf332b1e2996")
            original = bridge.read_pr, bridge.derive_formal_task, bridge.publish_task, bridge.remote_task
            published = {}
            try:
                bridge.read_pr = lambda *_: proposal
                bridge.derive_formal_task = lambda _: task
                bridge.publish_task = lambda value: published.setdefault("task", value) and "c" * 40
                bridge.remote_task = lambda _: bridge.canonical(published["task"]) + b"\n"
                first = bridge.persistent_process("7", "a" * 40, str(root / "ledger"), str(root / "signer.pem"), str(channel))
                self.assertEqual(first["status"], "published")
                self.assertEqual(published["task"]["parameters"]["source"]["commit_sha"], task["parameters"]["source"]["commit_sha"])
                self.assertEqual(bridge.persistent_process("7", "a" * 40, str(root / "ledger"), str(root / "signer.pem"), str(channel))["status"], "already_seen")
            finally:
                bridge.read_pr, bridge.derive_formal_task, bridge.publish_task, bridge.remote_task = original


if __name__ == "__main__":
    unittest.main()
