"""Isolated tests for the CONTROL_STATE_V1 projection (scope: state + status only).

Standard library plus cryptography. No network, no Git, no runtime path, no live
Control Plane state.

Identity discipline under test: the Command Center task signer and the Hong Kong
evidence signer are **separate** Ed25519 identities. Every fixture that needs both
generates two independent keys; no fixture uses one key for both roles.
"""
import argparse
import base64
import datetime as dt
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader("state_projection", str(ROOT / "state_projection.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
sp = importlib.util.module_from_spec(spec)
loader.exec_module(sp)

AT = sp.parse_time("2026-09-14T12:00:00Z")


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def key_pair(name):
    """An Ed25519 key plus its own public key path, in a directory that outlives it."""
    from cryptography.hazmat.primitives import serialization
    directory = pathlib.Path(tempfile.mkdtemp(prefix="ccs-key-"))
    key = __import__("cryptography.hazmat.primitives.asymmetric.ed25519",
                     fromlist=["Ed25519PrivateKey"]).Ed25519PrivateKey.generate()
    private = directory / ("%s.pem" % name)
    public = directory / ("%s.pub" % name)
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    public.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return key, str(public)


def sign(obj, key, encoding):
    unsigned = {k: v for k, v in obj.items() if k != "signature"}
    raw = key.sign(sp.canonical(unsigned))
    out = dict(unsigned)
    out["signature"] = raw.hex() if encoding == "hex" else base64.b64encode(raw).decode("ascii")
    return out


def task(action="HK_STAGING_VERIFY", **over):
    issued = AT - dt.timedelta(minutes=30)
    value = {
        "schema_version": "1", "task_id": "task-%s" % action.lower().replace("_", "-"),
        "nonce": "nonce-0001", "issued_at": sp.iso(issued),
        "expires_at": sp.iso(issued + dt.timedelta(minutes=15)),
        "authority": "GO-COMMAND-CENTER", "environment": "HK-STAGING-01", "action_id": action,
        "parameters": {"release_id": "release-1",
                       "candidate_image_id": "sha256:" + "a" * 64,
                       "expected_current_image_id": "sha256:" + "a" * 64},
        # Placeholder envelope. Without a verifier key the projection must degrade
        # to OBSERVED, so a placeholder never buys a PROVEN claim.
        "signature": "0" * 128,
    }
    value.update(over)
    return value


def evidence(tk, **over):
    started = sp.parse_time(tk["issued_at"]) + dt.timedelta(seconds=30)
    value = {
        "schema_version": "1", "task_id": tk["task_id"], "nonce": tk["nonce"],
        "action_id": tk["action_id"], "environment": tk["environment"], "status": "SUCCESS",
        "started_at": sp.iso(started), "completed_at": sp.iso(started + dt.timedelta(seconds=20)),
        "agent_version": "0.5.7-rebuilt", "executor_version": "0.4.3-rollback-runtime",
        "executor_result": "VERIFY_OK", "gate_results": {"api_health": "PASS"},
        "signature": base64.b64encode(b"0" * 64).decode("ascii"),
    }
    value.update(over)
    return value


def health_pair(offset_minutes, completed_at=None):
    issued = AT - dt.timedelta(minutes=offset_minutes + 1)
    tk = task(action="CONTROL_PLANE_HEALTH", task_id="health-1", nonce="nonce-health",
              issued_at=sp.iso(issued), expires_at=sp.iso(issued + dt.timedelta(minutes=15)),
              parameters={})
    stamp = completed_at or sp.iso(AT - dt.timedelta(minutes=offset_minutes))
    ev = evidence(tk, executor_version="0.5.7-rebuilt",
                  executor_result={"hostname": "iZj6ccs8t04f1p4d8pe69zZ",
                                   "agent_version": "0.5.7-rebuilt",
                                   "tasks_repo_connectivity": True,
                                   "evidence_repo_connectivity": True},
                  started_at=stamp, completed_at=stamp)
    return tk, ev


def layout(tasks=(), evidences=(), requests=()):
    root = pathlib.Path(tempfile.mkdtemp(prefix="ccs-bus-"))
    (root / "tasks").mkdir()
    (root / "evidence").mkdir()
    for name, value in tasks:
        (root / "tasks" / name).write_text(json.dumps(value), encoding="utf-8")
    for name, value in evidences:
        (root / "evidence" / name).write_text(json.dumps(value), encoding="utf-8")
    requests_dir = None
    if requests:
        requests_dir = root / "requests"
        requests_dir.mkdir()
        for name, value in requests:
            (requests_dir / name).write_text(json.dumps(value), encoding="utf-8")
    return root, requests_dir


def fake_args(**over):
    base = {"tasks_ref": "main", "tasks_head": "5b7caecd8e47751b13e4661d14b27880f19d1d71",
            "evidence_ref": "permission-test",
            "evidence_head": "350dc628075ebd4cea9a3a2d8040caf23f957f57",
            "go_ref": "main", "go_head": "8ffcde66d36c1bbf849218529ef015f6e81725af"}
    base.update(over)
    return argparse.Namespace(**base)


def build(root, req_dir=None, task_pub=None, evidence_pub=None, go_repo=None, at=None, **flags):
    """Build the state without going through the CLI."""
    loaded = sp.Loaded()
    sp.load_tasks(str(root), loaded)
    sp.load_evidence(str(root), loaded)
    sp.load_requests(str(req_dir) if req_dir else None, loaded)
    task_verifier = sp.Verifier(task_pub, sp.TASK_VERIFIER_IDENTITY, "hex")
    evidence_verifier = sp.Verifier(evidence_pub, sp.EVIDENCE_VERIFIER_IDENTITY, "base64")
    separated = sp.separated(task_verifier, evidence_verifier, loaded)
    if not separated:
        task_verifier = task_verifier.disabled_copy()
        evidence_verifier = evidence_verifier.disabled_copy()
    options = {
        "stale_seconds": flags.pop("stale_seconds", 86400),
        "liveness_window": flags.pop("liveness_window", 1800),
        "verification_window": flags.pop("verification_window", 86400),
        "stuck_after": flags.pop("stuck_after", 900),
        "recent_window": flags.pop("recent_window", 604800),
        "go_repo": go_repo,
        "repository_main_sha": flags.pop("repository_main_sha", None),
        "identities_separated": separated,
        "args": fake_args(),
    }
    state = sp.build_state(loaded, task_verifier, evidence_verifier, at or AT, options)
    status = sp.build_status(state, sp.verdict_for(state["control_state"]))
    return loaded, state, status


def project(root, req_dir=None, **flags):
    """Build and return only the state document."""
    return build(root, req_dir, **flags)[1]


# --------------------------------------------------------------------------- #
class PrimitivesTests(unittest.TestCase):
    def test_canonical_is_key_order_independent(self):
        self.assertEqual(sp.canonical({"b": 1, "a": 2}), sp.canonical({"a": 2, "b": 1}))

    def test_digest_is_stable(self):
        self.assertEqual(sp.digest({"a": [1, 2]}), sp.digest({"a": [1, 2]}))

    def test_unknown_discards_value(self):
        self.assertEqual(sp.unknown("r")["value"], None)
        self.assertEqual(sp.unknown("r")["state"], sp.STATE_UNKNOWN)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            sp.parse_time("2026-09-14T12:00:00")

    def test_scope_is_declared(self):
        self.assertEqual(sp.CONTRACT_SCOPE, "CONTROL_STATE_AND_STATUS_ONLY")

    def test_instance_normalisation_collapses_three_spellings(self):
        for value in ("i-j6ccs8t04f1p4d8pe69z", "iZj6ccs8t04f1p4d8pe69zZ", "j6ccs8t04f1p4d8pe69z"):
            self.assertEqual(sp.normalize_instance(value), "i-j6ccs8t04f1p4d8pe69z")

    def test_instance_normalisation_rejects_other_strings(self):
        self.assertIsNone(sp.normalize_instance("command-center"))
        self.assertIsNone(sp.normalize_instance(None))


# --------------------------------------------------------------------------- #
class VerifierIdentityTests(unittest.TestCase):
    """The task signer and the evidence signer must be different identities."""

    def setUp(self):
        self.task_key, self.task_pub = key_pair("cc-task")
        self.evidence_key, self.evidence_pub = key_pair("hk-evidence")

    def test_two_keys_have_different_fingerprints(self):
        a = sp.Verifier(self.task_pub, sp.TASK_VERIFIER_IDENTITY, "hex")
        b = sp.Verifier(self.evidence_pub, sp.EVIDENCE_VERIFIER_IDENTITY, "base64")
        self.assertTrue(a.available and b.available)
        self.assertNotEqual(a.fingerprint, b.fingerprint)

    def test_valid_task_key_and_valid_evidence_key_pass(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.evidence_key, "base64")
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                            task_pub=self.task_pub, evidence_pub=self.evidence_pub)
        entry = state["tasks"][0]
        self.assertTrue(entry["task_signature_verified"])
        self.assertTrue(entry["evidence"]["signature_verified"])
        self.assertEqual(entry["lifecycle"], "COMPLETE")
        self.assertTrue(state["verification"]["identities_separated"])

    def test_task_signed_with_the_evidence_key_fails(self):
        tk = sign(task(), self.evidence_key, "hex")
        _, state, _ = build(*layout(tasks=[("t.json", tk)]),
                            task_pub=self.task_pub, evidence_pub=self.evidence_pub)
        entry = state["tasks"][0]
        self.assertFalse(entry["task_signature_verified"])
        self.assertEqual(entry["lifecycle"], "POLICY_HOLD")
        self.assertEqual(entry["assertion"]["value"], "TASK_SIGNATURE_INVALID")

    def test_evidence_signed_with_the_task_key_fails(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.task_key, "base64")
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                            task_pub=self.task_pub, evidence_pub=self.evidence_pub)
        entry = state["tasks"][0]
        self.assertFalse(entry["evidence"]["signature_verified"])
        self.assertEqual(entry["lifecycle"], "EVIDENCE_INVALID")
        self.assertNotEqual(entry["assertion"]["state"], sp.STATE_PROVEN)

    def test_tampered_evidence_is_invalid(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.evidence_key, "base64")
        ev["executor_result"] = "TAMPERED"
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                            task_pub=self.task_pub, evidence_pub=self.evidence_pub)
        self.assertFalse(state["tasks"][0]["evidence"]["signature_verified"])
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_INVALID")

    def test_missing_keys_never_yield_proven(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.evidence_key, "base64")
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]))
        entry = state["tasks"][0]
        self.assertIsNone(entry["task_signature_verified"])
        self.assertIsNone(entry["evidence"]["signature_verified"])
        self.assertNotEqual(entry["assertion"]["state"], sp.STATE_PROVEN)
        self.assertEqual(entry["lifecycle"], "EVIDENCE_PUBLISHED")
        self.assertEqual(state["verification"]["task"]["signature_verification"], "NOT_PERFORMED")
        self.assertEqual(state["verification"]["evidence"]["signature_verification"], "NOT_PERFORMED")

    def test_only_the_evidence_key_supplied_leaves_tasks_unverified(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.evidence_key, "base64")
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                            evidence_pub=self.evidence_pub)
        entry = state["tasks"][0]
        self.assertIsNone(entry["task_signature_verified"])
        self.assertTrue(entry["evidence"]["signature_verified"])
        # The Evidence verifies, but the Task it belongs to was never established.
        self.assertNotEqual(entry["assertion"]["state"], sp.STATE_PROVEN)

    def test_only_the_task_key_supplied_never_yields_proven_evidence(self):
        tk = sign(task(), self.task_key, "hex")
        ev = sign(evidence(task()), self.evidence_key, "base64")
        _, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                            task_pub=self.task_pub)
        entry = state["tasks"][0]
        self.assertTrue(entry["task_signature_verified"])
        self.assertIsNone(entry["evidence"]["signature_verified"])
        self.assertNotEqual(entry["assertion"]["state"], sp.STATE_PROVEN)

    def test_broken_key_file_reports_not_performed(self):
        bad = pathlib.Path(tempfile.mkdtemp(prefix="ccs-bad-")) / "bad.pub"
        bad.write_bytes(b"not a key")
        verifier = sp.Verifier(str(bad), sp.TASK_VERIFIER_IDENTITY, "hex")
        self.assertFalse(verifier.available)
        self.assertIsNone(verifier.verify(task(), "hex"))

    def test_a_shared_key_for_both_roles_is_a_collision(self):
        shared_key, shared_pub = key_pair("shared")
        tk = sign(task(), shared_key, "hex")
        ev = sign(evidence(task()), shared_key, "base64")
        loaded, state, _ = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                                 task_pub=shared_pub, evidence_pub=shared_pub)
        self.assertIn("VERIFIER_IDENTITY_COLLISION", [a["kind"] for a in loaded.anomalies])
        self.assertFalse(state["verification"]["identities_separated"])
        self.assertEqual(state["verification"]["task"]["signature_verification"], "NOT_PERFORMED")
        self.assertNotEqual(state["tasks"][0]["assertion"]["state"], sp.STATE_PROVEN)

    def test_verifier_describe_exposes_identity_and_encoding(self):
        described = sp.Verifier(self.task_pub, sp.TASK_VERIFIER_IDENTITY, "hex").describe()
        self.assertEqual(described["encoding"], "hex")
        self.assertEqual(described["identity"], sp.TASK_VERIFIER_IDENTITY)
        self.assertEqual(described["signature_verification"], "PERFORMED")


