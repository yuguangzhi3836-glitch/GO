"""Isolated tests for the CONTROL_STATE_V1 projection.

Standard library only; no network, no Git, no runtime path, no live Control
Plane state. Signatures use ephemeral in-test Ed25519 keys so the PROVEN and
OBSERVED ranks can both be exercised honestly.
"""
import base64
import copy
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


def pem_private(key_path):
    key = __import__("cryptography.hazmat.primitives.asymmetric.ed25519",
                     fromlist=["Ed25519PrivateKey"]).Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    pathlib.Path(key_path).write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    return key


def pem_public(key, key_path):
    from cryptography.hazmat.primitives import serialization
    pathlib.Path(key_path).write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))


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
        # A placeholder envelope. Without a verifier key the projection must
        # degrade to OBSERVED, so the placeholder never buys a PROVEN claim.
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


def layout(tasks=(), evidences=(), requests=()):
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "tasks").mkdir()
    (root / "evidence").mkdir()
    for name, value in tasks:
        (root / "tasks" / name).write_text(json.dumps(value), encoding="utf-8")
    for name, value in evidences:
        (root / "evidence" / name).write_text(json.dumps(value), encoding="utf-8")
    req_dir = None
    if requests:
        req_dir = root / "requests"
        req_dir.mkdir()
        for name, value in requests:
            (req_dir / name).write_text(json.dumps(value), encoding="utf-8")
    return root, req_dir


def project(root, req_dir=None, key_path=None, **over):
    at = over.pop("at", AT)
    loaded = sp.Loaded()
    sp.load_tasks(str(root), loaded)
    sp.load_evidence(str(root), loaded)
    sp.load_requests(str(req_dir) if req_dir else None, loaded)
    verifier = sp.Verifier(key_path)
    state = sp.build_state(loaded, verifier, at, 86400, None, 1800,
                           {"tasks_repo": "fixture", "evidence_repo": "fixture"})
    return loaded, state


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

    def test_instance_normalisation_collapses_three_spellings(self):
        for value in ("i-j6ccs8t04f1p4d8pe69z", "iZj6ccs8t04f1p4d8pe69zZ", "j6ccs8t04f1p4d8pe69z"):
            self.assertEqual(sp.normalize_instance(value), "i-j6ccs8t04f1p4d8pe69z")

    def test_instance_normalisation_rejects_other_strings(self):
        self.assertIsNone(sp.normalize_instance("command-center"))
        self.assertIsNone(sp.normalize_instance(None))


class SignatureRankTests(unittest.TestCase):
    def test_missing_key_reports_not_performed(self):
        verifier = sp.Verifier(None)
        self.assertFalse(verifier.available)
        self.assertIsNone(verifier.verify(task(), "hex"))

    def test_broken_key_reports_not_performed(self):
        with tempfile.TemporaryDirectory() as raw:
            bad = pathlib.Path(raw) / "bad.pub"
            bad.write_bytes(b"not a key")
            verifier = sp.Verifier(str(bad))
            self.assertFalse(verifier.available)
            self.assertIsNone(verifier.verify(task(), "hex"))

    def test_hex_and_base64_encodings_both_verify(self):
        with tempfile.TemporaryDirectory() as raw:
            private, public = pathlib.Path(raw) / "k.pem", pathlib.Path(raw) / "k.pub"
            key = pem_private(private)
            pem_public(key, public)
            verifier = sp.Verifier(str(public))
            self.assertTrue(verifier.verify(sign(task(), key, "hex"), "hex"))
            self.assertTrue(verifier.verify(sign(evidence(task()), key, "base64"), "base64"))

    def test_tampered_payload_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            private, public = pathlib.Path(raw) / "k.pem", pathlib.Path(raw) / "k.pub"
            key = pem_private(private)
            pem_public(key, public)
            signed = sign(task(), key, "hex")
            signed["nonce"] = "nonce-0002"
            self.assertFalse(sp.Verifier(str(public)).verify(signed, "hex"))


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


