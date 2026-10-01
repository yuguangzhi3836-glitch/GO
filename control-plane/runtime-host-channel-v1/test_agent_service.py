"""Contract tests for agent_service.py (the validated Management Agent entry point).

These tests are offline: temporary filesystem, temporary SQLite, in-memory fakes.
No network, no real GitHub transport, no SSH, no Runtime/Agent start.

agent_service.protected_read is patched to a plain reader because the real one
requires root-owned paths; root-owned/symlink/mode enforcement itself is already
covered by test_adapter.py against real fixtures.
"""
import hashlib
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import agent_service
import channel
import git_transport


def plain_read(path, max_bytes=16384):
    with open(path, "rb") as fh:
        return fh.read(max_bytes)


def pem_public(key):
    return key.public_key().public_bytes(ser.Encoding.PEM, ser.PublicFormat.SubjectPublicKeyInfo)


class FakeTransport:
    """In-memory stand-in for GitTransport. No network, no git."""

    def __init__(self, initial=None):
        self.store = dict(initial or {})

    def keys(self):
        return sorted(self.store)

    def read(self, key):
        return self.store.get(key)

    def create(self, key, raw):
        if key in self.store and self.store[key] != raw:
            raise channel.Reject("transport_conflict")
        self.store[key] = raw


class AgentServiceContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # captured before patching, so the "fixed constant" test sees the shipped value
        self.shipped_config_path = agent_service.CONFIG_PATH
        self.keys = self.root / "keys"
        self.keys.mkdir()
        self.bundle = self.root / "agent"
        self.bundle.mkdir()
        (self.bundle / "alpha.py").write_bytes(b"print('alpha')\n")
        (self.bundle / "beta.py").write_bytes(b"print('beta')\n")
        (self.bundle / "notes.txt").write_bytes(b"not a module\n")
        self.authority = Ed25519PrivateKey.generate()
        (self.keys / "authority.pub").write_bytes(pem_public(self.authority))
        try:
            (self.keys / "authority.pub").chmod(0o644)
        except PermissionError:  # NTFS may refuse; ownership check is patched out anyway
            pass
        self.evidence = Ed25519PrivateKey.generate()
        raw = self.evidence.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
        self.evidence_key_sha256 = hashlib.sha256(raw).hexdigest()
        (self.keys / "evidence.pem").write_bytes(
            self.evidence.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()))
        self.executor = agent_service.compute_executor_sha256(str(self.bundle))[0]
        self.config_path = self.root / "agent.json"
        self.registration_path = self.root / "registration.json"
        self.registry_db = self.root / "registry.db"
        self.cfg = {
            "version": 1,
            "environment": "GO-RUNTIME-TEST-01",
            "host_id": "i-j6cg7euc4ggol8gkijog",
            "agent_id": "go-runtime-test-01-agent",
            "registration_path": str(self.registration_path),
            "authority_public_path": str(self.keys / "authority.pub"),
            "task_public_path": str(self.keys / "authority.pub"),
            "evidence_private_path": str(self.keys / "evidence.pem"),
            "executor_bundle_dir": str(self.bundle),
            "registry_db": str(self.registry_db),
            "tasks": {"remote": "git@example.invalid:tasks.git", "branch": "main",
                      "key": str(self.keys / "tasks-read"), "known_hosts": str(self.keys / "kh")},
            "evidence": {"remote": "git@example.invalid:evidence.git", "branch": "permission-test",
                         "key": str(self.keys / "evidence-write"), "known_hosts": str(self.keys / "kh")},
            "tick_seconds": 30,
        }
        self.config_path.write_text(json.dumps(self.cfg), encoding="utf-8")
        self.patches = [
            mock.patch.object(agent_service, "CONFIG_PATH", str(self.config_path)),
            mock.patch.object(agent_service, "protected_read", plain_read),
            mock.patch.object(agent_service, "observe_live_host_id",
                              lambda: self.cfg["host_id"]),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def write_registration(self, **overrides):
        body = {
            "version": 1, "kind": "runtime-host-registration",
            "environment": self.cfg["environment"], "host_id": self.cfg["host_id"],
            "agent_id": self.cfg["agent_id"], "generation": 1,
            "candidate_sha": "7b9d53adb99b0523c1563ad388ac593ad800c864",
            "plan_sha256": "a" * 64,
            "executor_sha256": self.executor,
            "evidence_key_sha256": self.evidence_key_sha256,
            "approval_ref": "approval-7b9f6a99599db06b",
            "issued_at": int(time.time()) - 5,
            "expires_at": int(time.time()) + 3600,
            "actions": [channel.ACTION],
        }
        body.update(overrides)
        raw = channel.signed(body, self.authority)
        self.registration_path.write_bytes(raw)
        return raw

    # ---- fixed configuration surface -------------------------------------
    def test_config_path_is_a_fixed_absolute_constant(self):
        self.assertEqual(self.shipped_config_path, "/etc/go-runtime-host/agent.json")

    def test_imds_identity_url_is_a_fixed_constant(self):
        self.assertEqual(agent_service.IMDS_INSTANCE_ID,
                         "http://100.100.100.200/latest/meta-data/instance-id")

    def test_only_once_flag_is_accepted(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = agent_service.main(["agent_service.py", "--extra"])
        self.assertEqual(rc, 1)
        self.assertIn("bad_argument", err.getvalue())

    def test_once_without_config_is_a_clean_refusal(self):
        with mock.patch.object(agent_service, "CONFIG_PATH", str(self.root / "absent.json")):
            err = io.StringIO()
            with redirect_stderr(err):
                rc = agent_service.main(["agent_service.py", "--once"])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED", err.getvalue())

    def test_no_shell_execution_path(self):
        src = Path(agent_service.__file__).read_text(encoding="utf-8")
        self.assertNotIn("shell=True", src)
        self.assertNotIn("os.system", src)
        self.assertNotIn("subprocess", src)

    # ---- path/remote shape validation ------------------------------------
    def test_check_path_rejects_relative_and_parent_traversal(self):
        for bad in ("relative/x", "/a/../b", ""):
            with self.assertRaises(channel.Reject):
                agent_service.check_path(bad, "x")

    def test_check_remote_rejects_non_git_and_option_injection(self):
        for bad in ("http://example.invalid/x", "-oProxyCommand=id", "git@x\ny", ""):
            with self.assertRaises(channel.Reject):
                agent_service.check_remote(bad, "x")

    # ---- executor manifest -------------------------------------------------
    def test_executor_digest_is_deterministic(self):
        first = agent_service.compute_executor_sha256(str(self.bundle))
        second = agent_service.compute_executor_sha256(str(self.bundle))
        self.assertEqual(first, second)
        self.assertEqual(first[1], ["alpha.py", "beta.py"])

    def test_executor_digest_matches_independent_manifest(self):
        digest, names = agent_service.compute_executor_sha256(str(self.bundle))
        parts = []
        for name in sorted(names, key=lambda s: s.encode("utf-8")):
            h = hashlib.sha256((self.bundle / name).read_bytes()).hexdigest()
            parts.append("%s  %s\n" % (h, name))
        self.assertEqual(digest, hashlib.sha256("".join(parts).encode("utf-8")).hexdigest())

    def test_executor_digest_ignores_non_python_files(self):
        before = agent_service.compute_executor_sha256(str(self.bundle))[0]
        (self.bundle / "extra.txt").write_bytes(b"x\n")
        self.assertEqual(before, agent_service.compute_executor_sha256(str(self.bundle))[0])

    def test_executor_digest_changes_when_bundle_changes(self):
        before = agent_service.compute_executor_sha256(str(self.bundle))[0]
        (self.bundle / "gamma.py").write_bytes(b"print('gamma')\n")
        self.assertNotEqual(before, agent_service.compute_executor_sha256(str(self.bundle))[0])

    # ---- binding, fail closed ---------------------------------------------
    def _run_once(self):
        registry = [None]
        tasks, evidence = FakeTransport(), FakeTransport()
        with mock.patch.object(agent_service, "GitTransport",
                               side_effect=[tasks, evidence]), \
                redirect_stderr(io.StringIO()):
            return agent_service.one_pass(self.cfg, registry)

    def test_matching_registration_passes(self):
        self.write_registration()
        self.assertEqual(self._run_once(), 0)

    def test_executor_digest_mismatch_fails_closed(self):
        self.write_registration(executor_sha256="f" * 64)
        with self.assertRaises(channel.Reject) as ctx:
            self._run_once()
        self.assertEqual(str(ctx.exception), "local_executor_mismatch")

    def test_registration_binding_mismatch_fails_closed(self):
        self.write_registration(host_id="i-someotherhost")
        with self.assertRaises(channel.Reject) as ctx:
            self._run_once()
        self.assertEqual(str(ctx.exception), "config_registration_binding")

    def test_live_host_mismatch_fails_closed(self):
        with mock.patch.object(agent_service, "observe_live_host_id", lambda: "i-not-this-host"):
            self.write_registration()
            with self.assertRaises(channel.Reject) as ctx:
                self._run_once()
        self.assertEqual(str(ctx.exception), "local_host_mismatch")

    def test_host_identity_is_not_taken_from_config_self_claim(self):
        """A wrong live host id must refuse even though config claims the right one."""
        self.write_registration()
        cfg = dict(self.cfg)
        cfg["host_id"] = "i-j6cg7euc4ggol8gkijog"
        with mock.patch.object(agent_service, "observe_live_host_id", lambda: "i-live-differs"):
            with self.assertRaises(channel.Reject):
                self._run_once()

    # ---- action / namespace surface ----------------------------------------
    def test_only_action_is_the_probe(self):
        self.assertEqual(channel.ACTION, "RUNTIME_HOST_PROBE_V1")

    def test_transport_namespace_is_runtime_host_v1(self):
        self.assertEqual(git_transport.PREFIX, "runtime-host-v1/")
        tasks = git_transport.GitTransport("git@example.invalid:x.git", "main", "tasks",
                                          git_env={"GIT_TERMINAL_PROMPT": "0"})
        evidence = git_transport.GitTransport("git@example.invalid:x.git", "permission-test",
                                             "evidence", git_env={"GIT_TERMINAL_PROMPT": "0"})
        self.assertEqual(tasks.path("tasks/abc.json"), "runtime-host-v1/tasks/abc.json")
        self.assertEqual(evidence.path("evidence/abc.json"), "runtime-host-v1/evidence/abc.json")
        with self.assertRaises(channel.Reject):
            tasks.path("tasks/../../escape.json")
        with self.assertRaises(channel.Reject):
            tasks.path("evidence/abc.json")


if __name__ == "__main__":
    unittest.main()
