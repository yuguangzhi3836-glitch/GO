"""Offline contract tests for registration_sync.py.

No network, no real GitHub transport, no SSH, no Runtime start, no Agent start,
no Task execution. Temporary filesystem, in-memory transport and, for the
namespace-isolation cases, a local bare Git fixture.

Covers: highest valid generation selection, rollback refusal, same-generation byte
conflict refusal, wrong host / agent / signer / expired / wrong-binding rejection,
atomic replacement, and preservation of the previous registration when the
replacement fails half way.
"""
import contextlib
import hashlib
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import agent_service
import channel
import registration_sync as sync
from channel import Reject
from git_transport import GitTransport

NOW = 1_700_000_000


def plain_read(path, max_bytes=16384):
    """Mirrors adapter.protected_read's failure mode without the root-only checks."""
    try:
        with open(path, "rb") as fh:
            return fh.read(max_bytes)
    except OSError as exc:
        raise Reject("protected_read") from exc


class FakeTransport:
    def __init__(self, initial=None):
        self.store = dict(initial or {})

    def keys(self):
        return sorted(self.store)

    def read(self, key):
        return self.store.get(key)

    def create(self, key, raw):
        if key in self.store and self.store[key] != raw:
            raise Reject("transport_conflict")
        self.store[key] = raw


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.authority = Ed25519PrivateKey.generate()
        self.other_authority = Ed25519PrivateKey.generate()
        self.authority_pub = self.root / "cc-test-signer.pub"
        self.authority_pub.write_bytes(self.authority.public_key().public_bytes(
            ser.Encoding.PEM, ser.PublicFormat.SubjectPublicKeyInfo))
        self.evidence = Ed25519PrivateKey.generate()
        raw_pub = self.evidence.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
        self.evidence_key_sha256 = hashlib.sha256(raw_pub).hexdigest()
        self.evidence_pub = self.root / "evidence-signing.pub"
        self.evidence_pub.write_bytes(self.evidence.public_key().public_bytes(
            ser.Encoding.PEM, ser.PublicFormat.SubjectPublicKeyInfo))

        self.bundle = self.root / "agent"
        self.bundle.mkdir()
        (self.bundle / "alpha.py").write_bytes(b"print('alpha')\n")
        (self.bundle / "beta.py").write_bytes(b"print('beta')\n")
        self.executor = agent_service.compute_executor_sha256(str(self.bundle))[0]

        self.config_path = self.root / "registration-sync.json"
        self.registration_path = self.root / "registration.json"
        self.cfg = {
            "version": 1,
            "environment": "GO-RUNTIME-TEST-01",
            "host_id": "i-j6cg7euc4ggol8gkijog",
            "agent_id": "go-runtime-test-01-agent",
            "candidate_sha": "7b9d53adb99b0523c1563ad388ac593ad800c864",
            "plan_sha256": "a" * 64,
            "registration_path": str(self.registration_path),
            "authority_public_path": str(self.authority_pub),
            "evidence_public_path": str(self.evidence_pub),
            "bundle_dir": str(self.bundle),
            "registrations": {"remote": "git@example.invalid:tasks.git", "branch": "main",
                              "key": str(self.root / "tasks-read"),
                              "known_hosts": str(self.root / "kh")},
        }
        self.config_path.write_text(json.dumps(self.cfg), encoding="utf-8")
        self.patches = [
            mock.patch.object(sync, "CONFIG_PATH", str(self.config_path)),
            mock.patch.object(sync, "protected_read", plain_read),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    # ---- fixtures ----------------------------------------------------------
    def body(self, generation, **overrides):
        value = {
            "version": 1, "kind": "runtime-host-registration",
            "environment": self.cfg["environment"], "host_id": self.cfg["host_id"],
            "agent_id": self.cfg["agent_id"], "generation": generation,
            "candidate_sha": self.cfg["candidate_sha"], "plan_sha256": self.cfg["plan_sha256"],
            "executor_sha256": self.executor, "evidence_key_sha256": self.evidence_key_sha256,
            "approval_ref": "approval-7b9f6a99599db06b",
            "issued_at": NOW - 60, "expires_at": NOW + 3600,
            "actions": [channel.ACTION],
        }
        value.update(overrides)
        return value

    def key(self, generation):
        return "registrations/%s-g%06d.json" % (self.cfg["agent_id"], generation)

    def remote(self, generation, signer=None, **overrides):
        raw = channel.signed(self.body(generation, **overrides), signer or self.authority)
        return self.key(generation), raw

    def install_local(self, generation, **overrides):
        raw = channel.signed(self.body(generation, **overrides), self.authority)
        self.registration_path.write_bytes(raw)
        os.chmod(self.registration_path, 0o600)
        return raw

    def run_sync(self, transport, clock=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = sync.sync_once(self.cfg, transport, clock or (lambda: NOW))
        return rc, json.loads(buf.getvalue().strip().splitlines()[-1])

    # ---- argument / surface -------------------------------------------------
    def test_no_command_line_arguments_are_accepted(self):
        self.assertEqual(sync.main(["p", "sync", "--force"]), 1)

    def test_no_shell_execution_path(self):
        src = Path(sync.__file__).read_text(encoding="utf-8")
        self.assertNotIn("shell=True", src)
        self.assertNotIn("os.system", src)
        self.assertNotIn("subprocess", src)

    def test_sync_uses_only_the_registrations_namespace(self):
        captured = {}

        class Spy(GitTransport):
            def __init__(self, remote, branch, kind, *, git_env):
                captured["kind"], captured["branch"] = kind, branch
                raise Reject("stop-here")

        with mock.patch.object(sync, "GitTransport", Spy):
            self.assertRaises(Reject, sync.registration_transport, self.cfg)
        self.assertEqual(captured["kind"], "registrations")
        self.assertEqual(captured["branch"], "main")

    # ---- highest valid generation ------------------------------------------
    def test_generation_advances_one_two_three(self):
        transport = FakeTransport()
        key2, raw2 = self.remote(2)
        transport.store[key2] = raw2
        rc, status = self.run_sync(transport)
        self.assertEqual((rc, status["result"], status["generation"]), (0, "UPDATED", 2))
        self.assertEqual(self.registration_path.read_bytes(), raw2)

        key3, raw3 = self.remote(3)
        transport.store[key3] = raw3
        rc, status = self.run_sync(transport)
        self.assertEqual((rc, status["result"], status["generation"],
                          status["previous_generation"]), (0, "UPDATED", 3, 2))
        self.assertEqual(self.registration_path.read_bytes(), raw3)

    def test_highest_valid_generation_wins(self):
        transport = FakeTransport()
        for generation in (2, 3, 4):
            key, raw = self.remote(generation)
            transport.store[key] = raw
        rc, status = self.run_sync(transport)
        self.assertEqual(status["generation"], 4)
        self.assertEqual(status["candidates"], 3)

    def test_invalid_candidates_are_skipped_not_fatal(self):
        transport = FakeTransport()
        for generation, overrides in ((2, {"host_id": "i-otherhost"}),
                                      (3, {"agent_id": "other-agent"}),
                                      (4, {"evidence_key_sha256": "9" * 64})):
            key, raw = self.remote(generation, **overrides)
            transport.store[key] = raw
        key5, raw5 = self.remote(5)
        transport.store[key5] = raw5
        rc, status = self.run_sync(transport)
        self.assertEqual(status["generation"], 5)
        self.assertEqual(status["candidates"], 1)

    def test_boots_from_zero_when_nothing_is_installed(self):
        transport = FakeTransport()
        key, raw = self.remote(2)
        transport.store[key] = raw
        self.assertFalse(self.registration_path.exists())
        rc, status = self.run_sync(transport)
        self.assertEqual((status["result"], status["local_generation"], status["generation"]),
                         ("UPDATED", 0, 2))

    def test_no_candidate_leaves_everything_alone(self):
        local = self.install_local(2)
        rc, status = self.run_sync(FakeTransport())
        self.assertEqual((rc, status["result"]), (0, "NO_CANDIDATE"))
        self.assertEqual(self.registration_path.read_bytes(), local)

    # ---- rollback / same generation -----------------------------------------
    def test_generation_rollback_is_refused(self):
        local = self.install_local(5)
        transport = FakeTransport()
        key, raw = self.remote(4)
        transport.store[key] = raw
        self.assertRaises(Reject, sync.sync_once, self.cfg, transport, lambda: NOW)
        self.assertEqual(self.registration_path.read_bytes(), local)

    def test_same_generation_with_different_bytes_is_refused(self):
        local = self.install_local(5)
        transport = FakeTransport()
        key, raw = self.remote(5, issued_at=NOW - 30, expires_at=NOW + 1800)
        transport.store[key] = raw
        self.assertNotEqual(raw, local)
        self.assertRaises(Reject, sync.sync_once, self.cfg, transport, lambda: NOW)
        self.assertEqual(self.registration_path.read_bytes(), local)

    def test_same_generation_with_identical_bytes_is_up_to_date(self):
        local = self.install_local(5)
        transport = FakeTransport()
        key, raw = self.remote(5)
        transport.store[key] = raw
        self.assertEqual(local, raw)
        rc, status = self.run_sync(transport)
        self.assertEqual((rc, status["result"]), (0, "UP_TO_DATE"))
        self.assertEqual(self.registration_path.read_bytes(), local)

    # ---- identity / signer / expiry ----------------------------------------
    def test_wrong_host_is_not_applied(self):
        local = self.install_local(2)
        transport = FakeTransport()
        key, raw = self.remote(3, host_id="i-someotherhost")
        transport.store[key] = raw
        rc, status = self.run_sync(transport)
        self.assertEqual(status["result"], "NO_CANDIDATE")
        self.assertEqual(self.registration_path.read_bytes(), local)

    def test_wrong_agent_is_not_applied(self):
        local = self.install_local(2)
        transport = FakeTransport()
        key, raw = self.remote(3, agent_id="some-other-agent")
        transport.store[key] = raw
        rc, status = self.run_sync(transport)
        self.assertEqual(status["result"], "NO_CANDIDATE")
        self.assertEqual(self.registration_path.read_bytes(), local)

    def test_wrong_signer_is_not_applied(self):
        local = self.install_local(2)
        transport = FakeTransport()
        key, raw = self.remote(3, signer=self.other_authority)
        transport.store[key] = raw
        rc, status = self.run_sync(transport)
        self.assertEqual(status["result"], "NO_CANDIDATE")
        self.assertEqual(self.registration_path.read_bytes(), local)

    def test_expired_registration_is_not_applied(self):
        local = self.install_local(2)
        transport = FakeTransport()
        key, raw = self.remote(3, issued_at=NOW - 7200, expires_at=NOW - 3600)
        transport.store[key] = raw
        rc, status = self.run_sync(transport)
        self.assertEqual(status["result"], "NO_CANDIDATE")
        self.assertEqual(self.registration_path.read_bytes(), local)

    def test_over_long_lifetime_is_not_applied(self):
        local = self.install_local(2)
        transport = FakeTransport()
        key, raw = self.remote(3, issued_at=NOW - 60, expires_at=NOW + 86400 + 60)
        transport.store[key] = raw
        rc, status = self.run_sync(transport)
        self.assertEqual(status["result"], "NO_CANDIDATE")
        self.assertEqual(self.registration_path.read_bytes(), local)

    def test_wrong_candidate_plan_or_executor_is_not_applied(self):
        for overrides in ({"candidate_sha": "deadbeef" * 5},
                          {"plan_sha256": "b" * 64},
                          {"executor_sha256": "c" * 64}):
            local = self.install_local(2)
            transport = FakeTransport()
            key, raw = self.remote(3, **overrides)
            transport.store[key] = raw
            rc, status = self.run_sync(transport)
            self.assertEqual(status["result"], "NO_CANDIDATE", list(overrides))
            self.assertEqual(self.registration_path.read_bytes(), local)

    def test_corrupt_local_registration_refuses(self):
        self.registration_path.write_bytes(b"not json at all")
        transport = FakeTransport()
        key, raw = self.remote(3)
        transport.store[key] = raw
        self.assertRaises(Reject, sync.sync_once, self.cfg, transport, lambda: NOW)

    # ---- atomic replacement -------------------------------------------------
    def test_installed_registration_is_root_only(self):
        transport = FakeTransport()
        key, raw = self.remote(2)
        transport.store[key] = raw
        self.run_sync(transport)
        self.assertEqual(stat.S_IMODE(os.stat(self.registration_path).st_mode), 0o600)
        self.assertEqual(os.stat(self.registration_path).st_uid, 0)

    def test_replacement_is_atomic_and_leaves_no_temporary_file(self):
        transport = FakeTransport()
        key, raw = self.remote(2)
        transport.store[key] = raw
        with mock.patch.object(sync.os, "replace", wraps=os.replace) as replace:
            self.run_sync(transport)
        replace.assert_called_once()
        source, destination = replace.call_args[0]
        self.assertEqual(os.path.dirname(source), os.path.dirname(destination))
        self.assertEqual(destination, str(self.registration_path))
        leftovers = [p.name for p in self.root.iterdir() if p.name.startswith(".registration")]
        self.assertEqual(leftovers, [])

    def test_failed_replacement_keeps_the_previous_registration(self):
        local = self.install_local(2)
        transport = FakeTransport()
        key, raw = self.remote(3)
        transport.store[key] = raw
        with mock.patch.object(sync.os, "replace", side_effect=OSError("disk full")):
            self.assertRaises(OSError, sync.sync_once, self.cfg, transport, lambda: NOW)
        self.assertEqual(self.registration_path.read_bytes(), local)
        leftovers = [p.name for p in self.root.iterdir() if p.name.startswith(".registration")]
        self.assertEqual(leftovers, [])

    def test_main_refuses_cleanly_without_config(self):
        with mock.patch.object(sync, "CONFIG_PATH", str(self.root / "absent.json")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = sync.main(["registration_sync.py"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(buf.getvalue().strip())["status"], "REFUSED")


class NamespaceIsolationTests(unittest.TestCase):
    """Real GitTransport against a local bare repository. No network."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        seed, bare = root / "seed", root / "remote.git"
        subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
        (seed / "README").write_text("isolated fixture\n")
        subprocess.run(["git", "-C", str(seed), "add", "README"], check=True)
        subprocess.run(["git", "-C", str(seed), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@localhost", "commit", "-qm", "fixture"],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "clone", "--bare", "-q", str(seed), str(bare)], check=True)
        self.bare = str(bare)

    def tearDown(self):
        self.tmp.cleanup()

    def transport(self, kind):
        return GitTransport(self.bare, "main", kind, git_env=dict(os.environ))

    def test_registrations_do_not_appear_in_tasks_or_evidence_keys(self):
        registrations = self.transport("registrations")
        registrations.create("registrations/fixture-agent-g000001.json", b"one")
        self.assertEqual(registrations.keys(), ["registrations/fixture-agent-g000001.json"])
        self.assertEqual(self.transport("tasks").keys(), [])
        self.assertEqual(self.transport("evidence").keys(), [])

    def test_cross_namespace_keys_are_rejected(self):
        tasks, registrations = self.transport("tasks"), self.transport("registrations")
        with self.assertRaises(Reject):
            tasks.path("registrations/fixture.json")
        with self.assertRaises(Reject):
            registrations.path("tasks/fixture.json")
        self.assertEqual(registrations.path("registrations/fixture.json"),
                         "runtime-host-v1/registrations/fixture.json")

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(Reject):
            GitTransport(self.bare, "main", "deployments", git_env=dict(os.environ))

    def test_task_behaviour_is_unchanged(self):
        tasks = self.transport("tasks")
        tasks.create("tasks/fixture-task.json", b"one")
        self.assertEqual(tasks.read("tasks/fixture-task.json"), b"one")
        with self.assertRaises(Reject):
            tasks.create("tasks/fixture-task.json", b"two")


if __name__ == "__main__":
    unittest.main()
