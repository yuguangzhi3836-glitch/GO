"""Isolated tests for the read-only Deploy Readiness evaluator (CC V1-06 / #101).

This revision exists because the first one could report YES while the live Boss
Request Bridge would deterministically refuse the same request: CANARY and
RELEASE_GATES were advisory, and the canary declaration was reported rather than
re-derived. The rules pinned here are therefore:

  * every mandatory gate PASSes              -> YES
  * any mandatory gate FAILs                 -> NO
  * a live fact nobody can prove             -> UNKNOWN, never an inferred yes
  * YES may never be reported while the live Bridge would refuse the same plan
  * a switch that is on without a record signed by a distinct approval authority
    is never PROVEN
  * a readiness verdict authorises nothing

Standard library plus `cryptography` for the Ed25519 fixtures. No network, no
Git, no subprocess, no runtime credential or state path, no live contact.
"""
import base64
import hashlib
import importlib.machinery
import importlib.util
import json
import pathlib
import re
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
BOSS = REPO / "boss-deploy-request-v1"
sys.path.insert(0, str(ROOT))

loader = importlib.machinery.SourceFileLoader(
    "go_deploy_readiness", str(ROOT / "command-center" / "go-deploy-readiness"))
spec = importlib.util.spec_from_loader(loader.name, loader)
R = importlib.util.module_from_spec(spec)
loader.exec_module(R)

CONTRACT = ROOT / R.CONTRACT_FILE
AT = R.parse_time("2026-09-15T01:00:00Z")
COMMIT = "a" * 40
TREE = "b" * 40
SOURCE_TREE = "d" * 64
CURRENT_IMAGE = "sha256:" + "e" * 64
CANDIDATE_IMAGE = "sha256:" + "f" * 64
CANDIDATE_DIGEST = "go-hotel@" + CANDIDATE_IMAGE
CHANNEL_SHA = "1" * 64
PREV_CHANNEL_SHA = "2" * 64
PROOF_OBJECTS = ("canary_task", "canary_evidence", "preflight_task", "preflight_evidence")
# The authorised approver, taken from the evaluator's own allowlist so the two can
# never drift, and a login that is deliberately outside it.
APPROVER = R.APPROVAL_IDENTITIES[0]
UNAUTHORISED = "someone-else-entirely"


def gate_of(document, name):
    return [g for g in document["gates"] if g["gate"] == name][0]


def keypair():
    """A private key plus the exact Openssh public-key line it publishes."""
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(serialization.Encoding.Raw,
                                            serialization.PublicFormat.Raw)
    prefix = b"ssh-ed25519"
    blob = (len(prefix).to_bytes(4, "big") + prefix
            + len(raw).to_bytes(4, "big") + raw)
    line = b"ssh-ed25519 " + base64.b64encode(blob) + b"\n"
    ssh_sha = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return {"private": private, "line": line, "ssh_sha256": ssh_sha,
            "file_sha256": hashlib.sha256(line).hexdigest()}


def sign_hex(private, value):
    unsigned = {k: v for k, v in value.items() if k != "signature"}
    return dict(unsigned, signature=private.sign(R.canonical(unsigned)).hex())


def sign_b64(private, value):
    unsigned = {k: v for k, v in value.items() if k != "signature"}
    return dict(unsigned, signature=base64.b64encode(
        private.sign(R.canonical(unsigned))).decode("ascii"))


def candidate_pointer(**over):
    value = {"schema": "go.depth48.current-candidate.v1", "source_commit": COMMIT,
             "application_git_tree": TREE, "previous_application_git_tree": "c" * 40,
             "source_tree_sha256": SOURCE_TREE, "candidate_pr": 52, "candidate_branch": "main"}
    value.update(over)
    return value


def channel(**over):
    value = {"version": 4, "mode": "PERSISTENT", "publish_enabled": True,
             "allowed_actions": ["HK_STAGING_VERIFY", "HK_STAGING_TEST_PR", R.DEPLOY_ACTION],
             "allowed_environment": R.ENVIRONMENT, "deployment_requests_enabled": True}
    value.update(over)
    return value