# --------------------------------------------------------------------------- #
class ValidationTests(unittest.TestCase):
    def test_valid_task_passes(self):
        self.assertEqual(sp.validate_task(task())["_parameter_contract"], "CURRENT")

    def test_unknown_field_rejected(self):
        with self.assertRaises(sp.Malformed):
            sp.validate_task(task(extra="x"))

    def test_wrong_authority_and_environment_rejected(self):
        for patch in ({"authority": "SOMEONE-ELSE"}, {"environment": "PRODUCTION"}):
            with self.assertRaises(sp.Malformed):
                sp.validate_task(task(**patch))

    def test_unknown_action_rejected(self):
        with self.assertRaises(sp.Malformed):
            sp.validate_task(task(action="HK_STAGING_ERASE"))

    def test_parameter_drift_is_preserved_not_dropped(self):
        legacy = task()
        legacy["parameters"] = {"release_id": "release-1"}
        self.assertEqual(sp.validate_task(legacy)["_parameter_contract"], "LEGACY_OR_UNKNOWN")

    def test_test_pr_source_must_be_the_fixed_shape(self):
        value = task(action="HK_STAGING_TEST_PR")
        value["parameters"] = {"builder_profile": "go-application-python-v1",
                               "source": {"repository": "git@github.com:yuguangzhi3836-glitch/GO.git",
                                          "pr_number": "47", "commit_sha": "c" * 40}}
        self.assertEqual(sp.validate_task(value)["_parameter_contract"], "CURRENT")
        value["parameters"]["source"]["commit_sha"] = "not-a-sha"
        with self.assertRaises(sp.Malformed):
            sp.validate_task(value)

    def test_evidence_generations_normalise(self):
        current = sp.normalize_evidence(evidence(task()))
        self.assertEqual(current["_generation"], "v2")
        self.assertEqual(current["_completed_at"], evidence(task())["completed_at"])
        legacy = evidence(task())
        legacy["finished_at"] = legacy.pop("completed_at")
        legacy.pop("executor_result")
        legacy["result"] = {"hostname": "iZj6ccs8t04f1p4d8pe69zZ"}
        normalised = sp.normalize_evidence(legacy)
        self.assertEqual(normalised["_generation"], "v1")
        self.assertEqual(normalised["_completed_at"], legacy["finished_at"])

    def test_evidence_without_any_terminal_timestamp_rejected(self):
        value = evidence(task())
        value.pop("completed_at")
        with self.assertRaises(sp.Malformed):
            sp.normalize_evidence(value)

    def test_request_extras_are_action_scoped(self):
        base = {"schema_version": "1", "request_id": "boss-hk-verify-1",
                "action_id": "HK_STAGING_VERIFY", "environment": "HK-STAGING-01",
                "requested_at": sp.iso(AT)}
        self.assertEqual(sp.validate_request(base)["action_id"], "HK_STAGING_VERIFY")
        with self.assertRaises(sp.Malformed):
            sp.validate_request(dict(base, pr_number="47"))
        with self.assertRaises(sp.Malformed):
            sp.validate_request(dict(base, plan_id="plan-1"))

    def test_deploy_request_takes_only_plan_id(self):
        value = {"schema_version": "1", "request_id": "boss-deploy-1",
                 "action_id": "HK_STAGING_DEPLOY", "environment": "HK-STAGING-01",
                 "requested_at": sp.iso(AT), "plan_id": "reviewed-plan-1"}
        self.assertEqual(sp.validate_request(value)["plan_id"], "reviewed-plan-1")
        value["image"] = "sha256:" + "a" * 64
        with self.assertRaises(sp.Malformed):
            sp.validate_request(value)


