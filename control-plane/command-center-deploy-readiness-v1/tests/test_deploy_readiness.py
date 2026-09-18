"""Isolated tests for the read-only Deploy Readiness evaluator (CC V1-06 / #101).

This revision exists because the first one could report YES while the live Boss
Request Bridge would deterministically refuse the same request: CANARY and
RELEASE_GATES were advisory, and the canary declaration was reported rather than
re-derived. The rules pinned here are therefore:

  * every mandatory gate PASSes              -> YES
  * any mandatory gate FAILs                 -> NO
  * a live fact nobody can prove             -> UNKNOWN, never an inferred yes
  * YES may never be reported while the live Bridge would refuse the same plan
  * an authorisation that is not derived from an exact DEPLOY Request is never PROVEN
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
# The candidate's delivery identity: the content address of the sealed package
# (contract go.sealed-artifact.v1). There is no registry digest, because a push has
# not happened and a manifest digest is not an image config ID anyway.
CANDIDATE_PACKAGE = "9" * 64
CHANNEL_SHA = "1" * 64
PREV_CHANNEL_SHA = "2" * 64
REQUEST_SHA = "3" * 64  # the DEPLOY Request digest the fixture deploys
PROOF_OBJECTS = ("test_pr_task", "test_pr_evidence", "canary_task", "canary_evidence",
                 "preflight_task", "preflight_evidence")
TEST_PR_AT = "2026-09-14T00:00:00Z"   # the sealed TEST_PR of an immutable candidate
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


def release_candidate(**over):
    """The RELEASE_CANDIDATE_V1 block: what makes a version deployable at all."""
    value = {"schema": "go.release-candidate.v1", "candidate_id": "rc1-synthetic",
             "source_repository": R.CANDIDATE_REPOSITORY, "source_commit": COMMIT,
             "application_tree": TREE, "source_fingerprint": SOURCE_TREE,
             "migration_head": "0133_flight_change_plan", "migration_required": False,
             "build_definition": {"profile": "go-application-python-v1",
                                  "dockerfile": "Dockerfile.go-application-python-v2",
                                  "dockerfile_sha256": "7" * 64,
                                  "executor_version": "test-pr-v2",
                                  "builder_image_tag": "go-hotel:depth48-runtime-synthetic",
                                  "builder_image_id": CURRENT_IMAGE},
             "artifact_digest": CANDIDATE_IMAGE, "required_services": list(R.SERVICES),
             "artifact_package": {"durability": "PROVEN",
                                  "package_sha256": CANDIDATE_PACKAGE},
             "test_result_identity": {"action_id": "HK_STAGING_TEST_PR",
                                      "task_id": "go-boss-test-pr-52-synthetic",
                                      "evidence_id": "synthetic-evidence",
                                      "source_pr_number": "52",
                                      "source_commit_sha": COMMIT,
                                      "artifact_digest": CANDIDATE_IMAGE,
                                      "executor_result": "TEST_PR_OK"},
             "rollback_relation": {"relation": "REPLACES_CURRENT_KNOWN_GOOD",
                                   "previous_known_good_image_id": CURRENT_IMAGE}}
    value.update(over)
    return value


def candidate_pointer(**over):
    block_over = over.pop("release_candidate", {})
    value = {"schema": "go.depth48.current-candidate.v1", "source_commit": COMMIT,
             "application_git_tree": TREE, "previous_application_git_tree": "c" * 40,
             "source_tree_sha256": SOURCE_TREE, "candidate_pr": 52, "candidate_branch": "main"}
    value.update(over)
    value["release_candidate_v1"] = release_candidate(**block_over)
    return value


def channel(**over):
    value = {"version": 4, "mode": "PERSISTENT", "publish_enabled": True,
             "allowed_actions": ["HK_STAGING_VERIFY", "HK_STAGING_TEST_PR", R.DEPLOY_ACTION],
             "allowed_environment": R.ENVIRONMENT, "deployment_authorization": "request"}
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
                  "candidate_package_sha256"):
        if field in parameters:
            evidence[field] = parameters[field]
    return task, sign_b64(keys["evidence"]["private"], evidence)


def test_pr_pair(keys, **over):
    """The signed sealed TEST_PR the plan now carries, in the producer's own shape."""
    parameters = {"builder_profile": "go-application-python-v1",
                  "source": {"repository": "git@github.com:yuguangzhi3836-glitch/GO.git",
                             "pr_number": "52", "commit_sha": COMMIT}}
    task = {"schema_version": "1", "task_id": "go-boss-test-pr-52-synthetic",
            "nonce": "synthetic-test-pr-nonce", "issued_at": "2026-09-14T00:00:00Z",
            "expires_at": "2026-09-14T00:20:00Z", "authority": R.TASK_AUTHORITY,
            "environment": R.ENVIRONMENT, "action_id": "HK_STAGING_TEST_PR",
            "parameters": parameters}
    task.update(over.pop("task", {}))
    task = sign_hex(keys["task"]["private"], task)
    evidence = {"schema_version": "1", "task_id": task["task_id"], "nonce": task["nonce"],
                "action_id": "HK_STAGING_TEST_PR", "environment": R.ENVIRONMENT,
                "status": "SUCCESS", "executor_result": "TEST_PR_OK",
                "executor_version": "test-pr-v3", "started_at": "2026-09-14T00:05:00Z",
                "completed_at": "2026-09-14T00:06:00Z",
                "task_canonical_sha256": R.digest(
                    {k: v for k, v in task.items() if k != "signature"}),
                "source_commit_sha": COMMIT, "source_pr_number": "52",
                "built_image_id": CANDIDATE_IMAGE,
                "artifact_durability": "PROVEN", "deployment_performed": False,
                "artifact_package": {"schema": "go.sealed-artifact.v1",
                                     "package_sha256": CANDIDATE_PACKAGE,
                                     "image_id": CANDIDATE_IMAGE,
                                     "store": "go-hk-artifacts",
                                     "image_identity_role": "root_descriptor"},
                "gate_results": {name: "PASS" for name in R.TEST_PR_GATES}}
    evidence.update(over.pop("evidence", {}))
    assert not over, over
    return task, sign_b64(keys["evidence"]["private"], evidence)