def control_state(**over):
    value = {
        "schema_version": "1", "contract": R.STATE_CONTRACT,
        "sources": {"go": {"repository": "yuguangzhi3836-glitch/GO",
                           "canonical_candidate_pointer":
                               "docs/canonical-baseline/CURRENT_CANDIDATE.json",
                           "canonical_runtime_pointer":
                               "docs/canonical-baseline/CURRENT_HK_RUNTIME.json",
                           "head_sha": "0" * 40}},
        "freshness": {"live_verification_window_seconds": 86400},
        "control_state": {
            "live_verified_runtime": {"state": "PROVEN", "value": {
                "image_config_id": CURRENT_IMAGE, "age_seconds": 60,
                "verified_at": "2026-09-15T00:30:00Z"}},
            "repository_runtime_pointer": {"value": {"image_config_id": CURRENT_IMAGE,
                                                     "image_tag": "synthetic"}},
            "runtime_verification_state": "MATCH"},
        "tasks": [{"task_id": "go-boss-test-pr-52-synthetic", "action_id": "HK_STAGING_TEST_PR",
                   "issued_at": "2026-09-15T00:10:00Z", "lifecycle": "COMPLETE",
                   "parameters": {"source": {"commit_sha": COMMIT}},
                   "evidence": {"status": "SUCCESS",
                                "source": {"path": "evidence/synthetic.json"}}}]}
    value.update(over)
    return value


def proof_pair(keys, action, executor_result, gate_names, parameters):
    """One signed task plus the signed evidence it binds to."""
    task = {"schema_version": "1", "task_id": "go-%s-synthetic" % action.lower(),
            "nonce": "nonce-%s" % action.lower(), "issued_at": "2026-09-15T00:50:00Z",
            "expires_at": "2026-09-15T01:10:00Z", "authority": R.TASK_AUTHORITY,
            "environment": R.ENVIRONMENT, "action_id": action, "parameters": parameters}
    task = sign_hex(keys["task"]["private"], task)
    evidence = {"schema_version": "1", "status": "SUCCESS", "executor_result": executor_result,
                "task_id": task["task_id"], "nonce": task["nonce"], "action_id": action,
                "environment": R.ENVIRONMENT, "started_at": "2026-09-15T00:56:00Z",
                "completed_at": "2026-09-15T00:58:00Z",
                "gate_results": {name: "PASS" for name in gate_names}}
    for field in ("release_id", "candidate_image_id", "expected_current_image_id",
                  "candidate_repo_digest"):
        if field in parameters:
            evidence[field] = parameters[field]
    return task, sign_b64(keys["evidence"]["private"], evidence)


def plan_bundle(keys, **over):
    canary_task, canary_evidence = proof_pair(
        keys, "HK_STAGING_CANARY", "CANARY_OK", R.CANARY_GATES,
        {"release_id": "canary-release-1", "candidate_image_id": CANDIDATE_IMAGE,
         "candidate_repo_digest": CANDIDATE_DIGEST,
         "expected_current_image_id": CURRENT_IMAGE})
    preflight_task, preflight_evidence = proof_pair(
        keys, "HK_STAGING_VERIFY", "VERIFY_OK", R.VERIFY_GATES,
        {"release_id": "preflight-release-1", "candidate_image_id": CURRENT_IMAGE,
         "expected_current_image_id": CURRENT_IMAGE})
    plan = {"schema_version": "1", "plan_id": "release-one", "environment": R.ENVIRONMENT,
            "action_id": R.DEPLOY_ACTION,
            "candidate": {"repository": R.CANDIDATE_REPOSITORY, "source_commit": COMMIT,
                          "application_git_tree": TREE, "source_tree_sha256": SOURCE_TREE,
                          "package_sha256": "9" * 64, "image_id": CANDIDATE_IMAGE,
                          "repo_digest": CANDIDATE_DIGEST},
            "expected_current_image_id": CURRENT_IMAGE,
            "target_services": list(R.SERVICES),
            "protected_non_targets": list(R.PROTECTED_NON_TARGETS),
            "migration": False, "production": False, "automatic_rollback": False,
            "gates": {name: "PASS" for name in R.REQUIRED_PLAN_GATES},
            "canary_task_sha256": R.digest(canary_task),
            "canary_evidence_sha256": R.digest(canary_evidence),
            "preflight_task_sha256": R.digest(preflight_task),
            "preflight_evidence_sha256": R.digest(preflight_evidence)}
    # No signature: the authority is an authenticated GitHub identity, so an
    # approval is a statement about who approved, bound to the plan, and there
    # is nothing for anyone to sign.
    approval = {"schema_version": "1", "approval_id": "approval-synthetic-1",
                "approved_by": APPROVER, "approved_at": "2026-09-15T00:58:30Z",
                "expires_at": "2026-09-15T01:05:00Z", "scope": R.APPROVAL_SCOPE,
                "plan_sha256": R.digest(plan)}
    bundle = {"plan": plan, "approval": approval, "canary_task": canary_task,
              "canary_evidence": canary_evidence, "preflight_task": preflight_task,
              "preflight_evidence": preflight_evidence}
    bundle.update(over)
    return bundle


