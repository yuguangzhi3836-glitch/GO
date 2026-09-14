"""Isolated tests for the read-only Deploy Readiness evaluator (CC V1-06 / #101).

Standard library only. No network, no Git, no subprocess, no runtime credential
or state path, no live Control Plane or Hong Kong contact.

The three rules the issue states are pinned here as tests rather than as prose:

  * every gate satisfied            -> YES
  * any mandatory gate missing/fails -> NO
  * a live fact nobody can prove     -> UNKNOWN, never an inferred yes

and one more that matters just as much: a readiness verdict authorises nothing.
"""
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

loader = importlib.machinery.SourceFileLoader(
    "go_deploy_readiness", str(ROOT / "command-center" / "go-deploy-readiness"))
spec = importlib.util.spec_from_loader(loader.name, loader)
R = importlib.util.module_from_spec(spec)
loader.exec_module(R)

CONTRACT = ROOT / R.CONTRACT_FILE
AT = R.parse_time("2026-09-15T01:00:00Z")
COMMIT = "a" * 40
TREE = "b" * 40
PREV = "c" * 40
SOURCE_TREE = "d" * 64
CURRENT_IMAGE = "sha256:" + "e" * 64
CANDIDATE_IMAGE = "sha256:" + "f" * 64


def gate_of(document, name):
    return [g for g in document["gates"] if g["gate"] == name][0]


def candidate_pointer(**over):
    value = {"schema": "go.depth48.current-candidate.v1", "source_commit": COMMIT,
             "application_git_tree": TREE, "previous_application_git_tree": PREV,
             "source_tree_sha256": SOURCE_TREE, "candidate_pr": 52, "candidate_branch": "main"}
    value.update(over)
    return value


def plan_bundle(**over):
    plan = {"schema_version": "1", "plan_id": "release-one", "environment": R.ENVIRONMENT,
            "action_id": R.DEPLOY_ACTION, "source_commit": COMMIT, "application_git_tree": TREE,
            "candidate": {"source_commit": COMMIT, "application_git_tree": TREE,
                          "source_tree_sha256": SOURCE_TREE, "image_id": CANDIDATE_IMAGE,
                          "repo_digest": "go-hotel@" + CANDIDATE_IMAGE},
            "expected_current_image_id": CURRENT_IMAGE,
            "canary_task_sha256": "1" * 64, "canary_evidence_sha256": "2" * 64,
            "gates": {name: "PASS" for name in R.REQUIRED_PLAN_GATES}}
    approval = {"approval_id": "approval-one", "approved_at": "2026-09-15T00:00:00Z",
                "expires_at": "2026-09-16T00:00:00Z"}
    plan.update(over.pop("plan", {}))
    approval.update(over.pop("approval", {}))
    return {"plan": plan, "approval": approval}


def channel(**over):
    value = {"deployment_requests_enabled": True, "publish_enabled": True,
             "allowed_actions": ["HK_STAGING_VERIFY", "HK_STAGING_TEST_PR", R.DEPLOY_ACTION],
             "allowed_environment": R.ENVIRONMENT}
    value.update(over)
    return value


def control_state(**over):
    state = {
        "schema_version": "1", "contract": R.STATE_CONTRACT,
        "sources": {"go": {"repository": "yuguangzhi3836-glitch/GO",
                           "head_sha": "0" * 40,
                           "canonical_candidate_pointer":
                               "docs/canonical-baseline/CURRENT_CANDIDATE.json",
                           "canonical_runtime_pointer":
                               "docs/canonical-baseline/CURRENT_HK_RUNTIME.json"}},
        "freshness": {"live_verification_window_seconds": 86400},
        "control_state": {
            "live_verified_runtime": {"state": "PROVEN", "value": {
                "image_config_id": CURRENT_IMAGE, "age_seconds": 60,
                "verified_at": "2026-09-15T00:30:00Z"}},
            "repository_runtime_pointer": {"value": {"image_config_id": CURRENT_IMAGE}},
            "runtime_verification_state": "MATCH"},
        "tasks": [{"task_id": "synthetic-test-pr", "action_id": "HK_STAGING_TEST_PR",
                   "issued_at": "2026-09-15T00:10:00Z", "lifecycle": "COMPLETE",
                   "parameters": {"source": {"commit_sha": COMMIT}},
                   "evidence": {"status": "SUCCESS", "source": {"path": "evidence/t.json"}}}]}
    state.update(over)
    return state


