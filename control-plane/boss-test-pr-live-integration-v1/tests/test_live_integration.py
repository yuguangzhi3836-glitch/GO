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

    def test_command_center_backup_and_rollback_guard_set_is_complete(self):
        install = (ROOT / "install" / "install-command-center.sh").read_text(encoding="utf-8")
        rollback = (ROOT / "install" / "uninstall.sh").read_text(encoding="utf-8")
        preflight = (ROOT / "install" / "preflight.sh").read_text(encoding="utf-8")
        self.assertIn("sha256sum -c SHA256SUMS", install)
        self.assertIn("record /usr/local/libexec/go-boss-request-bridge go-boss-request-bridge", install)
        self.assertIn("record /etc/go-command-center/boss-request-bridge-v1.json boss-request-bridge-v1.json", install)
        self.assertIn('test ! -e "$backup/state.tsv"', install)
        self.assertIn("88880363d761eb924aac1910caa7696619dbbb0b4fcb112b63cf726de3bf1335", preflight)
        self.assertIn('test "$(sha256sum "$path" | awk', rollback)
        self.assertIn('test "$(sha256sum "$backup/$name" | awk', rollback)
        self.assertIn("restore go-boss-request-bridge /usr/local/libexec/go-boss-request-bridge", rollback)
        self.assertIn("restore boss-request-bridge-v1.json /etc/go-command-center/boss-request-bridge-v1.json", rollback)
        self.assertIn("cp -p", rollback)
        self.assertLess(rollback.index('test "$(sha256sum "$path" | awk'), rollback.index("cp -p"))

    def test_hk_backup_and_rollback_guard_set_is_complete(self):
        install = (ROOT / "install" / "install-hk-agent.sh").read_text(encoding="utf-8")
        rollback = (ROOT / "install" / "uninstall.sh").read_text(encoding="utf-8")
        preflight = (ROOT / "install" / "preflight.sh").read_text(encoding="utf-8")
        for statement in (
            "record /opt/go-hk-agent-rebuilt/hk_agent/transport.py transport.py",
            "record /etc/go-hk-agent/agent.json agent.json",
            "record /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py test_pr.py",
            "record /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1 Dockerfile.go-application-python-v1",
        ):
            self.assertIn(statement, install)
        self.assertIn("82ab805b921081ec0299ffa20576963476e12f57e711438f46ada2342a7c7b30", preflight)
        self.assertIn("test ! -e /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py", preflight)
        self.assertIn("test ! -e /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1", preflight)
        self.assertIn('elif test "$existed" = absent; then', rollback)
        self.assertIn('rm -- "$path"', rollback)
        self.assertIn("restore transport.py /opt/go-hk-agent-rebuilt/hk_agent/transport.py", rollback)
        self.assertIn("restore agent.json /etc/go-hk-agent/agent.json", rollback)
        self.assertIn("restore test_pr.py /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py", rollback)
        self.assertIn("restore Dockerfile.go-application-python-v1 /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1", rollback)
        self.assertIn('test "$(sha256sum "$path" | awk', rollback)
        self.assertLess(rollback.index('test "$(sha256sum "$path" | awk'), rollback.index('rm -- "$path"'))


if __name__ == "__main__":
    unittest.main()