def switch_provenance(**over):
    record = {"schema_version": "1", "field": "deployment_requests_enabled", "value": True,
              "changed_at": "2026-09-15T00:59:00Z", "change_record": "CC-CHANGE-SYNTHETIC-1",
              "approved_by": APPROVER, "approval_id": "approval-synthetic-1",
              "valid_from": "2026-09-15T00:58:00Z", "valid_until": "2026-09-15T01:30:00Z",
              "before_sha256": PREV_CHANNEL_SHA, "after_sha256": CHANNEL_SHA}
    record.update(over)
    return record


class Fixture:
    """A synthetic GO checkout, control state and operator bundle.

    Unless `rebind` is off, the plan's proof digests and the approval's plan
    digest are recomputed over the final objects and the approval is re-signed.
    That is what an honest operator does, and it keeps each test expressing one
    intended fault instead of an accidental digest mismatch.
    """

    def __init__(self, collide_task_with_evidence=False, bundle=True, plan=True,
                 channel_value=True, provenance=True, rebind=True, mutate=None,
                 provenance_record=None, **overrides):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ccv106-"))
        self.go = self.root / "GO"
        component = self.go / R.STATE_COMPONENT
        (component / "identity" / "keys").mkdir(parents=True)
        (self.go / "docs" / "canonical-baseline").mkdir(parents=True)
        self.keys = {"task": keypair(), "evidence": keypair()}
        if collide_task_with_evidence:
            self.keys["evidence"] = self.keys["task"]
        for role, key in self.keys.items():
            (component / "identity" / "keys" / ("%s.pub" % role)).write_bytes(key["line"])
        roles = {"task": R.ROLE_TASK, "evidence": R.ROLE_EVIDENCE}
        names = {"task": "GO-CC-TASK-MANIFEST-SIGNER", "evidence": "HK-AGENT-EVIDENCE-SIGNER"}
        identities = [{"identity_id": names[role], "role": roles[role],
                       "public_key_path": "identity/keys/%s.pub" % role,
                       "public_key_file_sha256": self.keys[role]["file_sha256"],
                       "public_key_ssh_sha256": self.keys[role]["ssh_sha256"]}
                      for role in ("task", "evidence")]
        (component / "identity" / "VERIFIER_IDENTITIES_V1.json").write_text(
            json.dumps({"schema_version": "1", "contract": "VERIFIER_IDENTITIES_V1",
                        "identities": identities}), encoding="utf-8")
        (self.go / "docs" / "canonical-baseline" / "CURRENT_CANDIDATE.json").write_text(
            json.dumps(candidate_pointer(**overrides.get("candidate", {}))), encoding="utf-8")
        (self.go / "docs" / "canonical-baseline" / "CURRENT_HK_RUNTIME.json").write_text(
            json.dumps({"image_config_id": CURRENT_IMAGE, "image_tag": "synthetic",
                        "host": "i-synthetic", "runtime_generation": "SYNTHETIC"}),
            encoding="utf-8")
        self.state_path = self.root / "CURRENT_CONTROL_STATE.json"
        self.state_path.write_text(json.dumps(control_state(**overrides.get("state", {}))),
                                   encoding="utf-8")
        if not bundle:
            self.bundle_dir = None
            return
        self.bundle_dir = self.root / "live"
        self.bundle_dir.mkdir()
        if plan:
            built = plan_bundle(self.keys, **overrides.get("bundle", {}))
            if mutate is not None:
                mutate(self.keys, built)
            if rebind:
                for name in PROOF_OBJECTS:
                    built["plan"][name + "_sha256"] = R.digest(built[name])
                built["approval"]["plan_sha256"] = R.digest(built["plan"])
            (self.bundle_dir / "release-one.json").write_text(json.dumps(built), encoding="utf-8")
        (self.bundle_dir / "channel.json").write_text(
            json.dumps(channel(deployment_requests_enabled=channel_value)), encoding="utf-8")
        if provenance:
            record = (switch_provenance(**provenance_record)
                      if provenance_record is not None else switch_provenance())
            (self.bundle_dir / "switch-provenance.json").write_text(json.dumps(record),
                                                                    encoding="utf-8")

    def evaluate(self, at=AT):
        return R.evaluate(self.state_path, self.go, self.bundle_dir, at, at)


