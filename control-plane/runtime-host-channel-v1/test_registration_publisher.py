"""Offline contract tests for registration_publisher.py.

No network, no real GitHub transport, no SSH, no Task publication, no registration
publication to any real repository. Temporary filesystem only.

Covers the rotation contract: strict generation increase, the configured deployment
floor, durable pre-network persistence, readback-only reconciliation of an
ambiguous push, and the fixed binding checks.
"""
import base64
import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import channel
import registration_publisher as pub


def die_reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except SystemExit as exc:
        return exc.code
    raise AssertionError("expected SystemExit")


class FakeTransport:
    """In-memory stand-in for GitTransport. No network, no git."""

    def __init__(self, initial=None, fail_after=False, drop=False, fail_before=0):
        self.store = dict(initial or {})
        self.writes = 0
        self.created = []
        self.fail_after = fail_after
        self.drop = drop
        self.fail_before = fail_before

    def keys(self):
        return sorted(self.store)

    def read(self, key):
        return self.store.get(key)

    def create(self, key, raw):
        self.writes += 1
        self.created.append((key, raw))
        if self.fail_before > 0:
            self.fail_before -= 1
            raise OSError("push failed before the object existed")
        if self.drop:
            return  # a write that never reached the remote
        if key in self.store:
            if self.store[key] != raw:
                raise channel.Reject("transport_conflict")
            return
        self.store[key] = raw
        if self.fail_after:
            raise OSError("connection lost after write")


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.signer = Ed25519PrivateKey.generate()
        self.priv = self.root / "signer.pem"
        self.pub = self.root / "signer.pub"
        self.priv.write_bytes(self.signer.private_bytes(
            ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()))
        self.pub.write_bytes(self.signer.public_key().public_bytes(
            ser.Encoding.PEM, ser.PublicFormat.SubjectPublicKeyInfo))
        self.plan_path = self.root / "install-plan.json"
        self.approval_path = self.root / "approval.json"
        self.publisher_path = self.root / "publisher.json"
        self.state_dir = self.root / "state"
        self.state_dir.mkdir()
        self.state_path = self.state_dir / "registration-generation.json"
        self.clock = lambda: 1_700_000_000

    def tearDown(self):
        self.tmp.cleanup()

    # ---- fixtures ----------------------------------------------------------
    def write_plan(self, **overrides):
        plan = {
            "environment": "GO-RUNTIME-TEST-01",
            "host_id": "i-j6cg7euc4ggol8gkijog",
            "agent_id": "go-runtime-test-01-agent",
            "candidate": {"sha": "7b9d53adb99b0523c1563ad388ac593ad800c864"},
            "management_agent": {"executor_sha256": "0" * 64},
            "evidence_key": {"evidence_key_sha256": "1" * 64},
        }
        plan.update(overrides)
        self.plan_path.write_bytes(json.dumps(plan, sort_keys=True,
                                              separators=(",", ":")).encode("utf-8") + b"\n")
        return hashlib.sha256(self.plan_path.read_bytes()).hexdigest()

    def write_approval(self, plan_sha256, **overrides):
        binding = {"plan_sha256": plan_sha256, "executor_sha256": "0" * 64,
                   "evidence_key_sha256": "1" * 64,
                   "candidate": "7b9d53adb99b0523c1563ad388ac593ad800c864",
                   "environment": "GO-RUNTIME-TEST-01",
                   "host_id": "i-j6cg7euc4ggol8gkijog",
                   "agent_id": "go-runtime-test-01-agent"}
        binding.update(overrides)
        approval = {"approval_ref": "approval-7b9f6a99599db06b",
                    "approval_status": "HUMAN_APPROVED_BOUNDED_TEST",
                    "binding": binding}
        self.approval_path.write_text(json.dumps(approval), encoding="utf-8")

    def make_cfg(self, plan_sha256, **overrides):
        cfg = {"version": 1, "environment": "GO-RUNTIME-TEST-01",
               "host_id": "i-j6cg7euc4ggol8gkijog", "agent_id": "go-runtime-test-01-agent",
               "candidate_sha": "7b9d53adb99b0523c1563ad388ac593ad800c864",
               "plan_sha256": plan_sha256, "executor_sha256": "0" * 64,
               "evidence_key_sha256": "1" * 64,
               "approval_ref": "approval-7b9f6a99599db06b",
               "required_approval_status": "HUMAN_APPROVED_BOUNDED_TEST",
               "deployment_first_generation": 2,
               "signer_private_key": str(self.priv), "signer_public_key": str(self.pub),
               "tasks": {"remote": "git@example.invalid:tasks.git", "branch": "main",
                         "key": "/k"}}
        cfg.update(overrides)
        self.publisher_path.write_text(json.dumps(cfg), encoding="utf-8")
        return cfg

    def prepared(self, **overrides):
        plan_sha = self.write_plan()
        cfg = self.make_cfg(plan_sha, **overrides)
        self.write_approval(plan_sha)
        return cfg

    def patched(self):
        return mock.patch.multiple(
            pub, PUBLISHER_JSON=str(self.publisher_path), APPROVAL_JSON=str(self.approval_path),
            PLAN_JSON=str(self.plan_path), STATE_DIR=str(self.state_dir),
            GENERATION_STATE=str(self.state_path))

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    # ---- lifetime is never extended ---------------------------------------
    def test_registration_lifetime_is_the_protocol_maximum(self):
        self.assertEqual(pub.REGISTRATION_LIFETIME_SECONDS, 86400)
        self.assertLessEqual(pub.REGISTRATION_LIFETIME_SECONDS, 86400)
        src = Path(pub.__file__).read_text(encoding="utf-8")
        self.assertIn("86400", src)

    # ---- argument surface --------------------------------------------------
    def test_no_command_line_arguments_are_accepted(self):
        for argv in (["p", "sign-registration"], ["p", "publish"], ["p", "deploy"],
                     ["p", "--force"], ["p", "host=i-other"]):
            self.assertEqual(die_reason(pub.main, argv), 1)

    def test_no_shell_execution_path(self):
        src = Path(pub.__file__).read_text(encoding="utf-8")
        self.assertNotIn("shell=True", src)
        self.assertNotIn("os.system", src)
        self.assertNotIn("subprocess", src)

    # ---- binding -----------------------------------------------------------
    def test_binding_matrix_rejects_every_field_mismatch(self):
        plan_sha = self.write_plan()
        cfg = self.make_cfg(plan_sha)
        cases = {"executor_sha256": "2" * 64, "evidence_key_sha256": "3" * 64,
                 "candidate": "4" * 40, "environment": "OTHER-ENV",
                 "host_id": "i-otherhost", "agent_id": "other-agent"}
        for field, bad in cases.items():
            self.write_approval(plan_sha, **{field: bad})
            with self.patched():
                approval = json.loads(self.approval_path.read_text(encoding="utf-8"))
                plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
                self.assertEqual(die_reason(pub.check_binding, cfg, approval, plan,
                                            self.plan_path.read_bytes()), 1, field)

    def test_plan_digest_is_recomputed_locally(self):
        plan_sha = self.write_plan()
        cfg = self.make_cfg("f" * 64)
        self.write_approval(plan_sha)
        with self.patched():
            approval = json.loads(self.approval_path.read_text(encoding="utf-8"))
            plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
            self.assertEqual(die_reason(pub.check_binding, cfg, approval, plan,
                                        self.plan_path.read_bytes()), 1)

    def test_approval_status_must_be_a_human_approval(self):
        plan_sha = self.write_plan()
        cfg = self.make_cfg(plan_sha, required_approval_status="APPROVED")
        self.write_approval(plan_sha)
        with self.patched():
            self.assertEqual(die_reason(pub.load_config), 1)

    def test_approval_status_must_match_the_configured_value(self):
        plan_sha = self.write_plan()
        cfg = self.make_cfg(plan_sha)
        self.write_approval(plan_sha)
        approval = json.loads(self.approval_path.read_text(encoding="utf-8"))
        approval["approval_status"] = "HUMAN_APPROVED_SOMETHING_ELSE"
        self.approval_path.write_text(json.dumps(approval), encoding="utf-8")
        with self.patched():
            self.assertEqual(die_reason(pub.check_binding, cfg, approval,
                                        json.loads(self.plan_path.read_text(encoding="utf-8")),
                                        self.plan_path.read_bytes()), 1)

    def test_approval_ref_must_match(self):
        plan_sha = self.write_plan()
        cfg = self.make_cfg(plan_sha)
        self.write_approval(plan_sha)
        approval = json.loads(self.approval_path.read_text(encoding="utf-8"))
        approval["approval_ref"] = "approval-someotherref"
        with self.patched():
            self.assertEqual(die_reason(pub.check_binding, cfg, approval,
                                        json.loads(self.plan_path.read_text(encoding="utf-8")),
                                        self.plan_path.read_bytes()), 1)

    def test_wrong_host_and_agent_never_reach_publication(self):
        for field, bad in (("host_id", "i-otherhost"), ("agent_id", "other-agent")):
            plan_sha = self.write_plan()
            cfg = self.make_cfg(plan_sha)
            self.write_approval(plan_sha, **{field: bad})
            transport = FakeTransport()
            with self.patched():
                self.assertEqual(die_reason(pub.rotate, cfg, transport, self.clock), 1, field)
            self.assertEqual(transport.writes, 0, field)
            self.assertFalse(self.state_path.exists(), field)

    # ---- generation progression -------------------------------------------
    def test_first_generation_follows_the_deployment_floor(self):
        cfg = self.prepared()
        transport = FakeTransport()
        with self.patched():
            self.assertEqual(pub.rotate(cfg, transport, self.clock), 0)
        self.assertEqual(self.state()["last_generation"], 2)
        self.assertEqual(list(transport.store),
                         ["registrations/go-runtime-test-01-agent-g000002.json"])

    def test_generation_increments_one_at_a_time(self):
        cfg = self.prepared()
        transport = FakeTransport()
        with self.patched():
            pub.rotate(cfg, transport, self.clock)
            pub.rotate(cfg, transport, self.clock)
            pub.rotate(cfg, transport, self.clock)
        self.assertEqual(self.state()["last_generation"], 4)
        self.assertEqual(sorted(transport.store), [
            "registrations/go-runtime-test-01-agent-g000002.json",
            "registrations/go-runtime-test-01-agent-g000003.json",
            "registrations/go-runtime-test-01-agent-g000004.json"])
        bodies = [json.loads(v.decode("utf-8"))["body"] for v in transport.store.values()]
        self.assertEqual(sorted(b["generation"] for b in bodies), [2, 3, 4])
        for body in bodies:
            # The rotator now issues the closed action vector: the original host
            # probe plus the bounded C1 bridge probe.
            self.assertEqual(body["actions"], [channel.HOST_ACTION, channel.RUNTIME_ACTION])
            self.assertEqual(set(body["actions"]), set(channel.ACTIONS))
            self.assertEqual(set(body), set(channel.REGISTRATION_FIELDS.split()))
            self.assertEqual(body["expires_at"] - body["issued_at"], 86400)

    def test_generation_never_repeats_after_restart(self):
        cfg = self.prepared()
        with self.patched():
            pub.rotate(cfg, FakeTransport(), self.clock)
        # a fresh process re-reads the durable state
        with self.patched():
            pub.rotate(cfg, FakeTransport(), self.clock)
        self.assertEqual(self.state()["last_generation"], 3)

    def test_state_below_the_configured_floor_is_a_rollback(self):
        self.prepared()
        self.state_path.write_text(json.dumps({
            "version": 1, "environment": "GO-RUNTIME-TEST-01",
            "host_id": "i-j6cg7euc4ggol8gkijog", "agent_id": "go-runtime-test-01-agent",
            "last_generation": 1, "pending": None}), encoding="utf-8")
        cfg = json.loads(self.publisher_path.read_text(encoding="utf-8"))
        cfg["deployment_first_generation"] = 5
        with self.patched():
            self.assertEqual(die_reason(pub.load_state, cfg), 1)

    def test_state_identity_rebind_is_rejected(self):
        self.prepared()
        self.state_path.write_text(json.dumps({
            "version": 1, "environment": "GO-RUNTIME-TEST-01",
            "host_id": "i-someotherhost", "agent_id": "go-runtime-test-01-agent",
            "last_generation": 4, "pending": None}), encoding="utf-8")
        cfg = json.loads(self.publisher_path.read_text(encoding="utf-8"))
        with self.patched():
            self.assertEqual(die_reason(pub.load_state, cfg), 1)

    # ---- durable state -----------------------------------------------------
    def test_state_file_is_root_only(self):
        cfg = self.prepared()
        with self.patched():
            pub.rotate(cfg, FakeTransport(), self.clock)
        self.assertEqual(stat.S_IMODE(os.stat(self.state_path).st_mode), 0o600)

    def test_state_is_persisted_before_any_network_write(self):
        cfg = self.prepared()
        state_path = self.state_path

        class Watching(FakeTransport):
            def create(self, key, raw):
                on_disk = json.loads(state_path.read_text(encoding="utf-8"))
                assert on_disk["pending"] is not None, "pending must be durable first"
                assert on_disk["pending"]["state"] == "ATTEMPTED", on_disk["pending"]["state"]
                assert base64.b64decode(on_disk["pending"]["raw"]) == raw
                FakeTransport.create(self, key, raw)

        with self.patched():
            self.assertEqual(pub.rotate(cfg, Watching(), self.clock), 0)

    # ---- unfinished publication -------------------------------------------
    def _counting_signer(self):
        """Wrap load_signer so a re-sign during recovery would be visible."""
        calls = {"n": 0}
        real = pub.load_signer

        def counting(cfg, private=False):
            calls["n"] += 1
            return real(cfg, private=private)

        return calls, counting

    def test_a_push_that_never_landed_retries_the_identical_bytes(self):
        cfg = self.prepared()
        transport = FakeTransport(fail_before=1)  # first push dies before the object exists
        with self.patched():
            self.assertRaises(OSError, pub.rotate, cfg, transport, self.clock)
            state = self.state()
            self.assertEqual(state["pending"]["generation"], 2)
            self.assertEqual(state["last_generation"], 1)
            pending_key = state["pending"]["key"]
            pending_raw = base64.b64decode(state["pending"]["raw"])

            calls, counting = self._counting_signer()
            with mock.patch.object(pub, "load_signer", counting):
                self.assertEqual(pub.rotate(cfg, transport, self.clock), 0)
            self.assertEqual(calls["n"], 0)  # recovery never re-signs

        self.assertEqual(transport.writes, 2)
        self.assertEqual(transport.created,
                         [(pending_key, pending_raw), (pending_key, pending_raw)])
        self.assertEqual(transport.store[pending_key], pending_raw)
        state = self.state()
        self.assertIsNone(state["pending"])
        self.assertEqual(state["last_generation"], 2)

    def test_b_lost_acknowledgement_is_resolved_by_readback_alone(self):
        cfg = self.prepared()
        transport = FakeTransport(fail_after=True)  # stored remotely, ack lost
        with self.patched():
            self.assertRaises(OSError, pub.rotate, cfg, transport, self.clock)
            state = self.state()
            self.assertEqual(state["pending"]["state"], "ATTEMPTED")
            self.assertEqual(state["last_generation"], 1)  # never advanced on ambiguity
            pending_key = state["pending"]["key"]
            published = transport.store[pending_key]

            calls, counting = self._counting_signer()
            with mock.patch.object(pub, "load_signer", counting):
                self.assertEqual(pub.rotate(cfg, transport, self.clock), 0)
            self.assertEqual(calls["n"], 0)

        self.assertEqual(transport.writes, 1)  # no second write was needed
        self.assertEqual(transport.store[pending_key], published)
        self.assertEqual(self.state()["last_generation"], 2)

    def test_c_conflicting_remote_object_is_refused_not_overwritten(self):
        cfg = self.prepared()
        transport = FakeTransport(fail_after=True)
        conflict = b'{"body":{},"signature":"AAAA"}'
        with self.patched():
            self.assertRaises(OSError, pub.rotate, cfg, transport, self.clock)
            key = self.state()["pending"]["key"]
            transport.store[key] = conflict
            before = transport.writes
            self.assertEqual(die_reason(pub.rotate, cfg, transport, self.clock), 1)
            self.assertEqual(transport.writes, before)  # not even an overwrite attempt
            self.assertEqual(transport.store[key], conflict)
            self.assertEqual(self.state()["last_generation"], 1)
            self.assertEqual(self.state()["pending"]["generation"], 2)

    def test_d_repeated_absence_leaves_pending_and_generation_unchanged(self):
        cfg = self.prepared()
        transport = FakeTransport(drop=True)
        with self.patched():
            for _ in range(3):
                self.assertEqual(die_reason(pub.rotate, cfg, transport, self.clock), 1)
                self.assertEqual(self.state()["pending"]["generation"], 2)
                self.assertEqual(self.state()["last_generation"], 1)
        self.assertEqual(transport.store, {})
        self.assertEqual(len({key for key, _ in transport.created}), 1)   # one key only
        self.assertEqual(len({raw for _, raw in transport.created}), 1)   # one byte string

    # ---- namespace ---------------------------------------------------------
    def test_published_key_uses_the_registrations_namespace(self):
        cfg = self.prepared()
        transport = FakeTransport()
        with self.patched():
            pub.rotate(cfg, transport, self.clock)
        key = list(transport.store)[0]
        self.assertTrue(key.startswith("registrations/"))
        self.assertNotIn("tasks/", key)
        self.assertFalse(key.startswith("evidence/"))


if __name__ == "__main__":
    unittest.main()