def plan_bundle(keys, **over):
    canary_task, canary_evidence = proof_pair(
        keys, "HK_STAGING_CANARY", "CANARY_OK", R.CANARY_GATES,
        {"release_id": "canary-release-1", "candidate_image_id": CANDIDATE_IMAGE,
         "candidate_package_sha256": CANDIDATE_PACKAGE,
         "expected_current_image_id": CURRENT_IMAGE})
    preflight_task, preflight_evidence = proof_pair(
        keys, "HK_STAGING_VERIFY", "VERIFY_OK", R.VERIFY_GATES,
        {"release_id": "preflight-release-1", "candidate_image_id": CURRENT_IMAGE,
         "expected_current_image_id": CURRENT_IMAGE})
    test_pr_task, test_pr_evidence = test_pr_pair(keys)
    plan = {"schema_version": "1", "plan_id": "release-one", "environment": R.ENVIRONMENT,
            "action_id": R.DEPLOY_ACTION,
            "candidate": {"repository": R.CANDIDATE_REPOSITORY, "source_commit": COMMIT,
                          "application_git_tree": TREE, "source_tree_sha256": SOURCE_TREE,
                          "package_sha256": CANDIDATE_PACKAGE,
                          "image_id": CANDIDATE_IMAGE},
            "expected_current_image_id": CURRENT_IMAGE,
            "target_services": list(R.SERVICES),
            "protected_non_targets": list(R.PROTECTED_NON_TARGETS),
            "migration": False, "production": False, "automatic_rollback": False,
            "test_pr_task_sha256": R.digest(test_pr_task),
            "test_pr_evidence_sha256": R.digest(test_pr_evidence),
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
                "plan_sha256": R.digest(plan), "request_sha256": REQUEST_SHA}
    # The name is a function of the candidate and the canary run, and the approval id is a
    # function of the Request's digest, so the fixture derives both rather than choosing
    # them: a fixture that could choose them would be testing a contract this project no
    # longer has.
    plan["plan_id"] = R.derived_plan_id(plan["candidate"], canary_task)
    approval["plan_sha256"] = R.digest(plan)
    approval["approval_id"] = "approval-" + approval["request_sha256"][:16]
    bundle = {"plan": plan, "approval": approval, "test_pr_task": test_pr_task,
              "test_pr_evidence": test_pr_evidence, "canary_task": canary_task,
              "canary_evidence": canary_evidence, "preflight_task": preflight_task,
              "preflight_evidence": preflight_evidence}
    bundle.update(over)
    return bundle