class KeyProfileTests(unittest.TestCase):
    """Two signing roles are published, and the approval authority is an identity."""

    def test_two_distinct_signing_roles_bind_and_are_reported_distinct(self):
        document = Fixture().evaluate()
        identity = document["identity"]
        self.assertTrue(identity["task_and_evidence_distinct"])
        self.assertEqual(identity["collisions"], [])
        for role in (R.ROLE_TASK, R.ROLE_EVIDENCE):
            self.assertEqual(identity["roles"][role]["binding"], R.BINDING_BOUND)

    def test_the_approval_authority_is_published_as_an_identity_allowlist(self):
        document = Fixture().evaluate()
        self.assertEqual(document["identity"]["approval_identities"],
                         list(R.APPROVAL_IDENTITIES))
        # The cancelled role must be gone: an approval is no longer a published
        # key, so no signing role for it may survive anywhere in the report.
        self.assertEqual(sorted(document["identity"]["roles"]),
                         sorted([R.ROLE_TASK, R.ROLE_EVIDENCE]))
        self.assertFalse(hasattr(R, "APPROVAL_AUTHORITY_ID"))
        self.assertFalse(hasattr(R, "ROLE_APPROVAL"))

    def test_one_key_in_two_roles_is_reported_as_a_collision(self):
        document = Fixture(collide_task_with_evidence=True).evaluate()
        self.assertFalse(document["identity"]["task_and_evidence_distinct"])
        self.assertTrue(any("TASK==EVIDENCE" in clash
                            for clash in document["identity"]["collisions"]))

    def test_a_collision_keeps_the_verdict_out_of_yes(self):
        document = Fixture(collide_task_with_evidence=True).evaluate()
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_replaced_key_file_is_mismatched_and_fails_closed(self):
        fixture = Fixture()
        (fixture.go / R.STATE_COMPONENT / "identity" / "keys" / "evidence.pub").write_bytes(
            fixture.keys["task"]["line"])
        document = fixture.evaluate()
        self.assertEqual(document["identity"]["roles"][R.ROLE_EVIDENCE]["binding"],
                         R.BINDING_IDENTITY_MISMATCH)
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")


