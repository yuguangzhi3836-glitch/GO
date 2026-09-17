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
# earlier runs for the same source stay in the same directory as history: PREVIOUS is
# the run this reconciliation replaced, HISTORICAL the one before it.
REAL_EVIDENCE = (ROOT / "tests" / "fixtures" / "real" / "evidence"
                 / "go-boss-test-pr-52-0342850d8822-BHxETPRzcd-8wM9TCrKdOQr-KZ_SZTqK.json")
PREVIOUS_EVIDENCE = (ROOT / "tests" / "fixtures" / "real" / "evidence"
                     / "go-boss-test-pr-52-0673b27f427c-KfIhnufHkCAIeXeEufW2E9dBSxRVUsw-.json")
HISTORICAL_EVIDENCE = (ROOT / "tests" / "fixtures" / "real" / "evidence"
                       / "go-boss-test-pr-52-83b0e20f3980-7Wznjcy0Dvdnuf5D8Epv2PgUqDXJIozu.json")
# The current canonical pairing, frozen (B4-B1.5). The evidence identity is the
# record identity on the evidence repository -- the commit -- and the blob id is
# carried beside it as audit information only, never as evidence_id.
CURRENT_REAL_EVIDENCE_ID = "1865b17d25e6baa6dd2bebc2bdee89cb9a621ad3"
CURRENT_REAL_EVIDENCE_BLOB = "0500b1a098cc9b5e113922facb16b409372ef75a"
CURRENT_REAL_EVIDENCE_SHA256 = "b12537929f4a839a0715f98a9202481a20322b7cfb3c2377785eadd8f1f011ba"
CURRENT_ARTIFACT = "sha256:6b92050ed42c115d29d2ff0b540c711b21747c7ed961384629a35571cf6b93a7"
CURRENT_PACKAGE = "e70238c7c12a67fe6ebd54958237790f82aad39f602bcea3e11699aaa651f382"
SUPERSEDED_ARTIFACT = "sha256:fe0d2c3670444716cf0a84515a4321de1347b6be4570829d3767fe189a6e87e1"
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

    def test_a_builder_claim_the_signed_result_does_not_corroborate_is_refused(self):
        """Declared provenance has to be the provenance the signed result reports.

        `build_definition.executor_version` says how the artifact was made, and an
        artifact id cannot corroborate that on its own: it names the image, not the
        executor that produced it.  Before this binding a candidate was admitted as
        long as it named *any* recognised builder -- so an artifact built by v3 could
        be described as the work of v2, which is exactly the false statement the
        builder list refuses to let a candidate make.
        """
        for declared, signed in (("test-pr-v2", "test-pr-v3"), ("test-pr-v3", "test-pr-v2")):
            with self.subTest(declared=declared, signed=signed):
                result = self.write(candidate(build_definition={"executor_version": declared}),
                                    evidence_value=evidence(executor_version=signed))
                self.rejected(result, "candidate_test_result_evidence_builder_version")

    def test_a_signed_result_that_names_no_builder_corroborates_none(self):
        """Silence is not corroboration: the version the evidence reports must match."""
        value = evidence()
        del value["executor_version"]
        self.rejected(self.write(block=candidate(), evidence_value=value),
                      "candidate_test_result_evidence_builder_version")

    def test_a_malformed_evidence_identity_is_refused(self):
        """`evidence_id` is a record identity, so a path or an absence is not one.

        The shape a blob reference would take -- a path, or nothing at all -- is
        refused by name rather than recorded, which is part of why the field cannot
        quietly turn into the evidence file's own address.
        """
        for value in (".", "-leading-dash", "evidence/the-record.json", "", None):
            with self.subTest(value=value):
                self.rejected(self.write(block=candidate(
                    test_result_identity={"evidence_id": value})),
                    "candidate_test_result_evidence_id")

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

    def test_the_evidence_identity_is_a_record_identity_and_stays_one(self):
        """`evidence_id` names the record, not its bytes, and is not narrowed.

        The contract has always said "commit or record id", and that is left as it
        is. What has to stay true is that both shapes remain expressible: the field
        is not quietly redefined as the digest of the evidence file, and not narrowed
        to a commit-shaped value either. A future reconciliation records the evidence
        repository's commit here, as every earlier one did.
        """
        identity = (self.document["properties"]["test_result_identity"]["properties"]
                    ["evidence_id"])
        self.assertIn("commit or record id", identity["description"])
        pattern = re.compile(identity["pattern"])
        for value in ("go-boss-test-pr-52-0673b27f427c", COMMIT):
            self.assertIsNotNone(pattern.fullmatch(value),
                                 "the contract no longer accepts %r" % value)

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
                      candidate(source_commit="main"),
                      # The builder binding is the newest reason in the vocabulary, so
                      # the sweep has to exercise it or an unregistered token could
                      # reach a report nobody can look up.
                      candidate(build_definition={"executor_version": "test-pr-v2"}),
                      candidate()):
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
        # The gate names the repository once, as a module constant, and compares the plan's
        # candidate against it. The guard resolves the constant rather than the literal, so
        # renaming the constant cannot silently retire the check.
        declared = re.search(r"^REPOSITORY = '([^']+)'", self.gate, re.M)
        self.assertIsNotNone(declared, "the live gate no longer declares REPOSITORY")
        self.assertEqual(declared.group(1), A.CANDIDATE_REPOSITORY)
        self.assertIn("if candidate['repository']!=REPOSITORY: raise Reject('candidate_repository')",
                      self.gate)
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
        self.assertIn('EXECUTOR_VERSION = "%s"' % A.BUILDER_EXECUTOR_VERSION, self.test_pr)
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
        self.assertEqual(set(document["release_candidate_v1"]),
                         set(A.RELEASE_CANDIDATE_FIELDS) | set(A.OPTIONAL_FIELDS))

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
        """Same candidate, same source, and now a different builder generation.

        The earlier reconciliation could say the executor version and the gate results
        were identical, because it was a second build by the same builder. This one
        cannot, and saying so would be false: the artifact this candidate now names
        was built, tested and sealed by test-pr-v3, and the v3 result carries the
        artifact_sealed gate the v2 result never had.
        """
        previous = json.loads(PREVIOUS_EVIDENCE.read_text(encoding="utf-8"))
        new = json.loads(REAL_EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(previous["source_commit_sha"], new["source_commit_sha"])
        self.assertEqual(previous["source_pr_number"], new["source_pr_number"])
        self.assertNotEqual(previous["built_image_id"], new["built_image_id"])
        self.assertEqual(previous["executor_version"], "test-pr-v2")
        self.assertEqual(new["executor_version"], "test-pr-v3")
        self.assertEqual(sorted(previous["gate_results"]), ["isolated_runtime_checks",
                                                            "offline_build", "source_commit"])
        self.assertEqual(sorted(new["gate_results"]), ["artifact_sealed", "isolated_runtime_checks",
                                                       "offline_build", "source_commit"])
        block = json.loads(CANONICAL.read_text(encoding="utf-8"))["release_candidate_v1"]
        self.assertEqual(block["artifact_digest"], new["built_image_id"])
        self.assertEqual(block["test_result_identity"]["task_id"], new["task_id"])
        self.assertEqual(block["build_definition"]["executor_version"], new["executor_version"])
        self.assertEqual(block["artifact_package"]["durability"], "PROVEN")

    def test_a_real_candidate_whose_evidence_names_another_artifact_is_refused(self):
        document = json.loads(CANONICAL.read_text(encoding="utf-8"))
        document["release_candidate_v1"]["artifact_digest"] = OTHER_ARTIFACT
        scratch = pathlib.Path(tempfile.mkdtemp(prefix="ccv1-admission-real-")) / "c.json"
        scratch.write_text(json.dumps(document), encoding="utf-8")
        result = A.admit(CONTRACT, scratch, REAL_EVIDENCE, None, GO, AT, AT)
        self.assertEqual(result["verdict"]["admission"], "REJECT", result["verdict"])
        self.assertIn("candidate_test_result_artifact_digest", result["verdict"]["rejected"])


    def test_the_signed_evidence_corroborates_the_builder_the_candidate_declares(self):
        """Provenance is bound on the real artifacts, not only on synthetic ones."""
        block = json.loads(CANONICAL.read_text(encoding="utf-8"))["release_candidate_v1"]
        signed = json.loads(REAL_EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(signed["executor_version"],
                         block["build_definition"]["executor_version"])

    def test_the_real_evidence_cannot_corroborate_the_builder_it_does_not_report(self):
        """The other recognised builder is not readable out of this signed result.

        Written against whichever version the real evidence reports, so it keeps
        meaning the same thing when the next reconciliation moves the candidate to a
        v3 build: the claim and the proof have to move together.
        """
        document = json.loads(CANONICAL.read_text(encoding="utf-8"))
        signed = json.loads(REAL_EVIDENCE.read_text(encoding="utf-8"))
        others = sorted(v for v in A.BUILDER_EXECUTOR_VERSIONS
                        if v != signed["executor_version"])
        self.assertTrue(others, "the recognised builder list names only one version")
        document["release_candidate_v1"]["build_definition"]["executor_version"] = others[0]
        scratch = pathlib.Path(tempfile.mkdtemp(prefix="ccv1-admission-real-")) / "c.json"
        scratch.write_text(json.dumps(document), encoding="utf-8")
        result = A.admit(CONTRACT, scratch, REAL_EVIDENCE, None, GO, AT, AT)
        self.assertEqual(result["verdict"]["admission"], "REJECT", result["verdict"])
        self.assertIn("candidate_test_result_evidence_builder_version",
                      result["verdict"]["rejected"])

    def test_the_recorded_evidence_identity_is_the_record_not_the_evidence_bytes(self):
        """The identity `evidence_id` records is the evidence repository's commit.

        The canonical block and the reconciliation record that supplied it name the
        same commit.  A blob id computed over the evidence bytes -- which is what one
        cancelled plan would have recorded -- is a different value, and recording it
        would silently change what `evidence_id` has always meant.
        """
        document = json.loads(CANONICAL.read_text(encoding="utf-8"))
        evidence_id = document["release_candidate_v1"]["test_result_identity"]["evidence_id"]
        self.assertIn("release_candidate_reconciliation", document)
        self.assertEqual(evidence_id,
                         document["release_candidate_reconciliation"]["new_evidence_commit"])
        self.assertRegex(evidence_id, r"^[0-9a-f]{40}$")
        raw = REAL_EVIDENCE.read_bytes()
        blob = hashlib.sha1(b"blob %d\x00" % len(raw) + raw).hexdigest()
        self.assertNotEqual(evidence_id, blob,
                            "evidence_id is not the evidence file's blob id")


class PairedReconciliationTests(unittest.TestCase):
    """B4-B1.5.  Image, Evidence and package are one set, or the candidate is refused.

    The reconciliation is only worth anything if the four identities it wrote are the
    four the signed result supports: the artifact the result built, the builder that
    built it, the result itself, and the sealed package that makes the artifact
    deliverable. Each test below moves one of them and requires admission to refuse,
    so a later round cannot quietly move one without the others.
    """

    def setUp(self):
        if not CANONICAL.is_file() or not REAL_EVIDENCE.is_file():
            self.skipTest("the canonical candidate or its evidence is not in this checkout")
        self.document = json.loads(CANONICAL.read_text(encoding="utf-8"))
        self.signed = json.loads(REAL_EVIDENCE.read_text(encoding="utf-8"))

    def admit(self, document, evidence=REAL_EVIDENCE):
        scratch = pathlib.Path(tempfile.mkdtemp(prefix="ccv1-admission-pair-")) / "c.json"
        scratch.write_text(json.dumps(document), encoding="utf-8")
        return A.admit(CONTRACT, scratch, evidence, None, GO, AT, AT)

    def mutated(self, **changes):
        document = json.loads(json.dumps(self.document))
        block = document["release_candidate_v1"]
        for target, patch in changes.items():
            if target == "package_sha256":
                block["artifact_package"]["package_sha256"] = patch
            elif target == "durability":
                block["artifact_package"]["durability"] = patch
            elif target == "executor_version":
                block["build_definition"]["executor_version"] = patch
            elif target == "artifact_digest":
                block["artifact_digest"] = patch
                block["test_result_identity"]["artifact_digest"] = patch
            else:
                raise AssertionError(target)
        return document

    def refused(self, result, reason):
        self.assertEqual(result["verdict"]["admission"], "REJECT", result["verdict"])
        self.assertIn(reason, result["verdict"]["rejected"])
        self.assertFalse(result["verdict"]["accepted"])

    # ------------------------------------------------------------- the four agree
    def test_the_canonical_candidate_and_its_signed_result_are_one_set(self):
        block = self.document["release_candidate_v1"]
        identity = block["test_result_identity"]
        self.assertEqual(self.signed["task_id"], identity["task_id"])
        self.assertEqual(self.signed["executor_result"], identity["executor_result"])
        self.assertEqual(self.signed["source_commit_sha"], block["source_commit"])
        self.assertEqual(self.signed["built_image_id"], block["artifact_digest"])
        self.assertEqual(self.signed["executor_version"],
                         block["build_definition"]["executor_version"])
        self.assertEqual(self.signed["artifact_durability"], "PROVEN")
        self.assertEqual(self.signed["artifact_package"]["package_sha256"],
                         block["artifact_package"]["package_sha256"])
        self.assertEqual(self.signed["artifact_package"]["image_id"],
                         block["artifact_digest"])
        self.assertEqual(block["artifact_package"]["durability"], "PROVEN")

    def test_the_reconciled_candidate_is_admitted_and_its_artifact_is_deliverable(self):
        result = self.admit(self.document)
        self.assertEqual(result["verdict"]["admission"], "ACCEPT", result["verdict"])
        self.assertEqual(result["artifact_durability"]["state"], "PROVEN")
        self.assertTrue(result["deployability"]["deployable_artifact_established"])
        # still not an approval: nothing here may be read as permission to deploy
        self.assertFalse(result["deployability"]["is_a_deploy_approval"])
        self.assertFalse(result["authority_boundary"]["is_a_deploy_approval"])

    # ------------------------------------------- builder provenance (B4-B1.4 gate)
    def test_the_builder_the_candidate_declares_is_the_one_the_result_reports(self):
        self.assertEqual(self.document["release_candidate_v1"]["build_definition"]
                         ["executor_version"], "test-pr-v3")
        self.assertEqual(self.signed["executor_version"], "test-pr-v3")

    def test_a_candidate_relabelled_to_the_previous_builder_is_refused(self):
        """The mutation that proves this round did not pass by the validator being lax.

        Same candidate, same result, same artifact, same package: only the declared
        builder generation moves back to the version that did not produce it.
        """
        self.refused(self.admit(self.mutated(executor_version="test-pr-v2")),
                     "candidate_test_result_evidence_builder_version")

    # ------------------------------------ image / evidence / package are one set
    def test_a_package_the_signed_result_does_not_report_is_refused(self):
        self.refused(self.admit(self.mutated(package_sha256="a" * 64)),
                     "candidate_artifact_package_mismatch")

    def test_a_package_proven_for_another_image_is_refused(self):
        result = self.admit(self.mutated(artifact_digest=SUPERSEDED_ARTIFACT))
        self.assertEqual(result["verdict"]["admission"], "REJECT", result["verdict"])
        # whichever binding catches it first, the three are not one set any more
        self.assertTrue({"candidate_test_result_evidence_artifact",
                         "candidate_artifact_package_mismatch",
                         "candidate_test_result_artifact_digest"}
                        & set(result["verdict"]["rejected"]), result["verdict"])

    def test_the_new_image_with_the_replaced_result_is_refused(self):
        self.refused(self.admit(self.document, evidence=PREVIOUS_EVIDENCE),
                     "candidate_test_result_evidence_task")

    def test_a_proven_durability_with_no_package_address_is_refused(self):
        self.refused(self.admit(self.mutated(package_sha256=None)),
                     "candidate_artifact_package_identity")

    def test_a_package_the_store_holds_but_the_result_never_reported_is_refused(self):
        """The store holding a file is not the proof; the signed result is."""
        document = self.mutated(durability="PROVEN",
                                package_sha256="b" * 64)
        self.refused(self.admit(document), "candidate_artifact_package_mismatch")

    # ------------------------------------------------------- the evidence identity
    def test_the_evidence_identity_is_the_commit_and_never_the_blob(self):
        block = self.document["release_candidate_v1"]
        self.assertEqual(block["test_result_identity"]["evidence_id"], CURRENT_REAL_EVIDENCE_ID)
        raw = REAL_EVIDENCE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), CURRENT_REAL_EVIDENCE_SHA256)
        self.assertNotEqual(block["test_result_identity"]["evidence_id"],
                            CURRENT_REAL_EVIDENCE_BLOB)
        reconciliation = self.document["release_candidate_reconciliation"]
        self.assertEqual(reconciliation["new_evidence_commit"], CURRENT_REAL_EVIDENCE_ID)
        # the blob is carried as audit information, beside the identity, not as it
        self.assertEqual(reconciliation["new_evidence_blob_sha"], CURRENT_REAL_EVIDENCE_BLOB)
        self.assertIn("audit information only", reconciliation["new_evidence_note"])

    def test_the_reconciled_candidate_without_its_evidence_is_not_accepted(self):
        """A PROVEN claim with no proof supplied is refused by name, not rounded up.

        The evidence is what makes the package claim checkable. Supplying none leaves
        the artifact binding unknown -- and because this candidate asserts a proven
        package that no proof covers, admission refuses the claim rather than reporting
        a verdict the claim does not support. Either way it is never ACCEPT.
        """
        result = self.admit(self.document, evidence=None)
        self.assertEqual(result["verdict"]["admission"], "REJECT", result["verdict"])
        self.assertFalse(result["verdict"]["accepted"])
        self.assertIn("candidate_test_result_evidence_absent", result["verdict"]["unknown"])
        self.assertIn("candidate_artifact_package_mismatch", result["verdict"]["rejected"])

    def test_the_even_earlier_result_is_still_in_the_history(self):
        """Three generations of the same candidate's builds are all still on record.

        The fixtures are the evidence trail, not a cache: the result this round
        replaced, and the one before it, both stay, and the replaced block's own
        "previous" pointers name the earlier one.
        """
        earlier = json.loads(HISTORICAL_EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(earlier["task_id"], "go-boss-test-pr-52-83b0e20f3980")
        superseded = [h for h in self.document["release_candidate_reconciliation_history"]
                      if h.get("new_task_id") == "go-boss-test-pr-52-0673b27f427c"][0]
        self.assertEqual(superseded["previous_task_id"], earlier["task_id"])
        self.assertEqual(superseded["previous_artifact_digest"], earlier["built_image_id"])

    def test_the_superseded_v2_result_is_preserved_as_history(self):
        history = self.document.get("release_candidate_reconciliation_history")
        self.assertIsInstance(history, list)
        self.assertTrue(history, "the earlier reconciliation block was lost")
        superseded = [h for h in history if h.get("new_task_id") == "go-boss-test-pr-52-0673b27f427c"]
        self.assertEqual(len(superseded), 1, "the earlier reconciliation was rewritten, not kept")
        self.assertEqual(superseded[0]["new_evidence_commit"],
                         "24bad37acfb34200722a449c6a3672b14efec199")
        self.assertEqual(superseded[0]["new_artifact_digest"], SUPERSEDED_ARTIFACT)
        self.assertIn("why_not_case_b", superseded[0])
        # the current block is the new event, and only the new one
        self.assertEqual(self.document["release_candidate_reconciliation"]["new_evidence_commit"],
                         CURRENT_REAL_EVIDENCE_ID)


class ArtifactDurabilityTests(Base):
    """B4-B1.  A build identity is not a deliverable, and admission must say so.

    The defect these hold shut: test-pr-v2 built an image, reported
    ``built_image_id`` in signed Evidence, and removed the image in its ``finally``
    block.  Every check here passed, because every check was about the build.  Now
    durability is asked separately, and its answer is reported whether or not it is
    favourable.
    """

    PACKAGE = "e" * 64

    def test_the_canonical_candidate_reports_that_its_artifact_is_proven(self):
        """The honest current state, which is no longer NOT_PROVEN.

        Until B4-B1.5 this test pinned the opposite, truthfully: the canonical artifact
        was v2-built and gone. The v3 build sealed it, so the assertion moves to the
        fact instead of the assertion being dropped -- a candidate that says nothing
        about durability is still never called deployable (the tests below).
        """
        document = json.loads(CANONICAL.read_text(encoding="utf-8"))
        scratch = pathlib.Path(tempfile.mkdtemp(prefix="ccv1-admission-real-")) / "c.json"
        scratch.write_text(json.dumps(document), encoding="utf-8")
        result = A.admit(CONTRACT, scratch, REAL_EVIDENCE, None, GO, AT, AT)
        self.assertEqual(result["artifact_durability"]["state"], "PROVEN")
        self.assertEqual(result["artifact_durability"]["package_sha256"], CURRENT_PACKAGE)

    def test_a_candidate_that_says_nothing_about_durability_is_not_deployable(self):
        result = self.write(candidate())
        self.assertEqual(result["verdict"]["admission"], "ACCEPT", result["verdict"])
        self.assertEqual(result["artifact_durability"]["state"], "NOT_PROVEN")
        self.assertFalse(result["deployability"]["deployable_artifact_established"])
        self.assertFalse(result["deployability"]["is_a_deploy_approval"])

    def test_a_signed_test_pr_with_no_sealed_package_is_never_called_deployable(self):
        """The exact ephemeral-artifact case: the evidence is true, the image is gone."""
        result = self.write(candidate(artifact_package={"durability": "NOT_PROVEN",
                                                        "package_sha256": None}))
        self.assertEqual(result["verdict"]["admission"], "ACCEPT", result["verdict"])
        self.assertIs(result["deployability"]["deployable_artifact_established"], False)
        self.assertEqual(result["deployability"]["reason"],
                         "candidate_artifact_package_not_proven")

    def test_a_candidate_cannot_claim_a_package_its_evidence_never_reported(self):
        result = self.write(candidate(artifact_package={"durability": "PROVEN",
                                                        "package_sha256": self.PACKAGE}))
        self.rejected(result, "candidate_artifact_package_mismatch")

    def test_a_proven_package_that_the_evidence_reports_is_deployable(self):
        result = self.write(candidate(artifact_package={"durability": "PROVEN",
                                                        "package_sha256": self.PACKAGE}),
                            evidence_value=evidence(artifact_package={
                                "schema": "go.sealed-artifact.v1", "image_id": ARTIFACT,
                                "package_sha256": self.PACKAGE}))
        self.assertEqual(result["verdict"]["admission"], "ACCEPT", result["verdict"])
        self.assertEqual(result["artifact_durability"]["state"], "PROVEN")
        self.assertEqual(result["artifact_durability"]["package_sha256"], self.PACKAGE)
        self.assertTrue(result["deployability"]["deployable_artifact_established"])

    def test_a_package_that_is_not_a_content_address_is_refused(self):
        for value in ("go-hotel@sha256:" + "a" * 64, "not-a-digest", "A" * 64, ""):
            result = self.write(candidate(artifact_package={"durability": "PROVEN",
                                                            "package_sha256": value}))
            self.rejected(result, "candidate_artifact_package_identity")

    def test_an_unknown_durability_value_is_refused(self):
        result = self.write(candidate(artifact_package={"durability": "MAYBE",
                                                        "package_sha256": None}))
        self.rejected(result, "candidate_artifact_package")

    def test_a_partial_artifact_package_is_refused(self):
        result = self.write(candidate(artifact_package={"durability": "PROVEN"}))
        self.rejected(result, "candidate_artifact_package")

    def test_a_package_proven_for_another_image_is_refused(self):
        result = self.write(candidate(artifact_package={"durability": "PROVEN",
                                                        "package_sha256": self.PACKAGE}),
                            evidence_value=evidence(artifact_package={
                                "schema": "go.sealed-artifact.v1",
                                "image_id": OTHER_ARTIFACT,
                                "package_sha256": self.PACKAGE}))
        self.rejected(result, "candidate_artifact_package_mismatch")

    def test_a_build_by_the_previous_builder_is_still_admissible(self):
        """A v2-built candidate is not a worse candidate; it simply cannot be PROVEN.

        It must still say v2 truthfully. The builder is a provenance claim, so it is
        admissible only while the signed result reports the same builder -- which is
        why this pairs the declaration with a v2 evidence rather than relabelling the
        v3 one.
        """
        result = self.write(candidate(build_definition={"executor_version": "test-pr-v2"}),
                            evidence_value=evidence(executor_version="test-pr-v2"))
        self.assertEqual(result["verdict"]["admission"], "ACCEPT", result["verdict"])
        self.assertFalse(result["deployability"]["deployable_artifact_established"])

    def test_a_builder_that_was_never_staged_is_refused(self):
        self.rejected(self.write(candidate(build_definition={"executor_version": "test-pr-v9"})),
                      "candidate_build_profile")


if __name__ == "__main__":
    unittest.main()
