"""Isolated tests for RELEASE_CANDIDATE_V1 admission (CC V1-08 / #103).

The load-bearing claim is the one the Command Center previously could not make:
*there is a definition of what is deployable, and a candidate that does not meet it
is refused by name at admission.* Every rejection case below is one way a Boss PR
could previously reach the deploy chain half-described.

The two cross-component tests read the live control plane's own sources, so the
constants this component ports cannot drift from the system they describe.

Standard library only. No network, no Git, no subprocess, no runtime credential or
state path, no live Control Plane or Hong Kong contact.
"""
import datetime as dt
import hashlib
import importlib.machinery
import importlib.util
import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

loader = importlib.machinery.SourceFileLoader(
    "go_candidate_admission", str(ROOT / "command-center" / "go-candidate-admission"))
spec = importlib.util.spec_from_loader(loader.name, loader)
A = importlib.util.module_from_spec(spec)
loader.exec_module(A)

CONTRACT = ROOT / A.CONTRACT_FILE
CANONICAL = GO / A.LINEAGE_POINTER
# The signed evidence of the fresh TEST_PR run against this exact candidate. The
# earlier run for the same source stays in the same directory as history.
REAL_EVIDENCE = (ROOT / "tests" / "fixtures" / "real" / "evidence"
                 / "go-boss-test-pr-52-0673b27f427c-KfIhnufHkCAIeXeEufW2E9dBSxRVUsw-.json")
HISTORICAL_EVIDENCE = (ROOT / "tests" / "fixtures" / "real" / "evidence"
                       / "go-boss-test-pr-52-83b0e20f3980-7Wznjcy0Dvdnuf5D8Epv2PgUqDXJIozu.json")
DEPLOY_COMPONENT = GO / "control-plane" / "boss-deploy-request-v1"
BRIDGE = DEPLOY_COMPONENT / "go-boss-request-bridge"
# The deploy gate is where the candidate and service topology rules actually live;
# the bridge carries the git@ form of the repository used to fetch a PR head.
DEPLOY_GATE = DEPLOY_COMPONENT / "go_deploy_request.py"
TEST_PR = (GO / "control-plane" / "boss-test-pr-live-integration-v1" / "hk-staging"
           / "hk_agent" / "test_pr.py")
AT = dt.datetime(2026, 9, 16, 1, 0, tzinfo=dt.timezone.utc)

COMMIT = "b" * 40
TREE = "c" * 40
FINGERPRINT = "d" * 64
DOCKERFILE_SHA = A.BUILDER_DOCKERFILE_SHA256
ARTIFACT = "sha256:" + "e" * 64
OTHER_ARTIFACT = "sha256:" + "f" * 64
KNOWN_GOOD = "sha256:" + "1" * 64


def candidate(**over):
    """A complete, self-consistent RELEASE_CANDIDATE_V1 block."""
    value = {
        "schema": A.SCHEMA,
        "candidate_id": "rc1-synthetic",
        "source_repository": A.CANDIDATE_REPOSITORY,
        "source_commit": COMMIT,
        "application_tree": TREE,
        "source_fingerprint": FINGERPRINT,
        "migration_head": "0133_flight_change_plan",
        "migration_required": False,
        "build_definition": {
            "profile": A.BUILDER_PROFILE,
            "dockerfile": A.BUILDER_DOCKERFILE,
            "dockerfile_sha256": DOCKERFILE_SHA,
            "executor_version": A.BUILDER_EXECUTOR_VERSION,
            "builder_image_tag": A.BUILDER_IMAGE_TAG,
            "builder_image_id": A.BUILDER_IMAGE_ID,
        },
        "artifact_digest": ARTIFACT,
        "required_services": list(A.SERVICES),
        "test_result_identity": {
            "action_id": A.TEST_PR_ACTION,
            "task_id": "go-boss-test-pr-99-synthetic",
            "evidence_id": "synthetic-evidence-commit",
            "source_pr_number": "99",
            "source_commit_sha": COMMIT,
            "artifact_digest": ARTIFACT,
            "executor_result": "TEST_PR_OK",
        },
        "rollback_relation": {
            "relation": "REPLACES_CURRENT_KNOWN_GOOD",
            "previous_known_good_image_id": KNOWN_GOOD,
        },
    }
    for key, patch in over.items():
        if isinstance(patch, dict) and isinstance(value.get(key), dict):
            merged = dict(value[key])
            merged.update(patch)
            value[key] = merged
        else:
            value[key] = patch
    return value