class VerdictTests(unittest.TestCase):
    def test_a_fully_proven_bundle_is_yes(self):
        document = Fixture().evaluate()
        self.assertEqual(document["verdict"]["deploy_ready"], "YES",
                         document["blocking_reasons"])
        self.assertEqual(document["blocking_reasons"], [])
        self.assertEqual(document["verdict"]["mandatory_gates"], len(R.MANDATORY_GATES))

    def test_yes_still_authorises_nothing(self):
        document = Fixture().evaluate()
        self.assertEqual(document["verdict"]["deploy_ready"], "YES")
        boundary = document["authority_boundary"]
        self.assertFalse(boundary["is_a_deploy_approval"])
        self.assertFalse(boundary["is_execution_authority"])
        self.assertFalse(boundary["can_publish_task"])
        self.assertFalse(boundary["can_open_the_request_switch"])

    def test_no_bundle_is_unknown_not_yes_and_never_fails(self):
        document = Fixture(bundle=False).evaluate()
        self.assertEqual(document["verdict"]["deploy_ready"], "UNKNOWN")
        self.assertEqual(document["verdict"]["failed"], [])
        self.assertIn("DEPLOYMENT_PLAN", document["verdict"]["unknown"])

    def test_a_bundle_without_a_plan_is_no(self):
        document = Fixture(plan=False).evaluate()
        self.assertEqual(gate_of(document, "DEPLOYMENT_PLAN")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_switch_that_is_off_is_no(self):
        document = Fixture(channel_value=False).evaluate()
        self.assertEqual(gate_of(document, "LIVE_SWITCH")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_every_gate_is_reported_and_mandatory(self):
        document = Fixture().evaluate()
        self.assertEqual([g["gate"] for g in document["gates"]], list(R.MANDATORY_GATES))
        self.assertTrue(all(g["mandatory"] for g in document["gates"]))
        self.assertEqual(document["advisory_holds"], [])


class CanaryTests(unittest.TestCase):
    """CANARY is mandatory and is only proven when the proof itself verifies."""

    def test_a_canary_whose_gate_failed_is_a_failure(self):
        def mutate(keys, bundle):
            task, evidence = proof_pair(
                keys, "HK_STAGING_CANARY", "CANARY_OK", R.CANARY_GATES,
                {"release_id": "canary-release-1", "candidate_image_id": CANDIDATE_IMAGE,
                 "candidate_repo_digest": CANDIDATE_DIGEST,
                 "expected_current_image_id": CURRENT_IMAGE})
            gates = dict(evidence["gate_results"])
            gates["container_cleanup"] = "FAIL"
            evidence["gate_results"] = gates
            bundle["canary_task"] = task
            bundle["canary_evidence"] = sign_b64(keys["evidence"]["private"], evidence)

        document = Fixture(mutate=mutate).evaluate()
        entry = gate_of(document, "CANARY")
        self.assertEqual(entry["state"], "FAIL")
        self.assertIn("container_cleanup", entry["reason"])
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_canary_evidence_with_a_broken_signature_is_a_failure(self):
        def mutate(keys, bundle):
            evidence = dict(bundle["canary_evidence"])
            evidence["signature"] = base64.b64encode(b"\x00" * 64).decode()
            bundle["canary_evidence"] = evidence

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "CANARY")["state"], "FAIL")
        self.assertEqual(gate_of(document, "BRIDGE_ACCEPTANCE")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_stale_canary_is_a_failure(self):
        document = Fixture().evaluate(at=R.parse_time("2026-09-15T01:40:00Z"))
        self.assertEqual(gate_of(document, "CANARY")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_canary_bound_to_another_image_is_a_failure(self):
        def mutate(keys, bundle):
            task, evidence = proof_pair(
                keys, "HK_STAGING_CANARY", "CANARY_OK", R.CANARY_GATES,
                {"release_id": "canary-release-1",
                 "candidate_image_id": "sha256:" + "8" * 64,
                 "candidate_repo_digest": "go-hotel@sha256:" + "8" * 64,
                 "expected_current_image_id": CURRENT_IMAGE})
            bundle["canary_task"] = task
            bundle["canary_evidence"] = evidence

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "CANARY")["state"], "FAIL")
        self.assertEqual(gate_of(document, "BRIDGE_ACCEPTANCE")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")


class ReleaseGateTests(unittest.TestCase):
    """RELEASE_GATES is mandatory now: a HOLD may not be a non-blocking note."""

    def test_a_hold_release_gate_blocks_the_verdict(self):
        def mutate(_keys, bundle):
            bundle["plan"]["gates"]["sealed_node"] = "HOLD"

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "RELEASE_GATES")["state"], "FAIL")
        self.assertEqual(gate_of(document, "BRIDGE_ACCEPTANCE")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")
        self.assertEqual(document["advisory_holds"], [])

    def test_the_contract_no_longer_declares_any_advisory_gate(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        declared = {k: v for k, v in contract["x-go-gates"].items() if k != "note"}
        self.assertEqual(sorted(k for k, v in declared.items() if not v["mandatory"]), [])
        self.assertTrue(declared["CANARY"]["mandatory"])
        self.assertTrue(declared["RELEASE_GATES"]["mandatory"])
        self.assertTrue(declared["BRIDGE_ACCEPTANCE"]["mandatory"])


class SwitchProvenanceTests(unittest.TestCase):
    def test_a_valid_record_is_proven(self):
        document = Fixture().evaluate()
        entry = gate_of(document, "LIVE_SWITCH_PROVENANCE")
        self.assertEqual(entry["state"], "PASS")
        self.assertEqual(entry["observed"]["change_record"], "CC-CHANGE-SYNTHETIC-1")

    def test_an_absent_record_keeps_the_gate_unknown(self):
        document = Fixture(provenance=False).evaluate()
        self.assertEqual(gate_of(document, "LIVE_SWITCH_PROVENANCE")["state"], "UNKNOWN")
        self.assertNotEqual(document["verdict"]["deploy_ready"], "YES")
        self.assertIn("LIVE_SWITCH_PROVENANCE", document["verdict"]["unknown"])

    def test_a_record_that_still_carries_the_cancelled_signature_is_refused(self):
        """The cancelling is one-way: the old signed shape is not accepted back."""

        document = Fixture(provenance_record={"signature": "0" * 128}).evaluate()
        self.assertEqual(gate_of(document, "LIVE_SWITCH_PROVENANCE")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_record_that_disagrees_with_the_live_channel_is_refused(self):
        document = Fixture(provenance_record={"value": False}).evaluate()
        self.assertEqual(gate_of(document, "LIVE_SWITCH_PROVENANCE")["state"], "FAIL")

    def test_a_closed_window_is_refused(self):
        document = Fixture().evaluate(at=R.parse_time("2026-09-15T02:00:00Z"))
        self.assertEqual(gate_of(document, "LIVE_SWITCH_PROVENANCE")["state"], "FAIL")

    def test_a_change_outside_its_window_is_refused(self):
        document = Fixture(provenance_record={"changed_at": "2026-09-15T00:10:00Z"}).evaluate()
        self.assertEqual(gate_of(document, "LIVE_SWITCH_PROVENANCE")["state"], "FAIL")

    def test_a_record_attributed_to_an_unauthorised_identity_is_refused(self):
        document = Fixture(provenance_record={"approved_by": UNAUTHORISED}).evaluate()
        self.assertEqual(gate_of(document, "LIVE_SWITCH_PROVENANCE")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_record_without_an_attribution_is_refused(self):
        fixture = Fixture()
        record = switch_provenance()
        del record["approved_by"]
        (fixture.bundle_dir / "switch-provenance.json").write_text(json.dumps(record),
                                                                   encoding="utf-8")
        document = fixture.evaluate()
        self.assertEqual(gate_of(document, "LIVE_SWITCH_PROVENANCE")["state"], "FAIL")

    def test_the_record_must_name_the_field_it_covers(self):
        document = Fixture(provenance_record={"field": "publish_enabled"}).evaluate()
        self.assertEqual(gate_of(document, "LIVE_SWITCH_PROVENANCE")["state"], "FAIL")


class ApprovalTests(unittest.TestCase):
    def test_an_approval_rebound_to_another_plan_is_refused(self):
        def mutate(_keys, bundle):
            bundle["approval"]["plan_sha256"] = "0" * 64

        document = Fixture(mutate=mutate, rebind=False).evaluate()
        self.assertEqual(gate_of(document, "HUMAN_APPROVAL")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_an_approval_naming_an_unauthorised_identity_is_refused(self):
        def mutate(_keys, bundle):
            bundle["approval"]["approved_by"] = UNAUTHORISED

        document = Fixture(mutate=mutate).evaluate()
        entry = gate_of(document, "HUMAN_APPROVAL")
        self.assertEqual(entry["state"], "FAIL")
        self.assertEqual(entry["observed"]["approved_by"], UNAUTHORISED)
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_an_approval_carrying_a_signature_is_refused(self):
        """A signed approval is the cancelled contract, not a stronger one."""

        def mutate(_keys, bundle):
            bundle["approval"]["signature"] = "0" * 128

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "BRIDGE_ACCEPTANCE")["state"], "FAIL")
        self.assertIn("approval_fields", gate_of(document, "BRIDGE_ACCEPTANCE")["reason"])
        self.assertNotEqual(document["verdict"]["deploy_ready"], "YES")

    def test_an_expired_approval_is_refused(self):
        def mutate(_keys, bundle):
            bundle["approval"]["expires_at"] = "2026-09-15T01:00:30Z"

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "HUMAN_APPROVAL")["state"], "FAIL")

    def test_an_approval_window_wider_than_the_contract_is_refused(self):
        def mutate(_keys, bundle):
            bundle["approval"]["approved_at"] = "2026-09-15T00:40:00Z"

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "HUMAN_APPROVAL")["state"], "FAIL")

    def test_an_approval_older_than_its_proofs_is_refused(self):
        def mutate(_keys, bundle):
            bundle["approval"]["approved_at"] = "2026-09-15T00:57:00Z"

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "HUMAN_APPROVAL")["state"], "FAIL")

    def test_an_approval_with_the_wrong_scope_is_refused(self):
        def mutate(_keys, bundle):
            bundle["approval"]["scope"] = "SOMETHING_ELSE"

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "HUMAN_APPROVAL")["state"], "FAIL")