# --------------------------------------------------------------------------- #
class LifecycleTests(unittest.TestCase):
    def test_published_task_without_evidence_is_observed_not_failed(self):
        tk = task(expires_at=sp.iso(AT + dt.timedelta(minutes=5)))
        state = project(*layout(tasks=[("t.json", tk)]))
        entry = state["tasks"][0]
        self.assertEqual(entry["lifecycle"], "TASK_PUBLISHED")
        self.assertEqual(entry["assertion"]["state"], sp.STATE_OBSERVED)
        self.assertEqual(entry["hk_agent_picked_up"]["state"], sp.STATE_UNKNOWN)

    def test_expired_task_without_evidence_is_distinct_from_success(self):
        tk = task(expires_at=sp.iso(AT - dt.timedelta(minutes=1)))
        state = project(*layout(tasks=[("t.json", tk)]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "TASK_EXPIRED")
        self.assertEqual(state["counts"]["by_lifecycle"], {"TASK_EXPIRED": 1})

    def test_unverified_evidence_reaches_published_not_complete(self):
        tk = task()
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_PUBLISHED")
        self.assertEqual(state["tasks"][0]["assertion"]["state"], sp.STATE_OBSERVED)

    def test_verified_evidence_reaches_complete(self):
        task_key, task_pub = key_pair("cc-task")
        evidence_key, evidence_pub = key_pair("hk-evidence")
        tk = sign(task(), task_key, "hex")
        ev = sign(evidence(task()), evidence_key, "base64")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        task_pub=task_pub, evidence_pub=evidence_pub)
        entry = state["tasks"][0]
        self.assertEqual(entry["lifecycle"], "COMPLETE")
        self.assertEqual(entry["assertion"]["state"], sp.STATE_PROVEN)

    def test_non_success_status_is_execution_failed(self):
        tk = task()
        state = project(*layout(tasks=[("t.json", tk)],
                                evidences=[("e.json", evidence(tk, status="REJECTED"))]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EXECUTION_FAILED")

    def test_evidence_after_expiry_is_timeout(self):
        tk = task()
        late = evidence(tk)
        late["completed_at"] = sp.iso(sp.parse_time(tk["expires_at"]) + dt.timedelta(minutes=1))
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", late)]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_TIMEOUT")

    def test_executor_result_mismatch_is_flagged_without_a_key(self):
        tk = task()
        state = project(*layout(tasks=[("t.json", tk)],
                                evidences=[("e.json", evidence(tk, executor_result="DEPLOY_OK"))]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_PUBLISHED")
        self.assertEqual(state["tasks"][0]["assertion"]["value"], "EXECUTOR_RESULT_MISMATCH")

    def test_executor_result_mismatch_is_failed_with_the_evidence_key(self):
        task_key, task_pub = key_pair("cc-task")
        evidence_key, evidence_pub = key_pair("hk-evidence")
        tk = sign(task(), task_key, "hex")
        ev = sign(evidence(task(), executor_result="DEPLOY_OK"), evidence_key, "base64")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        task_pub=task_pub, evidence_pub=evidence_pub)
        self.assertEqual(state["tasks"][0]["lifecycle"], "EXECUTION_FAILED")

    def test_nonce_reuse_is_replay_rejected(self):
        first, second = task(), task(task_id="task-two", nonce="nonce-0001")
        loaded, state, _ = build(*layout(tasks=[("a.json", first), ("b.json", second)]))
        self.assertIn("REPLAY_REJECTED", [a["kind"] for a in loaded.anomalies])
        self.assertIn("REPLAY_REJECTED", [a["kind"] for a in state["anomalies"]])

    def test_duplicate_task_id_is_reported(self):
        loaded, _, _ = build(*layout(tasks=[("a.json", task()), ("b.json", task())]))
        self.assertIn("TASK_ID_REUSED", [a["kind"] for a in loaded.anomalies])

    def test_legacy_parameter_contract_is_held_not_dropped(self):
        legacy = task()
        legacy["parameters"] = {"release_id": "release-1"}
        loaded, state, _ = build(*layout(tasks=[("legacy.json", legacy)]))
        self.assertEqual(len(state["tasks"]), 1)
        self.assertEqual(state["tasks"][0]["lifecycle"], "POLICY_HOLD")
        self.assertEqual(state["tasks"][0]["assertion"]["state"], sp.STATE_UNKNOWN)
        self.assertIn("TASK_PARAMETER_CONTRACT_DRIFT", [a["kind"] for a in loaded.anomalies])

    def test_malformed_task_is_reported_not_silently_ignored(self):
        loaded, _, _ = build(*layout(tasks=[("bad.json", {"schema_version": "1"})]))
        self.assertEqual(loaded.tasks, [])
        self.assertIn("TASK_UNREADABLE", [a["kind"] for a in loaded.anomalies])

    def test_lifecycle_vocabulary_is_closed(self):
        for needed in ("REQUEST_CREATED", "REQUEST_VALIDATED", "REQUEST_REJECTED",
                       "TASK_SIGNED", "TASK_PUBLISHED", "HK_AGENT_PICKED_UP",
                       "EXECUTION_STARTED", "EVIDENCE_PUBLISHED", "EVIDENCE_VERIFIED", "COMPLETE",
                       "TASK_EXPIRED", "TASK_NOT_PICKED_UP", "EXECUTION_FAILED",
                       "EVIDENCE_INVALID", "EVIDENCE_TIMEOUT", "REPLAY_REJECTED", "POLICY_HOLD"):
            self.assertIn(needed, sp.LIFECYCLE_TASK | sp.LIFECYCLE_REQUEST)


# --------------------------------------------------------------------------- #
class StuckTaskClassificationTests(unittest.TestCase):
    def test_fresh_published_task_is_active_but_not_stuck(self):
        tk = task(issued_at=sp.iso(AT - dt.timedelta(minutes=2)),
                  expires_at=sp.iso(AT + dt.timedelta(minutes=13)))
        _, state, status = build(*layout(tasks=[("t.json", tk)]))
        self.assertEqual(len(state["control_state"]["active_tasks"]), 1)
        self.assertEqual(state["control_state"]["active_stuck_tasks"], [])
        self.assertEqual(status["answers"]["stuck_tasks"]["answer"]["value"], "NO")

    def test_overdue_published_task_is_active_stuck(self):
        tk = task(issued_at=sp.iso(AT - dt.timedelta(minutes=20)),
                  expires_at=sp.iso(AT + dt.timedelta(minutes=5)))
        _, state, status = build(*layout(tasks=[("t.json", tk)]))
        self.assertEqual(len(state["control_state"]["active_tasks"]), 1)
        self.assertEqual(len(state["control_state"]["active_stuck_tasks"]), 1)
        self.assertEqual(status["answers"]["stuck_tasks"]["answer"]["value"], "YES")

    def test_expired_history_never_counts_as_stuck(self):
        old = task(task_id="task-old", nonce="nonce-old",
                   issued_at="2026-08-01T00:00:00Z", expires_at="2026-08-01T00:15:00Z")
        recent = task(task_id="task-recent", nonce="nonce-recent",
                      issued_at="2026-09-13T00:00:00Z", expires_at="2026-09-13T00:15:00Z")
        _, state, status = build(*layout(tasks=[("old.json", old), ("recent.json", recent)]))
        stuck = status["answers"]["stuck_tasks"]
        self.assertEqual(stuck["answer"]["value"], "NO")
        self.assertEqual(stuck["active_stuck_tasks"], [])
        self.assertEqual([t["task_id"] for t in stuck["recent_expired_tasks"]], ["task-recent"])
        self.assertEqual([t["task_id"] for t in stuck["historical_expired_tasks"]], ["task-old"])
        self.assertEqual(stuck["default_lookup"], "active_stuck_tasks")
        self.assertEqual(len(state["control_state"]["historical_expired_tasks"]), 1)

    def test_last_failure_distinguishes_expiry_from_proven_failure(self):
        expired = task(task_id="task-expired", nonce="nonce-a",
                       issued_at="2026-08-01T00:00:00Z", expires_at="2026-08-01T00:15:00Z")
        _, _, status = build(*layout(tasks=[("x.json", expired)]))
        self.assertEqual(status["answers"]["last_failure"]["value"]["kind"],
                         "EXPIRED_WITHOUT_EVIDENCE")

    def test_last_failure_with_evidence_is_a_failed_record(self):
        tk = task()
        _, _, status = build(*layout(tasks=[("t.json", tk)],
                                     evidences=[("e.json", evidence(tk, status="REJECTED"))]))
        self.assertEqual(status["answers"]["last_failure"]["value"]["kind"], "FAILED_RECORD")


# --------------------------------------------------------------------------- #
class LivenessTests(unittest.TestCase):
    def test_no_health_evidence_is_unknown(self):
        state = project(*layout(tasks=[("t.json", task())]))
        self.assertEqual(state["control_state"]["hk_agent_liveness"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(state["control_state"]["hk_agent_last_activity"]["state"], sp.STATE_UNKNOWN)

    def test_fresh_unverified_probe_is_observed_never_proven(self):
        tk, ev = health_pair(5)
        state = project(*layout(tasks=[("h.json", tk)], evidences=[("he.json", ev)]))
        liveness = state["control_state"]["hk_agent_liveness"]
        self.assertEqual(liveness["state"], sp.STATE_OBSERVED)
        self.assertEqual(liveness["value"]["hostname"], "iZj6ccs8t04f1p4d8pe69zZ")

    def test_fresh_verified_probe_is_proven(self):
        task_key, task_pub = key_pair("cc-task")
        evidence_key, evidence_pub = key_pair("hk-evidence")
        tk, ev = health_pair(5)
        state = project(*layout(tasks=[("h.json", sign(tk, task_key, "hex"))],
                                evidences=[("he.json", sign(ev, evidence_key, "base64"))]),
                        task_pub=task_pub, evidence_pub=evidence_pub)
        self.assertEqual(state["control_state"]["hk_agent_liveness"]["state"], sp.STATE_PROVEN)

    def test_stale_probe_is_unknown_and_reports_last_seen(self):
        tk, ev = health_pair(60 * 24 * 8)
        state = project(*layout(tasks=[("h.json", tk)], evidences=[("he.json", ev)]))
        liveness = state["control_state"]["hk_agent_liveness"]
        self.assertEqual(liveness["state"], sp.STATE_UNKNOWN)
        self.assertIsNone(liveness["value"])
        self.assertEqual(liveness["last_seen"]["hostname"], "iZj6ccs8t04f1p4d8pe69zZ")
        self.assertGreater(liveness["age_seconds"], 1800)

    def test_stale_probe_still_reports_last_activity(self):
        tk, ev = health_pair(60 * 24 * 8)
        state = project(*layout(tasks=[("h.json", tk)], evidences=[("he.json", ev)]))
        activity = state["control_state"]["hk_agent_last_activity"]
        self.assertEqual(activity["state"], sp.STATE_OBSERVED)
        self.assertEqual(activity["value"]["hostname"], "iZj6ccs8t04f1p4d8pe69zZ")

    def test_successful_verify_never_implies_agent_online(self):
        tk = task()
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))]))
        self.assertEqual(state["control_state"]["verify_status"]["state"], sp.STATE_OBSERVED)
        self.assertEqual(state["control_state"]["hk_agent_liveness"]["state"], sp.STATE_UNKNOWN)