class Fixture:
    """A synthetic GO checkout, a derived state document and an optional bundle."""

    def __init__(self, state=None, candidate=None, runtime=None, plan=None, channel_value=None,
                 plan_name=None):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ccv106-"))
        go = self.root / "GO" / "docs" / "canonical-baseline"
        go.mkdir(parents=True)
        (go / "CURRENT_CANDIDATE.json").write_text(
            json.dumps(candidate if candidate is not None else candidate_pointer()),
            encoding="utf-8")
        (go / "CURRENT_HK_RUNTIME.json").write_text(json.dumps(
            runtime if runtime is not None else
            {"image_config_id": CURRENT_IMAGE, "image_tag": "synthetic", "host": "i-synthetic",
             "runtime_generation": "SYNTHETIC"}), encoding="utf-8")
        self.state_path = self.root / "state.json"
        self.state_path.write_text(json.dumps(state if state is not None else control_state()),
                                   encoding="utf-8")
        self.go_repo = self.root / "GO"
        self.bundle = None
        if plan is not None or channel_value is not None:
            self.bundle = self.root / "live"
            self.bundle.mkdir()
            if plan is not None:
                name = plan_name or ("%s.json" % plan["plan"]["plan_id"])
                (self.bundle / name).write_text(json.dumps(plan), encoding="utf-8")
            if channel_value is not None:
                (self.bundle / "channel.json").write_text(json.dumps(channel_value),
                                                          encoding="utf-8")

    def evaluate(self):
        return R.evaluate(self.state_path, self.go_repo, self.bundle, AT, AT)

class VerdictTests(unittest.TestCase):
    def test_every_gate_satisfied_is_yes(self):
        document = Fixture(plan=plan_bundle(), channel_value=channel()).evaluate()
        self.assertEqual(document["verdict"]["deploy_ready"], "YES", document["verdict"])
        self.assertEqual(document["blocking_reasons"], [])
        self.assertEqual(document["verdict"]["failed"], [])
        self.assertEqual(document["verdict"]["unknown"], [])

    def test_a_failing_mandatory_gate_is_no(self):
        document = Fixture(plan=plan_bundle(),
                           channel_value=channel(deployment_requests_enabled=False)).evaluate()
        self.assertEqual(document["verdict"]["deploy_ready"], "NO", document["verdict"])
        self.assertEqual(document["verdict"]["failed"], ["LIVE_SWITCH"])
        self.assertTrue(document["blocking_reasons"])

    def test_a_missing_mandatory_live_fact_is_unknown_not_yes(self):
        """The plan store and the switch are live facts: absent means unprovable."""
        document = Fixture().evaluate()
        self.assertEqual(document["verdict"]["deploy_ready"], "UNKNOWN", document["verdict"])
        for name in ("DEPLOYMENT_PLAN", "HUMAN_APPROVAL", "LIVE_SWITCH", "PACKAGE_BINDING",
                     "CURRENT_RUNTIME"):
            self.assertIn(name, document["verdict"]["unknown"], name)
        self.assertEqual(document["verdict"]["failed"], [])

    def test_unknown_outranks_nothing_and_yes_requires_every_mandatory_gate(self):
        document = Fixture(plan=plan_bundle(), channel_value=channel()).evaluate()
        mandatory = [g for g in document["gates"] if g["mandatory"]]
        self.assertEqual(len(mandatory), len(R.MANDATORY_GATES))
        self.assertTrue(all(g["state"] == "PASS" for g in mandatory))

    def test_a_failure_wins_over_an_unknown(self):
        """One definite refusal makes the verdict NO even if others are unprovable."""
        document = Fixture(candidate=candidate_pointer(source_commit="not-a-sha"),
                           plan=plan_bundle(), channel_value=channel()).evaluate()
        self.assertEqual(document["verdict"]["deploy_ready"], "NO", document["verdict"])
        self.assertIn("APPROVED_CANDIDATE", document["verdict"]["failed"])

    def test_the_verdict_always_explains_itself(self):
        for document in (Fixture().evaluate(),
                         Fixture(plan=plan_bundle(), channel_value=channel()).evaluate(),
                         Fixture(plan=plan_bundle(),
                                 channel_value=channel(publish_enabled=False)).evaluate()):
            self.assertTrue(document["verdict"]["reason"])
            if document["verdict"]["deploy_ready"] != "YES":
                self.assertTrue(document["blocking_reasons"])
            for entry in document["blocking_reasons"]:
                self.assertTrue(entry["reason"], entry)