class BridgeAcceptanceTests(unittest.TestCase):
    """The invariant: readiness may never say YES while the Bridge would refuse."""

    def mutations(self):
        def topology(_keys, bundle):
            bundle["plan"]["target_services"] = list(R.SERVICES)[:7]

        def migration(_keys, bundle):
            bundle["plan"]["migration"] = True

        def release_gate(_keys, bundle):
            bundle["plan"]["gates"]["three_end_ux"] = "HOLD"

        def digest_suffix(_keys, bundle):
            bundle["plan"]["candidate"]["repo_digest"] = "go-hotel@sha256:" + "7" * 64

        def candidate_repository(_keys, bundle):
            bundle["plan"]["candidate"]["repository"] = "someone/else"

        def protected_non_targets(_keys, bundle):
            bundle["plan"]["protected_non_targets"] = ["redis"]

        def unknown_plan_field(_keys, bundle):
            bundle["plan"]["extra"] = "x"

        def approval_identity(_keys, bundle):
            bundle["approval"]["approved_by"] = UNAUTHORISED

        def approval_scope(_keys, bundle):
            bundle["approval"]["scope"] = "SOMETHING_ELSE"

        return {"topology": (topology, True), "migration": (migration, True),
                "release_gate": (release_gate, True), "digest_suffix": (digest_suffix, True),
                "candidate_repository": (candidate_repository, True),
                "protected_non_targets": (protected_non_targets, True),
                "unknown_plan_field": (unknown_plan_field, True),
                "approval_identity": (approval_identity, True),
                "approval_scope": (approval_scope, True)}

    def test_no_mutation_can_be_yes_while_the_bridge_gate_refuses(self):
        for name, (mutate, rebind) in self.mutations().items():
            with self.subTest(name):
                document = Fixture(mutate=mutate, rebind=rebind).evaluate()
                self.assertNotEqual(document["verdict"]["deploy_ready"], "YES",
                                    "readiness said YES for %s" % name)
                self.assertNotEqual(gate_of(document, "BRIDGE_ACCEPTANCE")["state"], "PASS",
                                    "the bridge gate accepted %s" % name)

    def test_a_valid_plan_passes_the_bridge_gate(self):
        document = Fixture().evaluate()
        self.assertEqual(gate_of(document, "BRIDGE_ACCEPTANCE")["state"], "PASS")

    def test_the_bridge_gate_names_the_rule_that_would_refuse(self):
        def mutate(_keys, bundle):
            bundle["plan"]["automatic_rollback"] = True

        document = Fixture(mutate=mutate).evaluate()
        entry = gate_of(document, "BRIDGE_ACCEPTANCE")
        self.assertEqual(entry["state"], "FAIL")
        self.assertIn("forbidden_operation", entry["reason"])

    def test_no_bridge_gate_without_a_bundle(self):
        document = Fixture(bundle=False).evaluate()
        self.assertEqual(gate_of(document, "BRIDGE_ACCEPTANCE")["state"], "UNKNOWN")