class Fixture:
    """A synthetic GO checkout, control state and operator bundle.

    Unless `rebind` is off, the plan's proof digests and the approval's plan
    digest are recomputed over the final objects and the approval is re-signed.
    That is what an honest operator does, and it keeps each test expressing one
    intended fault instead of an accidental digest mismatch.
    """

    def __init__(self, collide_task_with_evidence=False, bundle=True, plan=True,
                 channel_value="request", rebind=True, mutate=None, **overrides):
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
            (self.bundle_dir / (built["plan"]["plan_id"] + ".json")).write_text(
                json.dumps(built), encoding="utf-8")
        (self.bundle_dir / "channel.json").write_text(
            json.dumps(channel(deployment_authorization=channel_value)), encoding="utf-8")

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
        self.assertFalse(boundary["can_grant_the_deployment_authorization"])

    def test_no_bundle_is_unknown_not_yes_and_never_fails(self):
        document = Fixture(bundle=False).evaluate()
        self.assertEqual(document["verdict"]["deploy_ready"], "UNKNOWN")
        self.assertEqual(document["verdict"]["failed"], [])
        self.assertIn("DEPLOYMENT_PLAN", document["verdict"]["unknown"])

    def test_a_bundle_without_a_plan_is_no(self):
        document = Fixture(plan=False).evaluate()
        self.assertEqual(gate_of(document, "DEPLOYMENT_PLAN")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_configuration_that_refuses_deployments_is_no(self):
        """The emergency stop, read as a live fact.

        The mode has exactly one accepting value. Setting anything else refuses DEPLOY
        Requests -- and it is the only direction the field can be used in, because the
        field grants nothing.
        """
        for mode in ("suspended", "", None):
            with self.subTest(mode=mode):
                document = Fixture(channel_value=mode).evaluate()
                self.assertEqual(gate_of(document, "LIVE_DEPLOY_MODE")["state"], "FAIL")
                self.assertEqual(document["verdict"]["deploy_ready"], "NO")
        document = Fixture().evaluate()
        self.assertEqual(gate_of(document, "LIVE_DEPLOY_MODE")["state"], "PASS")

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
                 "candidate_package_sha256": CANDIDATE_PACKAGE,
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
                 "candidate_package_sha256": "8" * 64,
                 "expected_current_image_id": CURRENT_IMAGE})
            bundle["canary_task"] = task
            bundle["canary_evidence"] = evidence

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "CANARY")["state"], "FAIL")
        self.assertEqual(gate_of(document, "BRIDGE_ACCEPTANCE")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")


class RetiredReleaseGateTests(unittest.TestCase):
    """The four product-release declarations are gone, and the fact one of them stood for
    is now established by the sealed TEST_PR the plan carries."""

    def test_the_contract_no_longer_declares_any_advisory_gate(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        declared = {k: v for k, v in contract["x-go-gates"].items() if k != "note"}
        self.assertEqual(sorted(k for k, v in declared.items() if not v["mandatory"]), [])
        self.assertTrue(declared["CANARY"]["mandatory"])
        self.assertTrue(declared["BRIDGE_ACCEPTANCE"]["mandatory"])
        # Not "advisory": absent. The evaluator may not report on product acceptance.
        self.assertNotIn("RELEASE_GATES", declared)
        self.assertNotIn("RELEASE_GATES",
                         contract["properties"]["gates"]["items"]["properties"]["gate"]["enum"])
        self.assertEqual(set(declared), set(R.MANDATORY_GATES))

    def test_a_plan_that_still_carries_release_gates_is_refused(self):
        """The retired contract is refused by the exact field set, not read around."""
        def mutate(_keys, bundle):
            bundle["plan"]["gates"] = {name: "PASS" for name in (
                "three_end_ux", "six_vertical_closed_loop", "sealed_node", "final_release")}

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "BRIDGE_ACCEPTANCE")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")
        self.assertEqual(document["advisory_holds"], [])

    def test_a_hold_declaration_can_no_longer_be_expressed_at_all(self):
        """There is nowhere left to write HOLD: the plan has no gate block to hold."""
        def mutate(_keys, bundle):
            bundle["plan"]["sealed_node"] = "HOLD"

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_broken_sealed_test_pr_blocks_instead_of_the_retired_declaration(self):
        for field, value in (("artifact_durability", "NOT_PROVEN"),
                             ("deployment_performed", True),
                             ("built_image_id", "sha256:" + "9" * 64)):
            with self.subTest(field=field):
                def mutate(_keys, bundle, field=field, value=value):
                    bundle["test_pr_evidence"][field] = value

                document = Fixture(mutate=mutate).evaluate()
                self.assertEqual(gate_of(document, "BRIDGE_ACCEPTANCE")["state"], "FAIL")
                self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_plan_name_that_was_not_derived_is_refused(self):
        def mutate(_keys, bundle):
            bundle["plan"]["plan_id"] = "chosen-by-hand"

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "BRIDGE_ACCEPTANCE")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")