def evidence(**over):
    value = {"schema_version": "1", "action_id": A.TEST_PR_ACTION,
             "task_id": "go-boss-test-pr-99-synthetic", "status": "SUCCESS",
             "executor_result": "TEST_PR_OK", "source_commit_sha": COMMIT,
             "built_image_id": ARTIFACT, "source_pr_number": "99",
             "executor_version": A.BUILDER_EXECUTOR_VERSION,
             "application_health_proven": False, "deployment_performed": False}
    value.update(over)
    return value


def plan(**over):
    body = {"plan_id": "release-synthetic", "migration": False,
            "target_services": list(A.SERVICES),
            "candidate": {"repository": A.CANDIDATE_REPOSITORY, "source_commit": COMMIT,
                          "application_git_tree": TREE, "source_tree_sha256": FINGERPRINT,
                          "image_id": ARTIFACT}}
    if isinstance(over.get("candidate"), dict):
        merged = dict(body["candidate"])
        merged.update(over.pop("candidate"))
        body["candidate"] = merged
    body.update(over)
    return {"plan": body, "approval": {}, "canary_task": {}, "canary_evidence": {},
            "preflight_task": {}, "preflight_evidence": {}}


class Base(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ccv1-admission-"))
        self.document = self.root / "CURRENT_CANDIDATE.json"
        self.evidence_path = self.root / "evidence.json"
        self.plan_path = self.root / "plan.json"

    def write(self, block=None, document=None, evidence_value="default", plan_value="absent",
              go_repo=None):
        if document is None:
            document = {"source_commit": COMMIT, "application_git_tree": TREE,
                        "source_tree_sha256": FINGERPRINT}
        if block is not None:
            document = dict(document, release_candidate_v1=block)
        self.document.write_text(json.dumps(document), encoding="utf-8")
        if evidence_value == "default":
            self.evidence_path.write_text(json.dumps(evidence()), encoding="utf-8")
            evidence_path = self.evidence_path
        elif evidence_value is None:
            evidence_path = None
        else:
            self.evidence_path.write_text(json.dumps(evidence_value), encoding="utf-8")
            evidence_path = self.evidence_path
        if plan_value == "absent":
            plan_path = None
        else:
            self.plan_path.write_text(json.dumps(plan_value), encoding="utf-8")
            plan_path = self.plan_path
        return A.admit(CONTRACT, self.document, evidence_path, plan_path, go_repo, AT, AT)

    def rejected(self, result, reason):
        self.assertEqual(result["verdict"]["admission"], "REJECT", result["verdict"])
        self.assertIn(reason, result["verdict"]["rejected"])
        self.assertFalse(result["verdict"]["accepted"])


class ValidCandidateTests(Base):
    """A candidate that establishes every identity is admitted."""

    def test_a_complete_candidate_is_accepted(self):
        result = self.write(block=candidate())
        self.assertEqual(result["verdict"]["admission"], "ACCEPT", result["verdict"])
        self.assertTrue(result["verdict"]["accepted"])
        self.assertEqual(result["verdict"]["rejected"], [])
        self.assertEqual(result["verdict"]["unknown"], [])

    def test_admission_authorises_nothing(self):
        result = self.write(block=candidate())
        boundary = result["authority_boundary"]
        self.assertEqual(sorted(k for k, v in boundary.items() if v),
                         ["may_read_the_candidate_and_its_evidence"])
        self.assertFalse(boundary["is_a_deploy_approval"])
        self.assertFalse(boundary["can_publish_task"])
        self.assertFalse(boundary["signs_anything"])

    def test_the_admitted_identity_is_reported_back(self):
        result = self.write(block=candidate())
        self.assertEqual(result["release_candidate"]["candidate_id"], "rc1-synthetic")
        self.assertEqual(result["release_candidate"]["artifact_digest"], ARTIFACT)
        self.assertEqual(result["release_candidate"]["source_commit"], COMMIT)

    def test_a_plan_that_approves_this_candidate_is_cross_checked_and_passes(self):
        result = self.write(block=candidate(), plan_value=plan())
        self.assertEqual(result["verdict"]["admission"], "ACCEPT", result["verdict"])
        self.assertEqual(result["verdict"]["not_evaluated"], [])

    def test_without_a_plan_the_plan_rule_is_not_evaluated_rather_than_unknown(self):
        result = self.write(block=candidate())
        self.assertIn("plan_candidate_absent", result["verdict"]["not_evaluated"])
        self.assertEqual(result["verdict"]["unknown"], [])


class RejectionTests(Base):
    """Every way a candidate can fail to establish itself."""

    def test_a_missing_block_is_rejected(self):
        result = self.write(block=None)
        self.rejected(result, "release_candidate_absent")

    def test_a_missing_identity_is_rejected(self):
        block = candidate()
        del block["rollback_relation"]
        self.rejected(self.write(block=block), "release_candidate_fields")

    def test_an_extra_field_is_rejected(self):
        block = candidate()
        block["extra"] = "x"
        self.rejected(self.write(block=block), "release_candidate_fields")

    def test_a_wrong_schema_is_rejected(self):
        self.rejected(self.write(block=candidate(schema="go.something.else")),
                      "release_candidate_schema")

    def test_another_repository_is_rejected(self):
        self.rejected(self.write(block=candidate(source_repository="someone/else")),
                      "candidate_repository")

    def test_a_branch_name_is_not_an_immutable_source(self):
        self.rejected(self.write(block=candidate(source_commit="main")),
                      "candidate_source_commit_not_immutable")

    def test_an_abbreviated_commit_is_not_immutable(self):
        self.rejected(self.write(block=candidate(source_commit="bd25d7a")),
                      "candidate_source_commit_not_immutable")

    def test_a_ref_is_not_an_immutable_source(self):
        self.rejected(self.write(block=candidate(source_commit="refs/pull/52/head")),
                      "candidate_source_commit_not_immutable")

    def test_an_absent_commit_is_rejected(self):
        self.rejected(self.write(block=candidate(source_commit=None)), "candidate_source_commit")

    def test_a_fingerprint_that_disagrees_with_the_lineage_pointer_is_rejected(self):
        block = candidate(source_fingerprint="9" * 64)
        self.rejected(self.write(block=block),
                      "source_identity_disagrees_with_the_lineage_pointer")

    def test_a_commit_that_disagrees_with_the_lineage_pointer_is_rejected(self):
        block = candidate(source_commit="a" * 40)
        self.rejected(self.write(block=block),
                      "source_identity_disagrees_with_the_lineage_pointer")

    def test_a_malformed_fingerprint_is_rejected(self):
        document = {"source_commit": COMMIT, "application_git_tree": TREE,
                    "source_tree_sha256": FINGERPRINT}
        self.rejected(self.write(block=candidate(source_fingerprint="not-a-sha"), document=document),
                      "candidate_source_fingerprint")

    def test_a_candidate_that_needs_a_migration_is_rejected(self):
        self.rejected(self.write(block=candidate(migration_required=True)),
                      "candidate_migration_required")

    def test_a_missing_migration_head_is_rejected(self):
        self.rejected(self.write(block=candidate(migration_head=None)), "candidate_migration_head")

    def test_a_build_definition_from_another_builder_is_rejected(self):
        self.rejected(self.write(block=candidate(build_definition={"profile": "someone-elses"})),
                      "candidate_build_profile")

    def test_a_build_definition_from_another_dockerfile_is_rejected(self):
        self.rejected(self.write(block=candidate(
            build_definition={"dockerfile": "Dockerfile.something-else"})),
            "candidate_build_dockerfile")

    def test_a_dockerfile_digest_that_is_not_the_staged_one_is_rejected(self):
        self.rejected(self.write(block=candidate(
            build_definition={"dockerfile_sha256": "0" * 64})),
            "candidate_build_dockerfile_sha256")

    def test_a_partial_build_definition_is_rejected(self):
        block = candidate()
        block["build_definition"] = {"profile": A.BUILDER_PROFILE}
        self.rejected(self.write(block=block), "candidate_build_definition")

    def test_a_missing_artifact_digest_is_rejected(self):
        self.rejected(self.write(block=candidate(artifact_digest=None)),
                      "candidate_artifact_digest")

    def test_an_artifact_digest_that_is_not_an_image_id_is_rejected(self):
        self.rejected(self.write(block=candidate(artifact_digest="bed9edde")),
                      "candidate_artifact_digest")

    def test_a_service_outside_the_fixed_topology_is_rejected(self):
        services = list(A.SERVICES)[:7] + ["something-else"]
        self.rejected(self.write(block=candidate(required_services=services)),
                      "fixed_topology_required")

    def test_a_subset_of_the_fixed_topology_is_rejected(self):
        self.rejected(self.write(block=candidate(required_services=list(A.SERVICES)[:7])),
                      "fixed_topology_required")

    def test_a_test_result_from_another_action_is_rejected(self):
        self.rejected(self.write(block=candidate(
            test_result_identity={"action_id": "HK_STAGING_VERIFY"})),
            "candidate_test_pr_action")

    def test_a_test_result_that_is_not_a_success_is_rejected(self):
        self.rejected(self.write(block=candidate(
            test_result_identity={"executor_result": "TEST_PR_FAILED"})),
            "candidate_test_result_not_a_success")

    def test_a_test_result_for_another_commit_is_rejected(self):
        """The defect this exists to stop: tested commit A, deploying artifact B."""
        self.rejected(self.write(block=candidate(
            test_result_identity={"source_commit_sha": "a" * 40})),
            "candidate_test_result_source_commit")

    def test_a_test_result_for_another_artifact_is_rejected(self):
        self.rejected(self.write(block=candidate(
            test_result_identity={"artifact_digest": OTHER_ARTIFACT})),
            "candidate_test_result_artifact_digest")

    def test_evidence_for_another_commit_is_rejected(self):
        self.rejected(self.write(block=candidate(),
                                 evidence_value=evidence(source_commit_sha="a" * 40)),
                      "candidate_test_result_evidence_source_commit")

    def test_evidence_for_another_artifact_is_rejected(self):
        self.rejected(self.write(block=candidate(),
                                 evidence_value=evidence(built_image_id=OTHER_ARTIFACT)),
                      "candidate_test_result_evidence_artifact")

    def test_evidence_for_another_task_is_rejected(self):
        self.rejected(self.write(block=candidate(),
                                 evidence_value=evidence(task_id="go-boss-test-pr-98-other")),
                      "candidate_test_result_evidence_task")

    def test_failed_evidence_is_rejected(self):
        self.rejected(self.write(block=candidate(),
                                 evidence_value=evidence(status="FAILED")),
                      "candidate_test_result_evidence_not_success")

    def test_unreadable_evidence_is_rejected(self):
        self.evidence_path.write_text("{not json", encoding="utf-8")
        self.document.write_text(json.dumps(
            {"source_commit": COMMIT, "application_git_tree": TREE,
             "source_tree_sha256": FINGERPRINT,
             "release_candidate_v1": candidate()}), encoding="utf-8")
        result = A.admit(CONTRACT, self.document, self.evidence_path, None, None, AT, AT)
        self.rejected(result, "candidate_test_result_evidence_unreadable")

    def test_an_unknown_rollback_relation_is_rejected(self):
        self.rejected(self.write(block=candidate(
            rollback_relation={"relation": "MAYBE"})), "candidate_rollback_relation_unknown")

    def test_a_rollback_target_that_is_not_an_image_is_rejected(self):
        self.rejected(self.write(block=candidate(
            rollback_relation={"previous_known_good_image_id": "latest"})),
            "candidate_rollback_target_absent")

    def test_a_first_release_claiming_a_target_is_rejected(self):
        self.rejected(self.write(block=candidate(
            rollback_relation={"relation": "NO_PREVIOUS_KNOWN_GOOD",
                               "previous_known_good_image_id": KNOWN_GOOD})),
            "candidate_rollback_target")

    def test_a_first_release_with_no_target_is_accepted(self):
        result = self.write(block=candidate(
            rollback_relation={"relation": "NO_PREVIOUS_KNOWN_GOOD",
                               "previous_known_good_image_id": None}))
        self.assertEqual(result["verdict"]["admission"], "ACCEPT", result["verdict"])

    def test_a_plan_for_another_artifact_is_rejected(self):
        self.rejected(self.write(block=candidate(),
                                 plan_value=plan(candidate={"image_id": OTHER_ARTIFACT})),
                      "plan_candidate_artifact_mismatch")

    def test_a_plan_for_another_commit_is_rejected(self):
        self.rejected(self.write(block=candidate(),
                                 plan_value=plan(candidate={"source_commit": "a" * 40})),
                      "plan_candidate_source_mismatch")

    def test_a_plan_for_another_repository_is_rejected(self):
        self.rejected(self.write(block=candidate(),
                                 plan_value=plan(candidate={"repository": "someone/else"})),
                      "plan_candidate_repository_mismatch")

    def test_a_plan_that_declares_a_migration_is_rejected(self):
        self.rejected(self.write(block=candidate(), plan_value=plan(migration=True)),
                      "plan_candidate_migration_mismatch")

    def test_a_plan_without_a_candidate_is_rejected(self):
        self.rejected(self.write(block=candidate(), plan_value=plan(candidate=None)),
                      "plan_candidate_absent")

    def test_a_block_that_is_not_an_object_is_rejected(self):
        self.rejected(self.write(block="rc1"), "release_candidate_not_an_object")

    def test_an_unreadable_candidate_document_is_rejected(self):
        self.document.write_text("{not json", encoding="utf-8")
        result = A.admit(CONTRACT, self.document, None, None, None, AT, AT)
        self.rejected(result, "release_candidate_absent")

    def test_every_rejection_also_refuses_the_verdict(self):
        """No rejection may leave `accepted` true, whatever the rule was."""
        for block in (candidate(source_commit="main"),
                      candidate(artifact_digest=None),
                      candidate(required_services=["api"]),
                      None):
            with self.subTest(block=block):
                result = self.write(block=block)
                if result["verdict"]["rejected"]:
                    self.assertFalse(result["verdict"]["accepted"])
                    self.assertEqual(result["verdict"]["admission"], "REJECT")


class UnknownTests(Base):
    """An input the decision needs but was not given is UNKNOWN, never ACCEPT."""

    def test_an_absent_test_result_context_is_unknown_not_accepted(self):
        result = self.write(block=candidate(), evidence_value=None)
        self.assertEqual(result["verdict"]["admission"], "UNKNOWN", result["verdict"])
        self.assertIn("candidate_test_result_evidence_absent", result["verdict"]["unknown"])
        self.assertFalse(result["verdict"]["accepted"])

    def test_unknown_is_never_reported_as_accepted(self):
        result = self.write(block=candidate(), evidence_value=None)
        self.assertNotEqual(result["verdict"]["admission"], "ACCEPT")
        self.assertFalse(result["verdict"]["accepted"])


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = A.Contract(CONTRACT)
        self.document = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_the_contract_is_the_one_being_implemented(self):
        self.assertEqual(self.document["$id"], A.SCHEMA)
        self.assertEqual(set(self.document["required"]), set(A.RELEASE_CANDIDATE_FIELDS))

    def test_the_verdict_set_is_closed(self):
        self.assertEqual(self.document["x-go-verdicts"]["values"], ["ACCEPT", "REJECT", "UNKNOWN"])

    def test_every_identity_the_brief_names_is_declared(self):
        required = ["candidate_id", "source_repository", "source_commit", "application_tree",
                    "source_fingerprint", "migration_head", "build_definition",
                    "artifact_digest", "required_services", "test_result_identity",
                    "rollback_relation"]
        for name in required:
            self.assertIn(name, self.document["required"], name)

    def test_an_unregistered_reason_is_refused_rather_than_emitted(self):
        with self.assertRaises(A.Refuse):
            self.contract.refuses("a_reason_invented_tomorrow")

    def test_the_authority_block_grants_nothing(self):
        authority = self.document["x-go-authority"]
        self.assertEqual(sorted(k for k, v in authority.items() if v is True), [])

    def test_every_reason_the_validator_emits_is_in_the_contract(self):
        """A synthetic sweep: no code path may emit a token the contract cannot name."""
        emitted = set()
        root = pathlib.Path(tempfile.mkdtemp(prefix="ccv1-admission-sweep-"))
        document = root / "CURRENT_CANDIDATE.json"
        for block in ({}, candidate(artifact_digest=None),
                      candidate(required_services=["api"]),
                      candidate(source_commit="main"), candidate()):
            document.write_text(json.dumps({"source_commit": COMMIT,
                                            "application_git_tree": TREE,
                                            "source_tree_sha256": FINGERPRINT,
                                            "release_candidate_v1": block}), encoding="utf-8")
            evidence_path = root / "evidence.json"
            evidence_path.write_text(json.dumps(evidence()), encoding="utf-8")
            result = A.admit(CONTRACT, document, evidence_path, None, None, AT, AT)
            emitted |= set(result["verdict"]["rejected"]) | set(result["verdict"]["unknown"])
            emitted |= {c["reason"] for c in result["checks"] if c.get("reason")}
        self.assertEqual(sorted(emitted - set(self.contract.refusals)), [])


class LiveConstantTests(unittest.TestCase):
    """The ported constants must equal the live system's own, or this component lies."""

    def setUp(self):
        self.bridge = BRIDGE.read_text(encoding="utf-8")
        self.gate = DEPLOY_GATE.read_text(encoding="utf-8")
        self.test_pr = TEST_PR.read_text(encoding="utf-8")

    def test_the_candidate_repository_matches_the_live_gate(self):
        self.assertIn("candidate['repository']!='%s'" % A.CANDIDATE_REPOSITORY, self.gate)
        self.assertIn("git@github.com:%s.git" % A.CANDIDATE_REPOSITORY, self.bridge)

    def test_the_fixed_service_topology_matches_the_live_gate(self):
        found = re.search(r"^SERVICES = \[(.*?)\]", self.gate, re.M | re.S)
        self.assertIsNotNone(found)
        self.assertEqual(re.findall(r"'([a-z-]+)'", found.group(1)), list(A.SERVICES))

    def test_the_test_pr_action_and_profile_match_the_live_executor(self):
        self.assertIn('ACTION = "%s"' % A.TEST_PR_ACTION, self.test_pr)
        self.assertIn('PROFILE = "%s"' % A.BUILDER_PROFILE, self.test_pr)
        self.assertIn('"builder_profile":"%s"' % A.BUILDER_PROFILE, self.bridge)

    def test_the_executor_version_and_dockerfile_match_the_live_executor(self):
        self.assertIn('"executor_version": "%s"' % A.BUILDER_EXECUTOR_VERSION, self.test_pr)
        self.assertIn('DOCKERFILE = "/usr/local/libexec/go-hk-test-pr/%s"'
                      % A.BUILDER_DOCKERFILE, self.test_pr)
        self.assertEqual(A.BUILDER_DOCKERFILE_PATH,
                         "control-plane/boss-test-pr-live-integration-v1/hk-staging/%s"
                         % A.BUILDER_DOCKERFILE)

    def test_the_staged_dockerfile_digest_is_the_one_in_the_repository(self):
        staged = GO / A.BUILDER_DOCKERFILE_PATH
        self.assertTrue(staged.is_file(), "the staged builder Dockerfile moved: %s" % staged)
        self.assertEqual(hashlib.sha256(staged.read_bytes()).hexdigest(),
                         A.BUILDER_DOCKERFILE_SHA256)

    def test_the_builder_image_pins_match_the_live_executor(self):
        self.assertIn('BUILDER_IMAGE = "%s"' % A.BUILDER_IMAGE_TAG, self.test_pr)
        self.assertIn('BUILDER_IMAGE_ID = "%s"' % A.BUILDER_IMAGE_ID, self.test_pr)


class RealCandidateTests(unittest.TestCase):
    """The canonical candidate, its real signed TEST_PR, and the staged builder."""

    def setUp(self):
        if not CANONICAL.is_file() or not REAL_EVIDENCE.is_file():
            self.skipTest("the canonical candidate or its evidence is not in this checkout")

    def result(self, **over):
        return A.admit(CONTRACT, CANONICAL, REAL_EVIDENCE, over.pop("plan", None),
                       GO, AT, AT)

    def test_the_canonical_candidate_is_a_release_candidate_v1(self):
        result = self.result()
        self.assertEqual(result["verdict"]["admission"], "ACCEPT", result["verdict"])

    def test_the_canonical_candidate_block_is_exactly_the_contract_field_set(self):
        document = json.loads(CANONICAL.read_text(encoding="utf-8"))
        self.assertEqual(set(document["release_candidate_v1"]), set(A.RELEASE_CANDIDATE_FIELDS))

    def test_the_canonical_candidate_source_is_the_pr_head_the_bus_can_resolve(self):
        block = json.loads(CANONICAL.read_text(encoding="utf-8"))["release_candidate_v1"]
        self.assertEqual(block["source_commit"], block["test_result_identity"]["source_commit_sha"])
        self.assertEqual(block["artifact_digest"],
                         block["test_result_identity"]["artifact_digest"])

    def test_the_real_signed_evidence_binds_the_artifact_to_the_source(self):
        block = json.loads(CANONICAL.read_text(encoding="utf-8"))["release_candidate_v1"]
        signed = json.loads(REAL_EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(signed["task_id"], block["test_result_identity"]["task_id"])
        self.assertEqual(signed["source_commit_sha"], block["source_commit"])
        self.assertEqual(signed["built_image_id"], block["artifact_digest"])
        self.assertEqual(signed["source_pr_number"],
                         block["test_result_identity"]["source_pr_number"])
        self.assertEqual(signed["executor_result"], "TEST_PR_OK")
        self.assertEqual(signed["deployment_performed"], False)

    def test_the_reconciliation_moved_the_artifact_not_the_source(self):
        """The fresh TEST_PR is a second build of the same candidate, not another one."""
        old = json.loads(HISTORICAL_EVIDENCE.read_text(encoding="utf-8"))
        new = json.loads(REAL_EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(old["source_commit_sha"], new["source_commit_sha"])
        self.assertEqual(old["source_pr_number"], new["source_pr_number"])
        self.assertEqual(old["executor_version"], new["executor_version"])
        self.assertEqual(old["gate_results"], new["gate_results"])
        self.assertNotEqual(old["built_image_id"], new["built_image_id"])
        block = json.loads(CANONICAL.read_text(encoding="utf-8"))["release_candidate_v1"]
        self.assertEqual(block["artifact_digest"], new["built_image_id"])
        self.assertEqual(block["test_result_identity"]["task_id"], new["task_id"])

    def test_a_real_candidate_whose_evidence_names_another_artifact_is_refused(self):
        document = json.loads(CANONICAL.read_text(encoding="utf-8"))
        document["release_candidate_v1"]["artifact_digest"] = OTHER_ARTIFACT
        scratch = pathlib.Path(tempfile.mkdtemp(prefix="ccv1-admission-real-")) / "c.json"
        scratch.write_text(json.dumps(document), encoding="utf-8")
        result = A.admit(CONTRACT, scratch, REAL_EVIDENCE, None, GO, AT, AT)
        self.assertEqual(result["verdict"]["admission"], "REJECT", result["verdict"])
        self.assertIn("candidate_test_result_artifact_digest", result["verdict"]["rejected"])


if __name__ == "__main__":
    unittest.main()