class LiveBridgeContractTests(unittest.TestCase):
    """The ported constants must equal the live Bridge's own, or this component lies."""

    def setUp(self):
        self.source = (BOSS / "go_deploy_request.py").read_text(encoding="utf-8")

    def brace_set(self, name):
        found = re.search(r"^%s = \{(.*?)\}" % name, self.source, re.M | re.S)
        self.assertIsNotNone(found, name)
        return set(re.findall(r"'([a-z_]+)'", found.group(1)))

    def exact_fields(self, marker):
        """The field set the live gate compares that object against.

        The gate names the set either inline or through a module constant: eef48f8
        named the approval's set once so the approver-side tool and the tests read
        the same one. Both forms have to be resolved, or the drift this test exists
        to catch would hide behind a rename.
        """
        inline = re.search(r"exact\([^,]+,\{([^}]*)\},'%s'\)" % marker, self.source)
        if inline is not None:
            return set(re.findall(r"'([A-Za-z0-9_]+)'", inline.group(1)))
        named = re.search(r"exact\([^,]+,\s*([A-Z][A-Z0-9_]*)\s*,'%s'\)" % marker, self.source)
        self.assertIsNotNone(named, marker)
        constant = named.group(1)
        declared = re.search(r"^%s = [\(\{]([^\)\}]*)[\)\}]" % re.escape(constant),
                             self.source, re.M)
        self.assertIsNotNone(declared, "the field set %s is never declared" % constant)
        return set(re.findall(r"'([A-Za-z0-9_]+)'", declared.group(1)))

    def test_release_gate_names_match_the_live_contract(self):
        self.assertEqual(self.brace_set("RELEASE_GATES"), set(R.REQUIRED_PLAN_GATES))

    def test_canary_and_verify_gate_names_match(self):
        self.assertEqual(self.brace_set("CANARY_GATES"), set(R.CANARY_GATES))
        self.assertEqual(self.brace_set("VERIFY_GATES"), set(R.VERIFY_GATES))

    def test_the_fixed_service_topology_matches(self):
        found = re.search(r"^SERVICES = \[(.*?)\]", self.source, re.M | re.S)
        self.assertIsNotNone(found)
        self.assertEqual(re.findall(r"'([a-z-]+)'", found.group(1)), list(R.SERVICES))

    def test_the_protected_non_targets_match(self):
        self.assertIn("plan['protected_non_targets']!=['redis','caddy']", self.source)
        self.assertEqual(list(R.PROTECTED_NON_TARGETS), ["redis", "caddy"])

    def test_the_exact_field_sets_match(self):
        self.assertEqual(self.exact_fields("plan_fields"), set(R.PLAN_FIELDS))
        self.assertEqual(self.exact_fields("approval_fields"), set(R.APPROVAL_FIELDS))
        self.assertEqual(self.exact_fields("candidate_fields"), set(R.CANDIDATE_FIELDS))
        self.assertEqual(self.exact_fields("task_fields"), set(R.TASK_FIELDS))

    def test_the_approval_scope_and_authority_match(self):
        self.assertIn("'%s'" % R.APPROVAL_SCOPE, self.source)
        self.assertIn("'%s'" % R.TASK_AUTHORITY, self.source)

    def test_the_forbidden_operations_match(self):
        found = re.search(r"plan\[k\] is not False for k in \[(.*?)\]", self.source)
        self.assertIsNotNone(found)
        self.assertEqual(set(re.findall(r"'([a-z_]+)'", found.group(1))),
                         set(R.FORBIDDEN_OPERATIONS))

    def test_the_freshness_windows_match(self):
        self.assertIn("'HK_STAGING_CANARY',authority_key,hk_key,at,1800", self.source)
        self.assertIn("'HK_STAGING_VERIFY',authority_key,hk_key,at,300", self.source)
        self.assertEqual(R.CANARY_MAX_AGE_SECONDS, 1800)
        self.assertEqual(R.PREFLIGHT_MAX_AGE_SECONDS, 300)
        self.assertIn("expires-approved>dt.timedelta(minutes=15)", self.source)
        self.assertEqual(R.APPROVAL_MAX_WINDOW_SECONDS, 900)

    def test_the_bridge_still_takes_the_task_key_from_the_store(self):
        self.assertIn("authority=public_key(read_secure(STORE/'authority.pub',4096))", self.source)
        self.assertIn("validate_bundle(bundle,plan_id,authority,hk,at,approval_identity)",
                      self.source)

    def test_the_two_authorised_approval_identities_match_the_live_gate(self):
        """The allowlist the scope reset introduced, read from the live gate."""

        found = re.search(r"^APPROVAL_IDENTITIES = \(([^)]*)\)", self.source, re.M)
        self.assertIsNotNone(found)
        self.assertEqual(tuple(re.findall(r"'([^']+)'", found.group(1))),
                         tuple(R.APPROVAL_IDENTITIES))

    def test_the_cancelled_approval_key_is_gone_from_the_live_gate(self):
        """The scope reset deleted the dedicated approval key; it must not return."""

        self.assertNotIn("approval-authority.pub", self.source)
        self.assertNotIn("approval_authority", self.source)