class FailClosedTests(unittest.TestCase):
    def test_a_candidate_without_a_usable_commit_fails(self):
        document = Fixture(candidate=candidate_pointer(source_commit=None)).evaluate()
        self.assertEqual(gate_of(document, "APPROVED_CANDIDATE")["state"], "FAIL")

    def test_an_incomplete_source_identity_fails(self):
        document = Fixture(candidate=candidate_pointer(source_tree_sha256="short")).evaluate()
        binding = gate_of(document, "SOURCE_BINDING")
        self.assertEqual(binding["state"], "FAIL")
        self.assertIn("source_tree_sha256", binding["reason"])

    def test_a_source_mismatch_between_plan_and_candidate_fails(self):
        bundle = plan_bundle()
        bundle["plan"]["candidate"]["source_commit"] = "9" * 40
        document = Fixture(plan=bundle, channel_value=channel()).evaluate()
        binding = gate_of(document, "PACKAGE_BINDING")
        self.assertEqual(binding["state"], "FAIL")
        self.assertIn("source_commit", binding["reason"])
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_an_image_whose_repo_digest_does_not_match_fails(self):
        """The existing Hong Kong contract requires them equal; never accommodated."""
        bundle = plan_bundle()
        bundle["plan"]["candidate"]["repo_digest"] = "go-hotel@sha256:" + "7" * 64
        document = Fixture(plan=bundle, channel_value=channel()).evaluate()
        binding = gate_of(document, "PACKAGE_BINDING")
        self.assertEqual(binding["state"], "FAIL")
        self.assertIn("repo_digest_suffix_must_equal_image_id", binding["reason"])

    def test_an_expired_approval_fails(self):
        bundle = plan_bundle()
        bundle["approval"]["expires_at"] = "2026-09-15T00:30:00Z"
        document = Fixture(plan=bundle, channel_value=channel()).evaluate()
        approval = gate_of(document, "HUMAN_APPROVAL")
        self.assertEqual(approval["state"], "FAIL")
        self.assertIn("expired", approval["reason"])

    def test_an_approval_for_another_candidate_fails(self):
        bundle = plan_bundle()
        bundle["approval"]["source_commit"] = "8" * 40
        document = Fixture(plan=bundle, channel_value=channel()).evaluate()
        approval = gate_of(document, "HUMAN_APPROVAL")
        self.assertEqual(approval["state"], "FAIL")
        self.assertIn("different source_commit", approval["reason"])

    def test_a_plan_file_must_match_its_plan_id(self):
        document = Fixture(plan=plan_bundle(), plan_name="somewhere-else.json",
                           channel_value=channel()).evaluate()
        plan = gate_of(document, "DEPLOYMENT_PLAN")
        self.assertEqual(plan["state"], "FAIL")
        self.assertIn("file_name", plan["reason"])

    def test_a_plan_for_another_environment_or_action_fails(self):
        for over in ({"environment": "PRODUCTION"}, {"action_id": "HK_STAGING_VERIFY"}):
            bundle = plan_bundle()
            bundle["plan"].update(over)
            document = Fixture(plan=bundle, channel_value=channel()).evaluate()
            self.assertEqual(gate_of(document, "DEPLOYMENT_PLAN")["state"], "FAIL", over)

    def test_a_candidate_without_a_test_pr_is_no(self):
        state = control_state(tasks=[])
        document = Fixture(state=state, plan=plan_bundle(), channel_value=channel()).evaluate()
        self.assertEqual(gate_of(document, "TEST_PR")["state"], "FAIL")
        self.assertIn("never been built and tested", gate_of(document, "TEST_PR")["reason"])
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_test_pr_that_did_not_succeed_is_no(self):
        state = control_state()
        state["tasks"][0]["lifecycle"] = "TASK_EXPIRED"
        state["tasks"][0]["evidence"] = None
        document = Fixture(state=state, plan=plan_bundle(), channel_value=channel()).evaluate()
        self.assertEqual(gate_of(document, "TEST_PR")["state"], "FAIL")

    def test_a_test_pr_for_a_different_commit_does_not_count(self):
        state = control_state()
        state["tasks"][0]["parameters"]["source"]["commit_sha"] = "7" * 40
        document = Fixture(state=state, plan=plan_bundle(), channel_value=channel()).evaluate()
        self.assertEqual(gate_of(document, "TEST_PR")["state"], "FAIL")

    def test_a_stale_verify_fails(self):
        state = control_state()
        state["control_state"]["live_verified_runtime"]["value"]["age_seconds"] = 200000
        document = Fixture(state=state, plan=plan_bundle(), channel_value=channel()).evaluate()
        verify = gate_of(document, "VERIFY")
        self.assertEqual(verify["state"], "FAIL")
        self.assertIn("outside the 86400 s window", verify["reason"])

    def test_an_unverified_live_runtime_is_unknown_not_pass(self):
        state = control_state()
        state["control_state"]["live_verified_runtime"] = {"state": "UNKNOWN", "value": None,
                                                           "reason": "no VERIFY at all"}
        document = Fixture(state=state, plan=plan_bundle(), channel_value=channel()).evaluate()
        self.assertEqual(gate_of(document, "VERIFY")["state"], "UNKNOWN")
        self.assertEqual(document["verdict"]["deploy_ready"], "UNKNOWN")

    def test_runtime_drift_is_a_definite_no(self):
        state = control_state()
        state["control_state"]["runtime_verification_state"] = "DRIFT"
        document = Fixture(state=state, plan=plan_bundle(), channel_value=channel()).evaluate()
        self.assertEqual(gate_of(document, "CURRENT_RUNTIME")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_plan_expecting_a_different_current_image_fails(self):
        bundle = plan_bundle()
        bundle["plan"]["expected_current_image_id"] = "sha256:" + "9" * 64
        document = Fixture(plan=bundle, channel_value=channel()).evaluate()
        runtime = gate_of(document, "CURRENT_RUNTIME")
        self.assertEqual(runtime["state"], "FAIL")
        self.assertEqual(runtime["expected"], "sha256:" + "9" * 64)

    def test_a_document_that_is_not_a_control_state_is_refused(self):
        fixture = Fixture()
        fixture.state_path.write_text(json.dumps({"contract": "SOMETHING_ELSE"}),
                                      encoding="utf-8")
        with self.assertRaises(R.Refuse):
            fixture.evaluate()

    def test_a_missing_candidate_pointer_fails_rather_than_guess(self):
        fixture = Fixture()
        (fixture.go_repo / "docs/canonical-baseline/CURRENT_CANDIDATE.json").unlink()
        document = fixture.evaluate()
        self.assertEqual(gate_of(document, "APPROVED_CANDIDATE")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "NO")

    def test_a_symlinked_bundle_file_is_refused(self):
        fixture = Fixture(plan=plan_bundle(), channel_value=channel())
        target = fixture.bundle / "channel.json"
        real = fixture.root / "real-channel.json"
        real.write_bytes(target.read_bytes())
        target.unlink()
        try:
            target.symlink_to(real)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        document = fixture.evaluate()
        self.assertEqual(gate_of(document, "LIVE_SWITCH")["state"], "FAIL")


class AdvisoryTests(unittest.TestCase):
    def test_an_advisory_gate_is_reported_and_never_blocks(self):
        bundle = plan_bundle()
        bundle["plan"]["gates"] = {name: "HOLD" for name in R.REQUIRED_PLAN_GATES}
        document = Fixture(plan=bundle, channel_value=channel()).evaluate()
        self.assertEqual(gate_of(document, "RELEASE_GATES")["state"], "FAIL")
        self.assertFalse(gate_of(document, "RELEASE_GATES")["mandatory"])
        self.assertEqual(document["verdict"]["deploy_ready"], "YES", document["verdict"])
        self.assertEqual([a["gate"] for a in document["advisory_holds"]], ["RELEASE_GATES"])

    def test_a_missing_canary_binding_is_reported(self):
        bundle = plan_bundle()
        bundle["plan"]["canary_evidence_sha256"] = None
        document = Fixture(plan=bundle, channel_value=channel()).evaluate()
        self.assertEqual(gate_of(document, "CANARY")["state"], "FAIL")
        self.assertEqual(document["verdict"]["deploy_ready"], "YES")
        self.assertIn("CANARY", document["verdict"]["advisory_failed"])

    def test_advisory_gates_are_still_listed_when_they_pass(self):
        document = Fixture(plan=plan_bundle(), channel_value=channel()).evaluate()
        self.assertEqual({g["gate"] for g in document["gates"]},
                         set(R.MANDATORY_GATES) | set(R.ADVISORY_GATES))


class BoundaryTests(unittest.TestCase):
    def test_the_evaluator_holds_no_authority(self):
        document = Fixture(plan=plan_bundle(), channel_value=channel()).evaluate()
        boundary = document["authority_boundary"]
        self.assertFalse(boundary["is_execution_authority"])
        self.assertFalse(boundary["can_create_task"])
        self.assertFalse(boundary["can_publish_task"])
        self.assertFalse(boundary["can_open_the_request_switch"])
        self.assertFalse(boundary["holds_private_key"])
        self.assertFalse(boundary["signs_anything"])
        self.assertFalse(boundary["accepts_caller_supplied_parameters"])
        self.assertFalse(boundary["touches_production"])
        self.assertFalse(boundary["is_a_deploy_approval"])

    def test_yes_is_explicitly_not_an_approval(self):
        document = Fixture(plan=plan_bundle(), channel_value=channel()).evaluate()
        self.assertIn("not an approval", document["verdict"]["reason"])
        self.assertIn("not an approval", " ".join(document["notes"]))

    def test_no_document_contains_a_task_or_a_signature(self):
        document = Fixture(plan=plan_bundle(), channel_value=channel()).evaluate()
        blob = R.canonical(document)
        for forbidden in (b'"signature"', b'"signed_task"', b'"nonce"',
                          b'"grants_execution"', b'"parameters"'):
            self.assertNotIn(forbidden, blob, forbidden)

    def test_production_is_never_a_target(self):
        source = (ROOT / "command-center" / "go-deploy-readiness").read_text(encoding="utf-8")
        # No production environment constant, no production branch: the only
        # occurrences are the boundary flag that denies touching it.
        self.assertNotIn('"PRODUCTION"', source)
        self.assertNotIn("touches_production\": True", source)
        self.assertIn('"touches_production": False', source)

    def test_the_evaluator_reads_no_signing_key(self):
        source = (ROOT / "command-center" / "go-deploy-readiness").read_text(encoding="utf-8")
        for forbidden in ("cryptography", "load_pem_private_key", "import socket", "subprocess"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_rollback_readiness_is_left_to_its_own_issue(self):
        document = Fixture().evaluate()
        self.assertEqual(document["not_evaluated"]["rollback_readiness"], "NOT_IN_SCOPE")
        self.assertIn("#104", document["not_evaluated"]["note"])

    def test_the_live_bundle_input_is_described_as_read_only(self):
        document = Fixture().evaluate()
        self.assertFalse(document["inputs"]["live_bundle"]["supplied"])
        self.assertTrue(document["inputs"]["live_bundle"]["files"] == [])


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_the_verdict_set_is_closed(self):
        verdict = self.schema["properties"]["verdict"]["properties"]["deploy_ready"]
        self.assertEqual(verdict["enum"], ["YES", "NO", "UNKNOWN"])

    def test_the_gate_set_is_closed_and_declares_mandatory(self):
        declared = self.schema["x-go-gates"]
        self.assertEqual(set(declared) - {"note"},
                         set(R.MANDATORY_GATES) | set(R.ADVISORY_GATES))
        self.assertEqual({name for name, value in declared.items()
                          if name != "note" and value["mandatory"]}, set(R.MANDATORY_GATES))

    def test_the_contract_forbids_everything_the_issue_forbids(self):
        forbidden = " ".join(self.schema["x-go-forbidden"])
        for phrase in ("Creating, signing or publishing a DEPLOY Task",
                       "Opening, arming or toggling the DEPLOY request switch",
                       "Any caller-supplied image", "Contacting Command Center or Hong Kong",
                       "Production"):
            self.assertIn(phrase, forbidden)

    def test_the_contract_states_that_unknown_is_never_promoted(self):
        rules = " ".join(self.schema["x-go-verdict-rules"])
        self.assertIn("never rounded up to YES", rules)
        self.assertIn("authorises nothing", rules)

    def test_the_boundary_block_is_all_false_except_reading(self):
        boundary = self.schema["$defs"]["boundary"]["properties"]
        for key, value in boundary.items():
            if key == "may_read_live_command_center_state":
                self.assertEqual(value["const"], True, key)
            else:
                self.assertEqual(value["const"], False, key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