class LifecycleTests(unittest.TestCase):
    def test_published_task_without_evidence_is_observed_not_failed(self):
        tk = task(expires_at=sp.iso(AT + dt.timedelta(minutes=5)))
        _, state = project(*layout(tasks=[("t.json", tk)]))
        entry = state["tasks"][0]
        self.assertEqual(entry["lifecycle"], "TASK_PUBLISHED")
        self.assertEqual(entry["assertion"]["state"], sp.STATE_OBSERVED)
        self.assertEqual(entry["hk_agent_picked_up"]["state"], sp.STATE_UNKNOWN)

    def test_expired_task_without_evidence_is_distinct_from_success(self):
        tk = task(expires_at=sp.iso(AT - dt.timedelta(minutes=1)))
        _, state = project(*layout(tasks=[("t.json", tk)]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "TASK_EXPIRED")
        self.assertEqual(state["counts"]["by_lifecycle"], {"TASK_EXPIRED": 1})

    def test_unverified_evidence_reaches_published_not_complete(self):
        tk = task()
        _, state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_PUBLISHED")
        self.assertEqual(state["tasks"][0]["assertion"]["state"], sp.STATE_OBSERVED)

    def test_verified_evidence_reaches_complete(self):
        tk = task()
        with tempfile.TemporaryDirectory() as raw:
            private, public = pathlib.Path(raw) / "k.pem", pathlib.Path(raw) / "k.pub"
            key = pem_private(private)
            pem_public(key, public)
            _, state = project(*layout(tasks=[("t.json", sign(tk, key, "hex"))],
                                       evidences=[("e.json", sign(evidence(tk), key, "base64"))]),
                               key_path=str(public))
            entry = state["tasks"][0]
            self.assertEqual(entry["lifecycle"], "COMPLETE")
            self.assertEqual(entry["assertion"]["state"], sp.STATE_PROVEN)
            self.assertTrue(entry["evidence"]["signature_verified"])
            self.assertEqual(state["verification"]["signature_verification"], "PERFORMED")

    def test_bad_evidence_signature_is_invalid_not_complete(self):
        tk = task()
        with tempfile.TemporaryDirectory() as raw:
            private, public = pathlib.Path(raw) / "k.pem", pathlib.Path(raw) / "k.pub"
            key = pem_private(private)
            pem_public(key, public)
            broken = sign(evidence(tk), key, "base64")
            broken["status"] = "SUCCESS"
            broken["executor_result"] = "TAMPERED"
            _, state = project(*layout(tasks=[("t.json", sign(tk, key, "hex"))],
                                       evidences=[("e.json", broken)]), key_path=str(public))
            self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_INVALID")
            self.assertEqual(state["tasks"][0]["assertion"]["state"], sp.STATE_FAILED)

    def test_non_success_status_is_execution_failed(self):
        tk = task()
        _, state = project(*layout(tasks=[("t.json", tk)],
                                   evidences=[("e.json", evidence(tk, status="REJECTED"))]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EXECUTION_FAILED")

    def test_evidence_after_expiry_is_timeout(self):
        tk = task()
        late = evidence(tk)
        late["completed_at"] = sp.iso(sp.parse_time(tk["expires_at"]) + dt.timedelta(minutes=1))
        _, state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", late)]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_TIMEOUT")

    def test_executor_result_mismatch_is_flagged_without_a_key(self):
        # Without the pinned key the mismatch is reported, but the projection
        # does not escalate an unverified file to a FAILED claim about the system.
        tk = task()
        _, state = project(*layout(tasks=[("t.json", tk)],
                                   evidences=[("e.json", evidence(tk, executor_result="DEPLOY_OK"))]))
        self.assertEqual(state["tasks"][0]["lifecycle"], "EVIDENCE_PUBLISHED")
        self.assertEqual(state["tasks"][0]["assertion"]["value"], "EXECUTOR_RESULT_MISMATCH")

    def test_executor_result_mismatch_is_failed_with_a_key(self):
        tk = task()
        with tempfile.TemporaryDirectory() as raw:
            private, public = pathlib.Path(raw) / "k.pem", pathlib.Path(raw) / "k.pub"
            key = pem_private(private)
            pem_public(key, public)
            _, state = project(*layout(tasks=[("t.json", sign(tk, key, "hex"))],
                                       evidences=[("e.json", sign(evidence(tk, executor_result="DEPLOY_OK"),
                                                                  key, "base64"))]),
                               key_path=str(public))
            self.assertEqual(state["tasks"][0]["lifecycle"], "EXECUTION_FAILED")

    def test_nonce_reuse_is_replay_rejected(self):
        first, second = task(), task(task_id="task-two", nonce="nonce-0001")
        loaded, state = project(*layout(tasks=[("a.json", first), ("b.json", second)]))
        self.assertIn("REPLAY_REJECTED", [a["kind"] for a in loaded.anomalies])
        self.assertIn("REPLAY_REJECTED", [a["kind"] for a in state["anomalies"]])

    def test_duplicate_task_id_is_reported(self):
        loaded, _ = project(*layout(tasks=[("a.json", task()), ("b.json", task())]))
        self.assertIn("TASK_ID_REUSED", [a["kind"] for a in loaded.anomalies])

    def test_legacy_parameter_contract_is_held_not_dropped(self):
        legacy = task()
        legacy["parameters"] = {"release_id": "release-1"}
        loaded, state = project(*layout(tasks=[("legacy.json", legacy)]))
        self.assertEqual(len(state["tasks"]), 1)
        self.assertEqual(state["tasks"][0]["lifecycle"], "POLICY_HOLD")
        self.assertEqual(state["tasks"][0]["assertion"]["state"], sp.STATE_UNKNOWN)
        self.assertIn("TASK_PARAMETER_CONTRACT_DRIFT", [a["kind"] for a in loaded.anomalies])

    def test_malformed_task_is_reported_not_silently_ignored(self):
        loaded, _ = project(*layout(tasks=[("bad.json", {"schema_version": "1"})]))
        self.assertEqual(loaded.tasks, [])
        self.assertIn("TASK_UNREADABLE", [a["kind"] for a in loaded.anomalies])

    def test_lifecycle_vocabulary_is_closed(self):
        for needed in ("REQUEST_CREATED", "REQUEST_VALIDATED", "REQUEST_REJECTED",
                       "TASK_SIGNED", "TASK_PUBLISHED", "HK_AGENT_PICKED_UP",
                       "EXECUTION_STARTED", "EVIDENCE_PUBLISHED", "EVIDENCE_VERIFIED", "COMPLETE",
                       "TASK_EXPIRED", "TASK_NOT_PICKED_UP", "EXECUTION_FAILED",
                       "EVIDENCE_INVALID", "EVIDENCE_TIMEOUT", "REPLAY_REJECTED", "POLICY_HOLD"):
            self.assertIn(needed, sp.LIFECYCLE_TASK | sp.LIFECYCLE_REQUEST)


class LivenessTests(unittest.TestCase):
    def health(self, offset_minutes, **over):
        issued = AT - dt.timedelta(minutes=offset_minutes + 1)
        tk = task(action="CONTROL_PLANE_HEALTH", task_id="health-1", nonce="nonce-health",
                  issued_at=sp.iso(issued),
                  expires_at=sp.iso(issued + dt.timedelta(minutes=15)), parameters={})
        ev = evidence(tk, executor_version="0.5.7-rebuilt",
                      executor_result={"hostname": "iZj6ccs8t04f1p4d8pe69zZ",
                                       "agent_version": "0.5.7-rebuilt",
                                       "tasks_repo_connectivity": True,
                                       "evidence_repo_connectivity": True},
                      started_at=sp.iso(AT - dt.timedelta(minutes=offset_minutes)),
                      completed_at=sp.iso(AT - dt.timedelta(minutes=offset_minutes)))
        ev.update(over)
        return tk, ev

    def test_no_health_evidence_is_unknown(self):
        _, state = project(*layout(tasks=[("t.json", task())]))
        liveness = state["control_state"]["hk_agent_liveness"]
        self.assertEqual(liveness["state"], sp.STATE_UNKNOWN)

    def test_fresh_unverified_probe_is_observed_never_proven(self):
        tk, ev = self.health(5)
        _, state = project(*layout(tasks=[("h.json", tk)], evidences=[("he.json", ev)]))
        liveness = state["control_state"]["hk_agent_liveness"]
        self.assertEqual(liveness["state"], sp.STATE_OBSERVED)
        self.assertEqual(liveness["value"]["hostname"], "iZj6ccs8t04f1p4d8pe69zZ")

    def test_fresh_verified_probe_is_proven(self):
        tk, ev = self.health(5)
        with tempfile.TemporaryDirectory() as raw:
            private, public = pathlib.Path(raw) / "k.pem", pathlib.Path(raw) / "k.pub"
            key = pem_private(private)
            pem_public(key, public)
            _, state = project(*layout(tasks=[("h.json", sign(tk, key, "hex"))],
                                       evidences=[("he.json", sign(ev, key, "base64"))]),
                               key_path=str(public))
            self.assertEqual(state["control_state"]["hk_agent_liveness"]["state"], sp.STATE_PROVEN)

    def test_stale_probe_is_unknown_and_reports_last_seen(self):
        tk, ev = self.health(60 * 24 * 8)
        _, state = project(*layout(tasks=[("h.json", tk)], evidences=[("he.json", ev)]))
        liveness = state["control_state"]["hk_agent_liveness"]
        self.assertEqual(liveness["state"], sp.STATE_UNKNOWN)
        self.assertIsNone(liveness["value"])
        self.assertEqual(liveness["last_seen"]["hostname"], "iZj6ccs8t04f1p4d8pe69zZ")
        self.assertGreater(liveness["age_seconds"], 1800)

    def test_successful_verify_never_implies_agent_online(self):
        tk = task()
        _, state = project(*layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))]))
        self.assertEqual(state["control_state"]["verify_status"]["state"], sp.STATE_OBSERVED)
        self.assertEqual(state["control_state"]["hk_agent_liveness"]["state"], sp.STATE_UNKNOWN)