class DeploymentAuthorizationTests(unittest.TestCase):
    """The authorisation a deployment rests on, and that it can only be one thing.

    There is no switch and no change record for it any more. What authorises a
    deployment is the authenticated DEPLOY Request, and the plan carries it as its
    `approval` object, so what these tests pin is the derivation: the record must cite
    an exact Request digest, and its id must be the derived form of that digest. A
    standing authorisation -- the shape an operator would have had to write -- has
    nothing to cite and therefore cannot be expressed at all.
    """

    def test_a_derived_authorization_is_proven(self):
        document = Fixture().evaluate()
        entry = gate_of(document, "DEPLOYMENT_AUTHORIZATION")
        self.assertEqual(entry["state"], "PASS")
        self.assertEqual(entry["observed"]["request_sha256"], REQUEST_SHA)
        self.assertEqual(entry["observed"]["approval_id"], "approval-" + REQUEST_SHA[:16])

    def test_a_plan_without_an_authorization_is_refused(self):
        document = Fixture(mutate=lambda _keys, bundle: bundle.__setitem__("approval", None),
                           rebind=False).evaluate()
        self.assertEqual(gate_of(document, "DEPLOYMENT_AUTHORIZATION")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_an_authorization_that_cites_no_request_is_refused(self):
        """The shape a hand-written approval has: nothing to cite."""

        def mutate(_keys, bundle):
            del bundle["approval"]["request_sha256"]

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "DEPLOYMENT_AUTHORIZATION")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_an_authorization_id_that_was_chosen_is_refused(self):
        """The id is a function of the Request, not a name anybody picks."""

        def mutate(_keys, bundle):
            bundle["approval"]["approval_id"] = "approval-chosen-by-hand"

        document = Fixture(mutate=mutate).evaluate()
        self.assertEqual(gate_of(document, "DEPLOYMENT_AUTHORIZATION")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_an_authorization_for_a_different_request_is_refused(self):
        """A digest that is well formed but is not the derived id's own is still refused."""

        def mutate(_keys, bundle):
            bundle["approval"]["request_sha256"] = "0" * 64

        document = Fixture(mutate=mutate, rebind=False).evaluate()
        self.assertEqual(gate_of(document, "DEPLOYMENT_AUTHORIZATION")["state"], "FAIL")

    def test_the_retired_switch_record_is_no_longer_a_bundle_file(self):
        """It cannot be handed back in: the directory would name two plans."""

        fixture = Fixture()
        (fixture.bundle_dir / "switch-provenance.json").write_text(json.dumps(
            {"schema_version": "1", "field": "deployment_requests_enabled", "value": True}),
            encoding="utf-8")
        document = fixture.evaluate()
        self.assertNotEqual(gate_of(document, "DEPLOYMENT_PLAN")["state"], "PASS")
        self.assertNotEqual(document["verdict"]["deploy_ready"], "YES")

    def test_nothing_reads_a_switch_any_more(self):
        for name in ("LIVE_SWITCH", "LIVE_SWITCH_PROVENANCE"):
            self.assertNotIn(name, R.MANDATORY_GATES)
            self.assertFalse(hasattr(R, "gate_" + name.lower()))
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertNotIn("LIVE_SWITCH", json.dumps(contract))
        self.assertNotIn("deployment_requests_enabled", json.dumps(contract))


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

        def retired_release_gate(_keys, bundle):
            # The retired contract: a plan that still carries the four product-release
            # declarations is refused by the exact field set, not read around.
            bundle["plan"]["gates"] = {name: "PASS" for name in (
                "three_end_ux", "six_vertical_closed_loop", "sealed_node", "final_release")}

        def sealed_test_pr(_keys, bundle):
            # What replaced sealed_node: an artifact whose sealing was never proven.
            bundle["test_pr_evidence"]["artifact_durability"] = "NOT_PROVEN"

        def plan_name_not_derived(_keys, bundle):
            bundle["plan"]["plan_id"] = "chosen-by-hand"

        def package_not_the_sealed_one(_keys, bundle):
            # A plan may not name a package the candidate has not sealed.
            bundle["plan"]["candidate"]["package_sha256"] = "7" * 64

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
                "retired_release_gate": (retired_release_gate, True),
                "sealed_test_pr": (sealed_test_pr, True),
                "plan_name_not_derived": (plan_name_not_derived, True),
                "package_binding": (package_not_the_sealed_one, True),
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
        found = re.search(r"^%s = [\{\(](.*?)[\}\)]" % name, self.source, re.M | re.S)
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
        conditional = re.search(
            r"exact\([^,]+,\s*\(\*([A-Z][A-Z0-9_]*),\s*'[^']+'\)\s*if\s+.*?\s+else\s+\1\s*,'%s'\)"
            % marker, self.source)
        if conditional is not None:
            constant = conditional.group(1)
        else:
            named = re.search(r"exact\([^,]+,\s*([A-Z][A-Z0-9_]*)\s*,'%s'\)" % marker,
                              self.source)
            self.assertIsNotNone(named, marker)
            constant = named.group(1)
        declared = re.search(r"^%s = [\(\{]([^\)\}]*)[\)\}]" % re.escape(constant),
                             self.source, re.M)
        self.assertIsNotNone(declared, "the field set %s is never declared" % constant)
        return set(re.findall(r"'([A-Za-z0-9_]+)'", declared.group(1)))

    def test_the_retired_release_gates_are_gone_from_the_live_contract(self):
        """The drift guard, inverted: the four declarations must not come back.

        They were product acceptance verdicts no machine process here can produce, and
        the live executor never read them, so the live gate must not declare them and this
        evaluator must not port them.
        """
        for name in ("three_end_ux", "six_vertical_closed_loop", "sealed_node", "final_release"):
            with self.subTest(gate=name):
                self.assertNotIn("'%s'" % name, self.source)
        self.assertIsNone(re.search(r"^RELEASE_GATES = \{", self.source, re.M))
        self.assertFalse(hasattr(R, "REQUIRED_PLAN_GATES"))

    def test_the_test_pr_constants_match_the_live_contract(self):
        self.assertEqual(self.brace_set("TEST_PR_GATES"), set(R.TEST_PR_GATES))
        self.assertEqual(set(R.TEST_PR_PARAMETERS) | set(R.TEST_PR_SOURCE),
                         {"builder_profile", "source", "repository", "pr_number", "commit_sha"})

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

    def test_the_deployment_authorization_form_matches_the_live_gate(self):
        """The authorisation's id is derived, on both sides, the same way.

        This is what replaced the switch. What stops a hand-written authorisation is not
        a signature -- there is no approval key -- but the derivation: the id has to be
        the derived form of the Request digest the record cites, so a record that cites
        nothing, or cites something and names itself, is refused.
        """
        derived = re.search(r"return '(approval-)'\+request_sha256\[:(\d+)\]", self.source)
        self.assertIsNotNone(derived, "the live gate no longer derives the approval id")
        self.assertEqual(derived.group(1), R.APPROVAL_ID_PREFIX)
        self.assertEqual(int(derived.group(2)), 16)
        bridge = (BOSS / "go-boss-request-bridge").read_text(encoding="utf-8")
        mode = re.search(r'^AUTHORIZATION_MODE = "([a-z]+)"', bridge, re.M)
        self.assertIsNotNone(mode, "the live Bridge no longer declares an authorisation mode")
        self.assertEqual(mode.group(1), R.AUTHORIZATION_MODE)
        self.assertNotIn("deployment_requests_enabled", bridge.replace(
            "`deployment_requests_enabled`", ""))

    def test_the_plan_name_is_derived_by_the_live_gate(self):
        """The name is a function, and the port has to return the same one."""
        self.assertIn("def plan_id_for(candidate,canary_task):", self.source)
        candidate = {"source_commit": COMMIT, "image_id": CANDIDATE_IMAGE}
        canary = {"parameters": {"release_id": "boss-request-canary-synthetic"}}
        self.assertEqual(R.derived_plan_id(candidate, canary),
                         "hkstg-%s-%s-%s" % (COMMIT[:12], CANDIDATE_IMAGE[7:19],
                                             hashlib.sha256(
                                                 b"boss-request-canary-synthetic").hexdigest()[:12]))
        self.assertIsNone(R.derived_plan_id(candidate, {"parameters": {}}))

    def test_the_forbidden_operations_match(self):
        found = re.search(r"plan\[k\] is not False for k in \[(.*?)\]", self.source)
        self.assertIsNotNone(found)
        self.assertEqual(set(re.findall(r"'([a-z_]+)'", found.group(1))),
                         set(R.FORBIDDEN_OPERATIONS))

    def scalar(self, name):
        """The right-hand side of a module constant, whatever shape it has."""
        found = re.search(r"^%s = (.*)$" % name, self.source, re.M)
        self.assertIsNotNone(found, name)
        return found.group(1).strip()

    def test_the_freshness_windows_match(self):
        # The windows are named constants now, so the guard reads the constant and the
        # value rather than a literal that a rename would silently invalidate.
        self.assertIn("CANARY_ACTION,authority_key,hk_key,at,CANARY_EVIDENCE_MAX_AGE",
                      self.source)
        self.assertIn("VERIFY_ACTION,authority_key,hk_key,at,VERIFY_EVIDENCE_MAX_AGE",
                      self.source)
        self.assertEqual(self.scalar("CANARY_ACTION"), "'HK_STAGING_CANARY'")
        self.assertEqual(self.scalar("VERIFY_ACTION"), "'HK_STAGING_VERIFY'")
        self.assertEqual(self.scalar("CANARY_EVIDENCE_MAX_AGE"), str(R.CANARY_MAX_AGE_SECONDS))
        self.assertEqual(self.scalar("VERIFY_EVIDENCE_MAX_AGE"), str(R.PREFLIGHT_MAX_AGE_SECONDS))
        self.assertEqual(self.scalar("APPROVAL_MAX_LIFE"), "dt.timedelta(minutes=15)")
        self.assertEqual(R.APPROVAL_MAX_WINDOW_SECONDS, 900)

    def test_the_bridge_still_takes_the_task_key_from_the_store(self):
        self.assertIn("public_key(read_secure(store/'authority.pub',4096))", self.source)
        self.assertIn("public_key(read_secure(store/'hk-evidence.pub',4096))", self.source)
        self.assertIn(
            "validate_bundle(bundle,plan_id,authority,hk,at,approval_identity,request_sha256)",
            self.source)
        # The approval is the Request, so the digest is not optional: a gate that can be
        # called without one would accept an approval that could name any Request.
        self.assertIn("if request_sha256 is None: raise Reject('approval_request_digest_missing')",
                      self.source)
        self.assertIn("if approval['request_sha256']!=request_sha256: raise Reject('approval_request_mismatch')",
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


class CandidateAdmissionTests(unittest.TestCase):
    """A candidate pointer is only deployable if it is a RELEASE_CANDIDATE_V1.

    The definition of deployable lives in the candidate admission component; these
    gates read that contract rather than a weaker second one of their own.
    """

    def rewrite(self, change):
        fixture = Fixture()
        path = fixture.go / "docs" / "canonical-baseline" / "CURRENT_CANDIDATE.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        change(document)
        path.write_text(json.dumps(document), encoding="utf-8")
        return fixture

    def drop_block(self, document):
        del document["release_candidate_v1"]

    def test_the_candidate_contract_is_read_from_the_other_component(self):
        contract = json.loads((REPO.parent / R.RELEASE_CANDIDATE_CONTRACT).read_text(encoding="utf-8"))
        self.assertEqual(contract["$id"], "go.release-candidate.v1")
        self.assertEqual(set(contract["required"]), set(R.RELEASE_CANDIDATE_FIELDS))

    def test_a_pointer_that_is_not_a_release_candidate_fails_the_candidate_gate(self):
        document = self.rewrite(self.drop_block).evaluate()
        entry = gate_of(document, "APPROVED_CANDIDATE")
        self.assertEqual(entry["state"], "FAIL")
        self.assertIn("release_candidate_absent", entry["reason"])
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_pointer_that_is_not_a_release_candidate_fails_the_source_binding(self):
        document = self.rewrite(self.drop_block).evaluate()
        self.assertEqual(gate_of(document, "SOURCE_BINDING")["state"], "FAIL")

    def test_a_pointer_that_is_not_a_release_candidate_fails_the_package_binding(self):
        document = self.rewrite(self.drop_block).evaluate()
        self.assertEqual(gate_of(document, "PACKAGE_BINDING")["state"], "FAIL")

    def test_an_incomplete_block_fails_the_candidate_gate(self):
        def change(document):
            del document["release_candidate_v1"]["rollback_relation"]

        entry = gate_of(self.rewrite(change).evaluate(), "APPROVED_CANDIDATE")
        self.assertEqual(entry["state"], "FAIL")
        self.assertIn("release_candidate_fields", entry["reason"])

    def test_a_block_with_an_extra_field_is_refused(self):
        def change(document):
            document["release_candidate_v1"]["something_else"] = True

        self.assertEqual(gate_of(self.rewrite(change).evaluate(),
                                 "APPROVED_CANDIDATE")["state"], "FAIL")

    def test_a_block_that_disagrees_about_the_source_is_two_candidates(self):
        def change(document):
            document["release_candidate_v1"]["source_fingerprint"] = "9" * 64

        entry = gate_of(self.rewrite(change).evaluate(), "SOURCE_BINDING")
        self.assertEqual(entry["state"], "FAIL")
        self.assertIn("two source identities", entry["reason"])

    def test_a_plan_that_approves_another_artifact_is_refused(self):
        def mutate(_keys, bundle):
            bundle["plan"]["candidate"]["image_id"] = "sha256:" + "8" * 64
            bundle["plan"]["candidate"]["package_sha256"] = "8" * 64

        document = Fixture(mutate=mutate).evaluate()
        entry = gate_of(document, "PACKAGE_BINDING")
        self.assertEqual(entry["state"], "FAIL")
        self.assertIn("does not claim", entry["reason"])
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_the_admitted_candidate_is_named_in_the_gate(self):
        entry = gate_of(Fixture().evaluate(), "APPROVED_CANDIDATE")
        self.assertEqual(entry["state"], "PASS")
        self.assertEqual(entry["observed"]["candidate_id"], "rc1-synthetic")


if __name__ == "__main__":
    unittest.main()