class ContractTests(unittest.TestCase):
    def test_the_declared_gate_set_equals_the_implemented_one(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        declared = set(contract["x-go-gates"]) - {"note"}
        self.assertEqual(declared, set(R.MANDATORY_GATES))
        self.assertEqual(set(contract["properties"]["gates"]["items"]["properties"]["gate"]["enum"]),
                         set(R.MANDATORY_GATES))
        self.assertEqual(R.ADVISORY_GATES, ())

    def test_the_verdict_set_is_closed(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["properties"]["verdict"]["properties"]["deploy_ready"]["enum"],
                         ["YES", "NO", "UNKNOWN"])

    def test_the_boundary_is_all_false_except_reading(self):
        boundary = Fixture(bundle=False).evaluate()["authority_boundary"]
        self.assertEqual(sum(1 for value in boundary.values() if value), 1)
        self.assertTrue(boundary["may_read_live_command_center_state"])

    def test_the_identity_block_is_reported(self):
        document = Fixture().evaluate()
        self.assertEqual(document["identity"]["approval_identities"],
                         list(R.APPROVAL_IDENTITIES))
        self.assertIn("roles", document["identity"])

    def test_the_identity_block_still_validates_against_its_own_contract(self):
        """The published schema must describe the identity block actually emitted."""

        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        declared = set(contract["properties"]["identity"]["required"])
        emitted = set(Fixture().evaluate()["identity"])
        self.assertEqual(declared, emitted)

    def test_the_document_keeps_its_scope_statement(self):
        document = Fixture().evaluate()
        self.assertEqual(document["not_evaluated"]["rollback_readiness"], "NOT_IN_SCOPE")
        self.assertEqual(document["scope"], "READ_ONLY_DEPLOY_READINESS")
        self.assertEqual(document["authority"], "DERIVED_NON_AUTHORITATIVE")


if __name__ == "__main__":
    unittest.main()
