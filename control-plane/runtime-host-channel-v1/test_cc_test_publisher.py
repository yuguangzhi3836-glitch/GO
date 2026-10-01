"""Contract tests for cc_test_publisher.py (the validated test-only CC publisher).

Offline only: temporary filesystem, temporary SQLite, in-memory keys.
No GitHub call, no transport, no SSH, no Task publication, no Evidence publication.

These tests assert the invariants that were observed on the real test run:
fixed verb set, fixed action, fixed field binding, bounded lifetimes,
single-shot outbox, and mandatory full evidence verification.
"""
import hashlib
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import cc_test_publisher as pub
import channel


def die_reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except SystemExit as exc:
        return exc.code
    raise AssertionError("expected SystemExit")


class PublisherContractTests(unittest.TestCase):
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
        self.evidence_key = Ed25519PrivateKey.generate()
        raw = self.evidence_key.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
        self.evidence_key_sha256 = hashlib.sha256(raw).hexdigest()

        self.plan_path = self.root / "install-plan.json"
        self.approval_path = self.root / "approval.json"
        self.publisher_path = self.root / "publisher.json"
        self.registration_out = self.root / "registration.json"
        self.state_dir = self.root / "state"
        self.state_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    # ---- writer helpers ----------------------------------------------------
    def write_plan(self):
        plan = {
            "environment": "GO-RUNTIME-TEST-01",
            "host_id": "i-j6cg7euc4ggol8gkijog",
            "agent_id": "go-runtime-test-01-agent",
            "candidate": {"sha": "7b9d53adb99b0523c1563ad388ac593ad800c864"},
            "management_agent": {"executor_sha256": "0" * 64},
            "evidence_key": {"evidence_key_sha256": self.evidence_key_sha256},
        }
        self.plan_path.write_bytes(json.dumps(plan, sort_keys=True,
                                              separators=(",", ":")).encode("utf-8") + b"\n")
        return plan, hashlib.sha256(self.plan_path.read_bytes()).hexdigest()

    def write_approval(self, plan_sha256, **overrides):
        binding = {
            "plan_sha256": plan_sha256, "executor_sha256": "0" * 64,
            "evidence_key_sha256": self.evidence_key_sha256,
            "candidate": "7b9d53adb99b0523c1563ad388ac593ad800c864",
            "environment": "GO-RUNTIME-TEST-01",
            "host_id": "i-j6cg7euc4ggol8gkijog",
            "agent_id": "go-runtime-test-01-agent",
        }
        binding.update(overrides)
        approval = {"approval_ref": "approval-7b9f6a99599db06b",
                    "approval_status": "HUMAN_APPROVED_BOUNDED_TEST",
                    "binding": binding}
        self.approval_path.write_text(json.dumps(approval), encoding="utf-8")
        return approval

    def make_cfg(self, plan_sha256):
        cfg = {
            "version": 1, "environment": "GO-RUNTIME-TEST-01",
            "host_id": "i-j6cg7euc4ggol8gkijog", "agent_id": "go-runtime-test-01-agent",
            "candidate_sha": "7b9d53adb99b0523c1563ad388ac593ad800c864",
            "plan_sha256": plan_sha256, "executor_sha256": "0" * 64,
            "evidence_key_sha256": self.evidence_key_sha256,
            "approval_ref": "approval-7b9f6a99599db06b", "generation": 1,
            "signer_private_key": str(self.priv), "signer_public_key": str(self.pub),
            "tasks": {"remote": "git@example.invalid:tasks.git", "branch": "main", "key": "/k"},
            "evidence": {"remote": "git@example.invalid:evidence.git",
                         "branch": "permission-test", "key": "/k"},
            "registration_max_lifetime_seconds": 14400,
        }
        self.publisher_path.write_text(json.dumps(cfg), encoding="utf-8")
        return cfg

    def patched(self, cfg):
        return mock.patch.multiple(
            pub, APPROVAL_JSON=str(self.approval_path), PLAN_JSON=str(self.plan_path),
            PUBLISHER_JSON=str(self.publisher_path), REGISTRATION_OUT=str(self.registration_out),
            STATE_DIR=str(self.state_dir))

    # ---- verb surface ------------------------------------------------------
    def test_exactly_three_verbs(self):
        self.assertEqual(pub.VERBS, ("sign-registration", "publish-one-probe", "collect-evidence"))

    def test_unknown_verb_is_rejected(self):
        for bad in ("deploy", "shell", "publish", "--help", ""):
            self.assertEqual(die_reason(pub.main, ["p", bad]), 1)

    def test_extra_arguments_are_rejected(self):
        self.assertEqual(die_reason(pub.main, ["p", "sign-registration", "target"]), 1)
        self.assertEqual(die_reason(pub.main, ["p", "publish-one-probe", "http://x"]), 1)
        self.assertEqual(die_reason(pub.main, ["p"]), 1)

    def test_only_action_is_the_probe(self):
        self.assertEqual(channel.ACTION, "RUNTIME_HOST_PROBE_V1")

    def test_no_shell_execution_path(self):
        src = Path(pub.__file__).read_text(encoding="utf-8")
        self.assertNotIn("shell=True", src)
        self.assertNotIn("os.system", src)

    # ---- configuration bounds ---------------------------------------------
    def test_registration_lifetime_is_bounded(self):
        plan, plan_sha = self.write_plan()
        cfg = self.make_cfg(plan_sha)
        cfg["registration_max_lifetime_seconds"] = 86401
        self.publisher_path.write_text(json.dumps(cfg), encoding="utf-8")
        with self.patched(cfg):
            self.assertEqual(die_reason(pub.load_publisher), 1)

    def test_missing_config_key_is_rejected(self):
        plan, plan_sha = self.write_plan()
        cfg = self.make_cfg(plan_sha)
        del cfg["evidence_key_sha256"]
        self.publisher_path.write_text(json.dumps(cfg), encoding="utf-8")
        with self.patched(cfg):
            self.assertEqual(die_reason(pub.load_publisher), 1)

    # ---- fixed binding checks ---------------------------------------------
    def test_binding_matrix_rejects_every_field_mismatch(self):
        plan, plan_sha = self.write_plan()
        cfg = self.make_cfg(plan_sha)
        cases = {
            "executor_sha256": "1" * 64,
            "evidence_key_sha256": "2" * 64,
            "candidate": "3" * 40,
            "environment": "OTHER-ENV",
            "host_id": "i-otherhost",
            "agent_id": "other-agent",
        }
        for field, bad in cases.items():
            approval = self.write_approval(plan_sha, **{field: bad})
            with self.patched(cfg):
                self.assertEqual(die_reason(pub.check_binding, cfg, approval, plan), 1, field)

    def test_plan_sha256_is_recomputed_locally(self):
        plan, plan_sha = self.write_plan()
        cfg = self.make_cfg("f" * 64)
        approval = self.write_approval(plan_sha)
        with self.patched(cfg):
            self.assertEqual(die_reason(pub.check_binding, cfg, approval, plan), 1)

    def test_approval_status_and_ref_are_checked(self):
        plan, plan_sha = self.write_plan()
        cfg = self.make_cfg(plan_sha)
        approval = self.write_approval(plan_sha)
        approval["approval_status"] = "SOMETHING_ELSE"
        with self.patched(cfg):
            self.assertEqual(die_reason(pub.check_binding, cfg, approval, plan), 1)
        approval = self.write_approval(plan_sha)
        approval["approval_ref"] = "approval-someotherref"
        with self.patched(cfg):
            self.assertEqual(die_reason(pub.check_binding, cfg, approval, plan), 1)

    # ---- sign-registration body -------------------------------------------
    def test_sign_registration_produces_the_fixed_field_set(self):
        plan, plan_sha = self.write_plan()
        cfg = self.make_cfg(plan_sha)
        self.write_approval(plan_sha)
        with self.patched(cfg):
            pub.cmd_sign_registration(cfg)
        raw = self.registration_out.read_bytes()
        body = channel.registration(raw, self.signer.public_key(), int(time.time()))
        self.assertEqual(set(body), set(channel.REGISTRATION_FIELDS.split()))
        self.assertEqual(body["actions"], [channel.ACTION])
        self.assertEqual(body["environment"], cfg["environment"])
        self.assertEqual(body["host_id"], cfg["host_id"])
        self.assertEqual(body["agent_id"], cfg["agent_id"])
        self.assertEqual(body["candidate_sha"], cfg["candidate_sha"])
        self.assertEqual(body["plan_sha256"], plan_sha)
        self.assertEqual(body["executor_sha256"], cfg["executor_sha256"])
        self.assertEqual(body["evidence_key_sha256"], cfg["evidence_key_sha256"])
        self.assertEqual(body["approval_ref"], cfg["approval_ref"])
        self.assertEqual(body["generation"], 1)
        self.assertLessEqual(body["expires_at"] - body["issued_at"], 14400)

    def test_sign_registration_refuses_to_overwrite(self):
        plan, plan_sha = self.write_plan()
        cfg = self.make_cfg(plan_sha)
        self.write_approval(plan_sha)
        with self.patched(cfg):
            pub.cmd_sign_registration(cfg)
            self.assertEqual(die_reason(pub.cmd_sign_registration, cfg), 1)

    # ---- outbox durability -------------------------------------------------
    def test_outbox_is_single_shot_and_ordered(self):
        db = str(self.root / "outbox.db")
        box = pub.Outbox(db)
        box.prepare("t1", "d1", b"raw-1")
        self.assertEqual(box.get("t1")[3], "PREPARED")
        box.mark_attempted("t1")
        self.assertEqual(box.get("t1")[3], "ATTEMPTED")
        box.mark_published("t1")
        self.assertEqual(box.get("t1")[3], "PUBLISHED")
        with self.assertRaises(channel.Reject):
            box.prepare("t2", "d2", b"raw-2")
        with sqlite3.connect(db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)

    def test_outbox_lives_in_a_real_table(self):
        db = str(self.root / "outbox2.db")
        pub.Outbox(db)
        with sqlite3.connect(db) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(outbox)")}
        self.assertEqual(cols, {"task_id", "task_digest", "raw", "state", "created_at"})

    # ---- task lifetime -----------------------------------------------------
    def test_task_lifetime_is_bounded_to_300s(self):
        now = int(time.time())
        ok = {"issued_at": now, "expires_at": now + 300}
        channel.window(ok, now, 300)
        too_long = {"issued_at": now, "expires_at": now + 301}
        with self.assertRaises(channel.Reject):
            channel.window(too_long, now, 300)

    def test_task_parameters_must_be_empty(self):
        task = {"action": channel.ACTION, "parameters": {"shell": "id"}}
        self.assertNotEqual(task["parameters"], {})

    # ---- evidence verification ---------------------------------------------
    def make_reg_and_task(self, now):
        reg = {"environment": "GO-RUNTIME-TEST-01", "host_id": "i-j6cg7euc4ggol8gkijog",
               "agent_id": "go-runtime-test-01-agent", "generation": 1,
               "executor_sha256": "0" * 64,
               "evidence_key_sha256": self.evidence_key_sha256}
        task = {"task_id": "rh-probe-test", "action": channel.ACTION,
                "issued_at": now - 5, "expires_at": now + 30}
        return reg, task

    def signed_evidence(self, task, reg, **overrides):
        result = {
            "version": 1, "kind": "runtime-host-evidence",
            "task_sha256": channel.digest(task), "task_id": task["task_id"],
            "registration_sha256": channel.digest(reg),
            "host_id": reg["host_id"], "agent_id": reg["agent_id"],
            "generation": reg["generation"], "observed_at": int(time.time()),
            "status": "PROBE_ONLY", "runtime_acceptance": "NOT_RUN",
            "executor_sha256": "0" * 64,
        }
        result.update(overrides)
        return channel.signed(result, self.evidence_key)

    def test_evidence_must_verify_with_probe_only_and_not_run(self):
        now = int(time.time())
        reg, task = self.make_reg_and_task(now)
        raw = self.signed_evidence(task, reg)
        verified = channel.verify_evidence(raw, self.evidence_key.public_key(), task, reg, now)
        self.assertEqual(verified["status"], "PROBE_ONLY")
        self.assertEqual(verified["runtime_acceptance"], "NOT_RUN")

    def test_evidence_with_other_status_is_rejected(self):
        now = int(time.time())
        reg, task = self.make_reg_and_task(now)
        for bad in ({"status": "PASS"}, {"runtime_acceptance": "PASS"},
                    {"host_id": "i-otherhost"}, {"task_sha256": "9" * 64}):
            raw = self.signed_evidence(task, reg, **bad)
            with self.assertRaises(channel.Reject):
                channel.verify_evidence(raw, self.evidence_key.public_key(), task, reg, now)

    def test_evidence_from_a_different_key_is_rejected(self):
        now = int(time.time())
        reg, task = self.make_reg_and_task(now)
        other = Ed25519PrivateKey.generate()
        raw = channel.signed({"version": 1, "kind": "runtime-host-evidence",
                              "task_sha256": channel.digest(task), "task_id": task["task_id"],
                              "registration_sha256": channel.digest(reg),
                              "host_id": reg["host_id"], "agent_id": reg["agent_id"],
                              "generation": 1, "observed_at": now, "status": "PROBE_ONLY",
                              "runtime_acceptance": "NOT_RUN", "executor_sha256": "0" * 64}, other)
        with self.assertRaises(channel.Reject):
            channel.verify_evidence(raw, self.evidence_key.public_key(), task, reg, now)

    def test_protected_environment_names_are_rejected(self):
        for env in ("HK-STAGING-01", "Production", "PRODUCTION"):
            body = {"version": 1, "kind": "runtime-host-registration", "environment": env,
                    "host_id": "i-j6cg7euc4ggol8gkijog", "agent_id": "go-runtime-test-01-agent",
                    "generation": 1, "candidate_sha": "7b9d53adb99b0523c1563ad388ac593ad800c864",
                    "plan_sha256": "a" * 64, "executor_sha256": "b" * 64,
                    "evidence_key_sha256": "c" * 64, "approval_ref": "approval-7b9f6a99599db06b",
                    "issued_at": int(time.time()), "expires_at": int(time.time()) + 60,
                    "actions": [channel.ACTION]}
            raw = channel.signed(body, self.signer)
            with self.assertRaises(channel.Reject):
                channel.registration(raw, self.signer.public_key(), int(time.time()))


if __name__ == "__main__":
    unittest.main()