class RuntimeAndGateTests(unittest.TestCase):
    def pointer(self, image):
        return {"schema": "go.current-hk-runtime.v1", "status": "ACTIVE",
                "environment": "HK-STAGING", "host": "i-j6ccs8t04f1p4d8pe69z",
                "runtime_generation": "DEPTH48",
                "canonical_runtime_identity": {"canonical_main_commit": "b" * 40},
                "image": {"image_tag": "go-hotel:depth48", "image_config_id": image},
                "release_acceptance": {"gate": "HOLD", "production": "UNTOUCHED_HOLD"}}

    def go_repo(self, image, candidate_commit="c" * 40):
        root = pathlib.Path(tempfile.mkdtemp())
        base = root / "docs" / "canonical-baseline"
        base.mkdir(parents=True)
        (base / "CURRENT_HK_RUNTIME.json").write_text(json.dumps(self.pointer(image)),
                                                      encoding="utf-8")
        (base / "CURRENT_CANDIDATE.json").write_text(
            json.dumps({"source_commit": candidate_commit, "final_release": "HOLD",
                        "production": "HOLD"}), encoding="utf-8")
        return root

    def test_matching_image_reports_no_drift(self):
        image = "sha256:" + "a" * 64
        tk = task()
        root, req = layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))])
        loaded = sp.Loaded()
        sp.load_tasks(str(root), loaded)
        sp.load_evidence(str(root), loaded)
        state = sp.build_state(loaded, sp.Verifier(None), AT, 86400, str(self.go_repo(image)), 1800, {})
        self.assertEqual(state["control_state"]["control_plane_drift"]["value"], "NONE")

    def test_changed_image_reports_drift(self):
        tk = task()
        root, req = layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))])
        loaded = sp.Loaded()
        sp.load_tasks(str(root), loaded)
        sp.load_evidence(str(root), loaded)
        state = sp.build_state(loaded, sp.Verifier(None), AT, 86400,
                               str(self.go_repo("sha256:" + "d" * 64)), 1800, {})
        drift = state["control_state"]["control_plane_drift"]
        self.assertEqual(drift["value"], "DRIFT")
        self.assertIn("no VERIFY Evidence", drift["reason"])

    def test_release_gates_hold_is_never_deployable(self):
        tk = task()
        root, req = layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))])
        loaded = sp.Loaded()
        sp.load_tasks(str(root), loaded)
        sp.load_evidence(str(root), loaded)
        state = sp.build_state(loaded, sp.Verifier(None), AT, 86400,
                               str(self.go_repo("sha256:" + "a" * 64)), 1800, {})
        status = sp.build_status(state, sp.verdict_for(state["control_state"]))
        self.assertEqual(status["answers"]["can_deploy"]["state"], sp.STATE_HOLD)
        self.assertEqual(status["answers"]["can_deploy"]["value"], "NO")
        self.assertEqual(state["control_state"]["production"]["state"], sp.STATE_HOLD)

    def test_liveness_host_binds_to_pointer_host(self):
        image = "sha256:" + "a" * 64
        issued = AT - dt.timedelta(minutes=6)
        tk = task(action="CONTROL_PLANE_HEALTH", task_id="health-1", nonce="nonce-health",
                  issued_at=sp.iso(issued), expires_at=sp.iso(issued + dt.timedelta(minutes=15)),
                  parameters={})
        ev = evidence(tk, executor_result={"hostname": "iZj6ccs8t04f1p4d8pe69zZ"},
                      started_at=sp.iso(AT - dt.timedelta(minutes=5)),
                      completed_at=sp.iso(AT - dt.timedelta(minutes=5)))
        root, _ = layout(tasks=[("h.json", tk)], evidences=[("he.json", ev)])
        loaded = sp.Loaded()
        sp.load_tasks(str(root), loaded)
        sp.load_evidence(str(root), loaded)
        state = sp.build_state(loaded, sp.Verifier(None), AT, 86400, str(self.go_repo(image)), 1800, {})
        identity = state["control_state"]["hk_runtime_identity"]
        self.assertTrue(identity["value"]["host_matches_last_probe"])