# --------------------------------------------------------------------------- #
class RuntimeSeparationTests(unittest.TestCase):
    DECLARED = "sha256:" + "d" * 64
    VERIFIED = "sha256:" + "a" * 64

    def pointer(self, image):
        return {"schema": "go.current-hk-runtime.v1", "status": "ACTIVE",
                "environment": "HK-STAGING", "host": "i-j6ccs8t04f1p4d8pe69z",
                "runtime_generation": "DEPTH48",
                "canonical_runtime_identity": {"canonical_main_commit": "b" * 40},
                "product_source_identity": {"source_commit": "e" * 40},
                "image": {"image_tag": "go-hotel:depth48", "image_config_id": image},
                "release_acceptance": {"gate": "HOLD", "production": "UNTOUCHED_HOLD"}}

    def go_repo(self, image):
        root = pathlib.Path(tempfile.mkdtemp(prefix="ccs-go-"))
        base = root / "docs" / "canonical-baseline"
        base.mkdir(parents=True)
        (base / "CURRENT_HK_RUNTIME.json").write_text(json.dumps(self.pointer(image)),
                                                      encoding="utf-8")
        (base / "CURRENT_CANDIDATE.json").write_text(
            json.dumps({"source_commit": "c" * 40, "final_release": "HOLD",
                        "production": "HOLD"}), encoding="utf-8")
        return str(root)

    def verify_pair(self, image, completed_at, status="SUCCESS"):
        issued = sp.parse_time(completed_at) - dt.timedelta(minutes=5)
        tk = task(task_id="task-verify", nonce="nonce-verify",
                  issued_at=sp.iso(issued), expires_at=sp.iso(issued + dt.timedelta(minutes=10)),
                  parameters={"release_id": "release-1", "candidate_image_id": image,
                              "expected_current_image_id": image})
        ev = evidence(tk, status=status, started_at=completed_at, completed_at=completed_at)
        return tk, ev

    def test_declared_runtime_is_never_proven(self):
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-14T11:50:00Z")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        go_repo=self.go_repo(self.VERIFIED))
        declared = state["control_state"]["repository_runtime_pointer"]
        self.assertEqual(declared["state"], sp.STATE_OBSERVED)

    def test_match_when_declared_and_proven_images_agree(self):
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-14T11:50:00Z")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        go_repo=self.go_repo(self.VERIFIED))
        self.assertEqual(state["control_state"]["runtime_verification_state"], sp.RUNTIME_MATCH)
        self.assertEqual(state["control_state"]["runtime_verification"]["value"]["image_relation"],
                         "MATCH")

    def test_drift_when_declared_and_proven_images_disagree(self):
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-14T11:50:00Z")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        go_repo=self.go_repo(self.DECLARED))
        verification = state["control_state"]["runtime_verification"]
        self.assertEqual(verification["value"]["verdict"], sp.RUNTIME_DRIFT)
        self.assertEqual(verification["value"]["image_relation"], "DIFFER")
        self.assertEqual(verification["value"]["repository_declared_image"], self.DECLARED)
        self.assertEqual(verification["value"]["live_proven_image"], self.VERIFIED)

    def test_not_recently_verified_when_the_proof_is_old(self):
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-08T00:00:00Z")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        go_repo=self.go_repo(self.VERIFIED), verification_window=3600)
        self.assertEqual(state["control_state"]["runtime_verification_state"],
                         sp.RUNTIME_NOT_RECENTLY_VERIFIED)
        self.assertEqual(state["control_state"]["runtime_verification"]["value"]["verdict"],
                         sp.RUNTIME_NOT_RECENTLY_VERIFIED)

    def test_unknown_when_no_verify_evidence_exists(self):
        _, state, status = build(*layout(), go_repo=self.go_repo(self.DECLARED))
        self.assertEqual(state["control_state"]["runtime_verification"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(state["control_state"]["runtime_verification_state"], sp.RUNTIME_UNKNOWN)
        self.assertEqual(status["answers"]["repository_declared_runtime"]["state"], sp.STATE_OBSERVED)
        self.assertEqual(status["answers"]["live_verified_runtime"]["state"], sp.STATE_UNKNOWN)

    def test_repository_main_is_never_substituted_by_a_runtime_sha(self):
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-14T11:50:00Z")
        state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                        go_repo=self.go_repo(self.VERIFIED))
        control = state["control_state"]
        self.assertEqual(control["repository_main_sha"]["state"], sp.STATE_UNKNOWN)
        self.assertIsNone(control["repository_main_sha"]["value"])
        self.assertEqual(control["runtime_built_from_main_sha"]["value"], "e" * 40)
        self.assertEqual(control["runtime_canonical_main_sha"]["value"], "b" * 40)
        self.assertNotEqual(control["runtime_built_from_main_sha"]["value"],
                            control["repository_main_sha"]["value"])

    def test_repository_main_is_reported_when_supplied(self):
        state = project(*layout(), repository_main_sha="f" * 40)
        repository_main = state["control_state"]["repository_main_sha"]
        self.assertEqual(repository_main["state"], sp.STATE_OBSERVED)
        self.assertEqual(repository_main["value"], "f" * 40)

    def test_production_gate_stays_hold(self):
        tk, ev = self.verify_pair(self.VERIFIED, "2026-09-14T11:50:00Z")
        _, state, status = build(*layout(tasks=[("t.json", tk)], evidences=[("e.json", ev)]),
                                 go_repo=self.go_repo(self.VERIFIED))
        self.assertEqual(state["control_state"]["production"]["state"], sp.STATE_HOLD)
        self.assertEqual(status["answers"]["can_deploy"]["state"], sp.STATE_HOLD)
        self.assertEqual(status["answers"]["can_deploy"]["value"], "NO")


# --------------------------------------------------------------------------- #
class RequestChannelTests(unittest.TestCase):
    def request(self, action, **extra):
        value = {"schema_version": "1", "request_id": "boss-%s-1" % action.lower().replace("_", "-"),
                 "action_id": action, "environment": "HK-STAGING-01",
                 "requested_at": sp.iso(AT)}
        value.update(extra)
        return value

    def test_only_verify_and_test_pr_are_enabled(self):
        self.assertEqual(list(sp.ENABLED_REQUEST_ACTIONS),
                         ["HK_STAGING_VERIFY", "HK_STAGING_TEST_PR"])

    def test_deploy_is_a_known_capability_that_is_not_enabled(self):
        _, _, status = build(*layout())
        channel = status["answers"]["request_channel"]
        self.assertIn("HK_STAGING_DEPLOY", channel["known_capabilities"])
        self.assertNotIn("HK_STAGING_DEPLOY", channel["enabled_request_actions"])
        self.assertEqual(channel["capability_classification"]["HK_STAGING_DEPLOY"],
                         "CAPABILITY_PRESENT_BUT_DISABLED")
        self.assertFalse(channel["deploy_request_enabled"])
        self.assertEqual(channel["live_request_switch"]["state"], sp.STATE_UNKNOWN)

    def test_canary_and_rollback_are_not_requestable(self):
        _, _, status = build(*layout())
        classification = status["answers"]["request_channel"]["capability_classification"]
        self.assertEqual(classification["HK_STAGING_CANARY"], "NOT_REQUESTABLE")
        self.assertEqual(classification["HK_STAGING_ROLLBACK"], "NOT_REQUESTABLE")

    def test_verify_request_is_requestable(self):
        root, req = layout(requests=[("r.json", self.request("HK_STAGING_VERIFY"))])
        state = project(root, req)
        self.assertTrue(state["requests"][0]["requestable_by_current_channel"])

    def test_deploy_request_is_flagged_not_requestable(self):
        root, req = layout(requests=[("d.json", self.request("HK_STAGING_DEPLOY",
                                                             plan_id="reviewed-plan-1"))])
        state = project(root, req)
        entry = state["requests"][0]
        self.assertFalse(entry["requestable_by_current_channel"])
        self.assertEqual(entry["capability_classification"], "CAPABILITY_PRESENT_BUT_DISABLED")

    def test_requests_never_hold_execution_authority(self):
        root, req = layout(requests=[("r.json", self.request("HK_STAGING_VERIFY"))])
        state = project(root, req)
        self.assertFalse(state["requests"][0]["holding_execution_authority"])
        self.assertEqual(state["requests"][0]["target"], {})


# --------------------------------------------------------------------------- #
class ContractTests(unittest.TestCase):
    def build_contract(self):
        tk = task()
        tpr = task(action="HK_STAGING_TEST_PR", task_id="task-test-pr", nonce="nonce-test-pr",
                   parameters={"builder_profile": "go-application-python-v1",
                               "source": {"repository": "git@github.com:yuguangzhi3836-glitch/GO.git",
                                          "pr_number": "47", "commit_sha": "c" * 40}})
        tasks = [("t.json", tk), ("p.json", tpr)]
        evidences = [("e.json", evidence(tk)),
                     ("pe.json", evidence(tpr, executor_result="TEST_PR_OK",
                                          built_image_id="sha256:" + "e" * 64))]
        request = {"schema_version": "1", "request_id": "boss-hk-verify-1",
                   "action_id": "HK_STAGING_VERIFY", "environment": "HK-STAGING-01",
                   "requested_at": sp.iso(AT)}
        root, req = layout(tasks=tasks, evidences=evidences,
                           requests=[("r.json", {"ref": "refs/heads/boss-request-x",
                                                 "head_sha": "f" * 40, "request": request})])
        return build(root, req)

    def test_answers_cover_every_required_question(self):
        _, _, status = self.build_contract()
        for key in ("hk_agent_recent_activity", "active_tasks", "last_task", "last_evidence",
                    "pr_tested", "verify", "repository_declared_runtime", "live_verified_runtime",
                    "runtime_verification", "stuck_tasks", "last_failure", "request_channel",
                    "can_deploy", "repository_main_sha", "runtime_built_from_main_sha",
                    "rollback_targets", "release_gates", "go_is_healthy", "hk_agent_online"):
            self.assertIn(key, status["answers"])

    def test_verify_status_query(self):
        _, _, status = self.build_contract()
        verify = status["answers"]["verify"]
        self.assertEqual(verify["state"], sp.STATE_OBSERVED)
        self.assertEqual(verify["value"]["action_id"], "HK_STAGING_VERIFY")
        self.assertEqual(verify["value"]["lifecycle"], "EVIDENCE_PUBLISHED")

    def test_test_pr_is_queryable_by_pr_number(self):
        _, _, status = self.build_contract()
        index = status["answers"]["pr_tested"]["by_pr_number"]
        self.assertEqual(sorted(index), ["47"])
        entry = index["47"][0]
        self.assertEqual(entry["commit_sha"], "c" * 40)
        self.assertEqual(entry["result"], "TEST_PR_OK")
        self.assertEqual(entry["built_image_id"], "sha256:" + "e" * 64)
        self.assertEqual(entry["state"], sp.STATE_OBSERVED)

    def test_untested_pr_is_absent_from_the_index(self):
        _, _, status = self.build_contract()
        self.assertNotIn("48", status["answers"]["pr_tested"]["by_pr_number"])

    def test_active_task_query_is_zero_when_nothing_is_pending(self):
        _, _, status = self.build_contract()
        self.assertEqual(status["answers"]["active_tasks"]["value"], 0)

    def test_authority_is_always_derived_and_non_authoritative(self):
        _, state, status = self.build_contract()
        self.assertEqual(state["authority"], "DERIVED_NON_AUTHORITATIVE")
        self.assertEqual(status["authority"], "DERIVED_NON_AUTHORITATIVE")
        self.assertIn("never authorizes", state["authority_note"])

    def test_status_contract_carries_no_execution_parameter_keys(self):
        _, _, status = self.build_contract()
        forbidden = {"compose_path", "executor_path", "env_file", "command", "shell",
                     "dockerfile", "image_override", "services", "environment_path",
                     "rollback_image", "signing_key", "private_key", "force_recreate",
                     "source_deploy_task_id", "approval_id", "canary_evidence_id"}

        def walk(node, path=""):
            if isinstance(node, dict):
                for key, value in node.items():
                    self.assertNotIn(key, forbidden, "forbidden key at %s" % (path + "/" + key))
                    walk(value, path + "/" + key)
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, "%s[%d]" % (path, index))

        walk(status)

    def test_status_contract_is_bounded(self):
        _, _, status = self.build_contract()
        self.assertLess(len(json.dumps(status)), 65536)

    def test_empty_control_bus_yields_unknown_not_success(self):
        _, _, status = build(*layout())
        self.assertEqual(status["answers"]["go_is_healthy"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(status["answers"]["hk_agent_online"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(status["answers"]["can_deploy"]["state"], sp.STATE_HOLD)
        self.assertEqual(status["answers"]["runtime_verification"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(status["answers"]["stuck_tasks"]["answer"]["value"], "NO")

    def test_manifest_files_are_not_treated_as_requests(self):
        root, req = layout(requests=[("good.json",
                                      {"schema_version": "1", "request_id": "boss-hk-verify-1",
                                       "action_id": "HK_STAGING_VERIFY",
                                       "environment": "HK-STAGING-01",
                                       "requested_at": sp.iso(AT)})])
        (pathlib.Path(req) / "_MANIFEST.json").write_text('{"entries": []}', encoding="utf-8")
        loaded = sp.Loaded()
        sp.load_requests(str(req), loaded)
        self.assertEqual(len(loaded.requests), 1)
        self.assertEqual(loaded.anomalies, [])


# --------------------------------------------------------------------------- #
class PortabilityTests(unittest.TestCase):
    def test_sources_use_stable_identity_not_local_paths(self):
        state = project(*layout(tasks=[("t.json", task())]))
        sources = state["sources"]
        self.assertEqual(sources["tasks"]["repository"], sp.TASKS_REPOSITORY)
        self.assertEqual(sources["evidence"]["repository"], sp.EVIDENCE_REPOSITORY)
        self.assertEqual(sources["go"]["repository"], sp.GO_REPOSITORY)
        self.assertEqual(sources["tasks"]["head_sha"], "5b7caecd8e47751b13e4661d14b27880f19d1d71")
        self.assertEqual(sources["go"]["canonical_runtime_pointer"],
                         "docs/canonical-baseline/CURRENT_HK_RUNTIME.json")

    def test_no_machine_specific_path_appears_anywhere(self):
        tk = task()
        request = {"schema_version": "1", "request_id": "boss-hk-verify-1",
                   "action_id": "HK_STAGING_VERIFY", "environment": "HK-STAGING-01",
                   "requested_at": sp.iso(AT)}
        root, req = layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))],
                           requests=[("r.json", {"request": request})])
        _, state, status = build(root, req)
        blob = json.dumps(state, sort_keys=True) + json.dumps(status, sort_keys=True)
        self.assertEqual(sp.LOCAL_PATH_RE.findall(blob), [])

    def test_rebuild_command_contains_no_local_path(self):
        state = project(*layout())
        command = state["rebuild"]["command"]
        self.assertEqual(sp.LOCAL_PATH_RE.findall(command), [])
        self.assertIn("--task-verify-key", command)
        self.assertIn("--evidence-verify-key", command)

    def test_missing_directory_anomaly_names_the_repository_not_the_disk(self):
        empty = pathlib.Path(tempfile.mkdtemp(prefix="ccs-empty-"))
        loaded = sp.Loaded()
        sp.load_tasks(str(empty), loaded)
        self.assertIn("TASKS_DIRECTORY_MISSING", [a["kind"] for a in loaded.anomalies])
        for anomaly in loaded.anomalies:
            self.assertEqual(sp.LOCAL_PATH_RE.findall(anomaly["detail"]), [])


# --------------------------------------------------------------------------- #
class DeterminismTests(unittest.TestCase):
    def test_same_instant_same_bytes(self):
        tk = task()
        root, req = layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))])
        self.assertEqual(sp.canonical(project(root, req)), sp.canonical(project(root, req)))

    def test_output_carries_no_wall_clock(self):
        root, req = layout(tasks=[("t.json", task())])
        self.assertEqual(project(root, req)["generated_at"], sp.iso(AT))

    def test_generated_at_is_shared_by_both_contracts(self):
        _, state, status = build(*layout())
        self.assertEqual(state["generated_at"], status["generated_at"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