class ContractTests(unittest.TestCase):
    def build(self):
        tk = task()
        tpr = task(action="HK_STAGING_TEST_PR", task_id="task-test-pr",
                   nonce="nonce-test-pr",
                   parameters={"builder_profile": "go-application-python-v1",
                               "source": {"repository":
                                          "git@github.com:yuguangzhi3836-glitch/GO.git",
                                          "pr_number": "47", "commit_sha": "c" * 40}})
        tpr_ev = evidence(tpr, executor_result="TEST_PR_OK", built_image_id="sha256:" + "e" * 64)
        request = {"schema_version": "1", "request_id": "boss-hk-verify-1",
                   "action_id": "HK_STAGING_VERIFY", "environment": "HK-STAGING-01",
                   "requested_at": sp.iso(AT)}
        root, req = layout(tasks=[("t.json", tk), ("p.json", tpr)],
                           evidences=[("e.json", evidence(tk)), ("pe.json", tpr_ev)],
                           requests=[("r.json", {"ref": "refs/remotes/origin/boss-request-x",
                                                 "head_sha": "f" * 40, "request": request})])
        loaded = sp.Loaded()
        sp.load_tasks(str(root), loaded)
        sp.load_evidence(str(root), loaded)
        sp.load_requests(str(req), loaded)
        state = sp.build_state(loaded, sp.Verifier(None), AT, 86400, None, 1800, {})
        return state, sp.build_status(state, sp.verdict_for(state["control_state"]))

    def test_answers_cover_every_required_question(self):
        _, status = self.build()
        for key in ("go_is_healthy", "hk_agent_online", "my_task_executed", "pr_tested",
                    "verify", "deploy", "current_runtime", "current_main",
                    "current_release_candidate", "can_deploy", "stuck_tasks",
                    "pending_evidence", "rollback_targets", "control_plane_drift",
                    "release_gates"):
            self.assertIn(key, status["answers"])

    def test_pr_lookup_is_possible_by_pr_number(self):
        _, status = self.build()
        self.assertEqual(sorted(status["answers"]["pr_tested"]["by_pr_number"]), ["47"])
        self.assertEqual(status["answers"]["pr_tested"]["by_pr_number"]["47"][0]["state"],
                         sp.STATE_OBSERVED)

    def test_authority_is_always_derived_and_non_authoritative(self):
        state, status = self.build()
        self.assertEqual(state["authority"], "DERIVED_NON_AUTHORITATIVE")
        self.assertEqual(status["authority"], "DERIVED_NON_AUTHORITATIVE")
        self.assertIn("never authorizes", state["authority_note"])

    def test_status_contract_never_carries_execution_parameters(self):
        _, status = self.build()
        forbidden = {"compose_path", "executor_path", "env_file", "command", "shell",
                     "dockerfile", "image_override", "service", "services", "environment_path",
                     "rollback_image", "signing_key", "private_key", "force_recreate"}

        def walk(node, path):
            if isinstance(node, dict):
                for key, value in node.items():
                    self.assertNotIn(key, forbidden, "forbidden key at %s" % (path + "/" + key))
                    walk(value, path + "/" + key)
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, "%s[%d]" % (path, index))

        walk(status, "")

    def test_status_contract_is_bounded(self):
        _, status = self.build()
        self.assertLess(len(json.dumps(status)), 65536)

    def test_requests_do_not_hold_execution_authority(self):
        state, _ = self.build()
        self.assertEqual(len(state["requests"]), 1)
        self.assertFalse(state["requests"][0]["holding_execution_authority"])
        self.assertEqual(state["requests"][0]["target"], {})

    def test_deploy_request_target_is_only_the_plan_id(self):
        request = {"schema_version": "1", "request_id": "boss-deploy-1",
                   "action_id": "HK_STAGING_DEPLOY", "environment": "HK-STAGING-01",
                   "requested_at": sp.iso(AT), "plan_id": "reviewed-plan-1"}
        root, req = layout(requests=[("d.json", request)])
        loaded = sp.Loaded()
        sp.load_requests(str(req), loaded)
        state = sp.build_state(loaded, sp.Verifier(None), AT, 86400, None, 1800, {})
        self.assertEqual(state["requests"][0]["target"], {"plan_id": "reviewed-plan-1"})

    def test_empty_control_bus_yields_unknown_not_success(self):
        state, status = self.build()
        empty_root, _ = layout()
        loaded = sp.Loaded()
        sp.load_tasks(str(empty_root), loaded)
        sp.load_evidence(str(empty_root), loaded)
        state = sp.build_state(loaded, sp.Verifier(None), AT, 86400, None, 1800, {})
        status = sp.build_status(state, sp.verdict_for(state["control_state"]))
        self.assertEqual(status["answers"]["go_is_healthy"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(status["answers"]["hk_agent_online"]["state"], sp.STATE_UNKNOWN)
        self.assertEqual(status["answers"]["can_deploy"]["state"], sp.STATE_UNKNOWN)

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


class DeterminismTests(unittest.TestCase):
    def test_same_instant_same_bytes(self):
        tk = task()
        root, req = layout(tasks=[("t.json", tk)], evidences=[("e.json", evidence(tk))])
        first = project(root, req)[1]
        second = project(root, req)[1]
        self.assertEqual(sp.canonical(first), sp.canonical(second))

    def test_output_carries_no_wall_clock(self):
        tk = task()
        root, req = layout(tasks=[("t.json", tk)])
        state = project(root, req)[1]
        self.assertEqual(state["generated_at"], sp.iso(AT))


if __name__ == "__main__":
    unittest.main(verbosity=2)
