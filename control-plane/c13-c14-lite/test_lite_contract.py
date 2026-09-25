"""Contracts, execution identity, GitHub run/artifact identity and the reviewer.

No network, no Git, no live host: every payload here is a synthetic literal.
"""
from __future__ import annotations

import pathlib
import sys
import unittest
from datetime import timedelta

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_ai_reviewer  # noqa: E402
import lite_bundle  # noqa: E402
import lite_candidate  # noqa: E402
import lite_canonical  # noqa: E402
import lite_errors  # noqa: E402
import lite_execution_record  # noqa: E402
import lite_fixtures as fx  # noqa: E402
import lite_github_run  # noqa: E402
import lite_identity  # noqa: E402


class CanonicalTests(unittest.TestCase):
    def test_canonical_is_key_order_independent(self):
        self.assertEqual(lite_canonical.digest({"b": 1, "a": 2}), lite_canonical.digest({"a": 2, "b": 1}))

    def test_canonical_rejects_nan(self):
        with self.assertRaises(ValueError):
            lite_canonical.canonical({"a": float("nan")})

    def test_parse_rejects_duplicate_keys(self):
        with self.assertRaises(ValueError):
            lite_canonical.parse_json('{"a":1,"a":2}')

    def test_digest_bytes_is_plain_sha256(self):
        self.assertEqual(lite_canonical.digest_bytes(b"abc"), lite_canonical.digest_bytes(b"abc"))
        self.assertNotEqual(lite_canonical.digest_bytes(b"abc"), lite_canonical.digest_bytes(b"abd"))


class CandidateContractTests(unittest.TestCase):
    def test_valid_contract_round_trips(self):
        contract = fx.contract("c14")
        lite_candidate.validate(contract)
        self.assertEqual(contract["cell_id"], "C14")

    def test_extra_field_is_rejected(self):
        contract = fx.contract("c14")
        contract["surprise"] = 1
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_candidate.validate(contract)
        self.assertEqual(ctx.exception.reason, "candidate_field_set_mismatch")

    def test_missing_task_reference_is_rejected(self):
        contract = fx.contract("c14")
        contract["issue_number"] = None
        contract["ledger_reference"] = None
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_candidate.validate(contract)
        self.assertEqual(ctx.exception.reason, "candidate_task_reference_missing")

    def test_expired_request_is_rejected(self):
        contract = fx.contract("c14")
        # Derived from the contract's own expiry, so the test cannot rot when the
        # default validity window or the wall clock changes.
        late = fx.just_after_expiry(contract)
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_candidate.validate(contract, now=late)
        self.assertEqual(ctx.exception.reason, "candidate_request_expired")

    def test_a_freshly_built_contract_is_not_expired(self):
        """The bug this guards: a frozen fixture default makes every contract expire
        once wall-clock passes it, and the whole suite fails for the wrong reason."""
        contract = fx.contract("c14")
        lite_candidate.validate(contract)  # no explicit ``now``: uses the real clock

    def test_binding_against_dispatch_input(self):
        contract = fx.contract("c13")
        lite_candidate.check_binding(
            contract,
            expected_candidate_sha=fx.CANDIDATE_SHA,
            expected_application_tree=fx.APPLICATION_TREE,
            expected_cell_id="C13",
            expected_task_id=fx.C13_TASK,
            expected_issue_number=fx.ISSUE_NUMBER,
            expected_request_id=fx.REQUEST_ID,
            now=fx.NOW,
        )
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_candidate.check_binding(
                contract,
                expected_candidate_sha=fx.CANDIDATE_SHA,
                expected_application_tree=fx.APPLICATION_TREE,
                expected_cell_id="C13",
                expected_task_id="C13-some-other-task",
                now=fx.NOW,
            )
        self.assertEqual(ctx.exception.reason, "task_id_mismatch")

    def test_ledger_reference_cell_must_match(self):
        contract = fx.contract("c13")
        contract["ledger_reference"] = dict(contract["ledger_reference"], cell_id="C14")
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_candidate.validate(contract, now=fx.NOW)
        self.assertEqual(ctx.exception.reason, "candidate_ledger_cell_mismatch")


class ExecutionIdentityTests(unittest.TestCase):
    def base(self):
        return {
            "implementation_execution_id": "impl-1",
            "c13_execution_id": "c13-1",
            "c14_execution_id": "c14-1",
            "c13_github_run_id": "1",
            "c14_github_run_id": "2",
            "c13_nonce": "nonce-c13-000000001",
            "c14_nonce": "nonce-c14-000000001",
        }

    def test_distinct_identities_pass(self):
        self.assertTrue(lite_identity.check(self.base()).ok)

    def test_each_collision_is_reported(self):
        cases = {
            "implementation_execution_id": "c13-1",
            "c13_execution_id": "c14-1",
            "c13_github_run_id": "2",
            "c13_nonce": "nonce-c14-000000001",
        }
        expected = {
            "implementation_execution_id": "implementation_equals_c13_execution",
            "c13_execution_id": "c13_equals_c14_execution",
            "c13_github_run_id": "c13_run_equals_c14_run",
            "c13_nonce": "c13_nonce_equals_c14_nonce",
        }
        for field, value in cases.items():
            identities = self.base()
            identities[field] = value
            result = lite_identity.check(identities)
            self.assertFalse(result.ok, field)
            self.assertIn(expected[field], result.reasons, field)

    def test_missing_identity_is_reported(self):
        identities = self.base()
        identities["c14_execution_id"] = ""
        result = lite_identity.check(identities)
        self.assertIn("execution_identity_missing", result.reasons)

    def test_require_raises(self):
        identities = self.base()
        identities["c14_execution_id"] = "c13-1"
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_identity.require(identities)
        self.assertEqual(ctx.exception.reason, "execution_independence_violation")


class ExecutionRecordTests(unittest.TestCase):
    def test_record_is_derived_from_the_sealed_bundle(self):
        round_ = fx.make_round()
        record = lite_execution_record.build(
            round_["c13_bundle"],
            artifact={"name": "c13c14-lite-c13-" + fx.CANDIDATE_SHA, "id": 7, "digest": "sha256:" + "c" * 64},
            evidence_path="evidence/c13_bundle.json",
        )
        self.assertEqual(record["root_hash"], round_["c13_bundle"][lite_bundle.C13_ROOT_FIELD])
        self.assertIs(record["authorizes_any_action"], False)

    def test_record_cannot_authorise(self):
        round_ = fx.make_round()
        record = lite_execution_record.build(
            round_["c13_bundle"],
            artifact={"name": "n", "id": 7, "digest": "sha256:" + "c" * 64},
            evidence_path="evidence/c13_bundle.json",
        )
        record["authorizes_any_action"] = True
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_execution_record.validate(record)
        self.assertEqual(ctx.exception.reason, "authorizes_any_action_must_be_false")


class GitHubRunIdentityTests(unittest.TestCase):
    def run_payload(self, **overrides):
        payload = {
            "id": 900001,
            "status": "completed",
            "conclusion": "success",
            "head_sha": fx.CANDIDATE_SHA,
            "path": fx.C14_WORKFLOW,
        }
        payload.update(overrides)
        return payload

    def artifact_payload(self, digest, **overrides):
        payload = {
            "name": lite_github_run.expected_artifact_name("c14", fx.CANDIDATE_SHA),
            "digest": digest,
            "expired": False,
            "workflow_run": {"id": 900001},
        }
        payload.update(overrides)
        return payload

    def test_matching_run_and_artifact_pass(self):
        lite_github_run.assert_run(self.run_payload(), run_id=900001, head_sha=fx.CANDIDATE_SHA, workflow_path=fx.C14_WORKFLOW)
        raw = b"synthetic artifact zip bytes"
        digest = lite_github_run.local_digest(raw)
        lite_github_run.assert_artifact(self.artifact_payload(digest), run_id=900001, name=lite_github_run.expected_artifact_name("c14", fx.CANDIDATE_SHA), digest=digest)
        lite_github_run.assert_downloaded_bytes(raw, digest=digest)

    def test_run_conclusion_and_identity_are_checked(self):
        with self.assertRaises(lite_errors.Reject):
            lite_github_run.assert_run(self.run_payload(conclusion="failure"), run_id=900001, head_sha=fx.CANDIDATE_SHA, workflow_path=fx.C14_WORKFLOW)
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_github_run.assert_run(self.run_payload(head_sha="0" * 40), run_id=900001, head_sha=fx.CANDIDATE_SHA, workflow_path=fx.C14_WORKFLOW)
        self.assertEqual(ctx.exception.reason, "run_head_sha_mismatch")
        with self.assertRaises(lite_errors.Reject):
            lite_github_run.assert_run(self.run_payload(path=".github/workflows/other.yml"), run_id=900001, head_sha=fx.CANDIDATE_SHA, workflow_path=fx.C14_WORKFLOW)

    def test_artifact_tampering_is_checked(self):
        digest = "sha256:" + "d" * 64
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_github_run.assert_artifact(self.artifact_payload(digest, workflow_run={"id": 1}), run_id=900001, name=lite_github_run.expected_artifact_name("c14", fx.CANDIDATE_SHA), digest=digest)
        self.assertEqual(ctx.exception.reason, "artifact_run_identity_mismatch")
        with self.assertRaises(lite_errors.Reject):
            lite_github_run.assert_artifact(self.artifact_payload(digest, expired=True), run_id=900001, name=lite_github_run.expected_artifact_name("c14", fx.CANDIDATE_SHA), digest=digest)
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_github_run.assert_artifact(self.artifact_payload(digest), run_id=900001, name=lite_github_run.expected_artifact_name("c13", fx.CANDIDATE_SHA), digest=digest)
        self.assertEqual(ctx.exception.reason, "artifact_name_mismatch")

    def test_downloaded_bytes_are_rehashed(self):
        raw = b"synthetic artifact zip bytes"
        digest = lite_github_run.local_digest(raw)
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_github_run.assert_downloaded_bytes(b"replaced bytes", digest=digest)
        self.assertEqual(ctx.exception.reason, "artifact_bytes_digest_mismatch")


class AIReviewerTests(unittest.TestCase):
    def facts(self, role="c14"):
        return fx.role_facts(role)

    def test_stub_is_labelled_and_deterministic(self):
        first = lite_ai_reviewer.run("c14", self.facts("c14"), stub=True)
        second = lite_ai_reviewer.run("c14", self.facts("c14"), stub=True)
        self.assertEqual(first["ai_execution_id"], second["ai_execution_id"])
        self.assertEqual(first["ai_provider"], lite_ai_reviewer.STUB_PROVIDER)
        self.assertIn("STUB", first["opinion"]["summary"])

    def test_prompt_and_input_hashes_are_stable(self):
        facts = self.facts("c13")
        outcome = lite_ai_reviewer.run("c13", facts, stub=True)
        prompt = lite_ai_reviewer.build_prompt("c13", facts)
        self.assertEqual(outcome["prompt_sha256"], lite_canonical.digest_bytes(prompt.encode("utf-8")))
        self.assertEqual(outcome["input_sha256"], lite_canonical.digest(facts))

    def test_opinion_candidate_must_be_the_frozen_one(self):
        opinion = fx.opinion("c14", candidate_sha="0" * 40)
        with self.assertRaises(lite_ai_reviewer.ReviewUnavailable) as ctx:
            lite_ai_reviewer.validate_opinion("c14", opinion, fx.CANDIDATE_SHA)
        self.assertEqual(ctx.exception.verdict, lite_errors.BLOCKED)

    def test_missing_api_key_is_a_blocked_not_a_failure(self):
        with self.assertRaises(lite_ai_reviewer.ReviewUnavailable) as ctx:
            lite_ai_reviewer.run("c14", self.facts("c14"), api_key=None)
        self.assertEqual(ctx.exception.verdict, lite_errors.BLOCKED)
        self.assertEqual(ctx.exception.failure_class, "AI_PROVIDER_FAILURE")

    def test_quota_exhaustion_is_classified_as_quota(self):
        self.assertEqual(
            lite_errors.classify_ai_failure(429, "You have no credits remaining. Add credits to continue."),
            "AI_QUOTA_EXHAUSTED",
        )
        self.assertEqual(lite_errors.classify_ai_failure(None, "insufficient_quota"), "AI_QUOTA_EXHAUSTED")
        self.assertEqual(lite_errors.classify_ai_failure(None, "", "connection reset"), "INFRA_FAILURE")
        self.assertEqual(lite_errors.classify_ai_failure(500, ""), "AI_PROVIDER_FAILURE")

    def test_blocked_outcome_keeps_identity_and_is_never_a_pass(self):
        outcome = lite_ai_reviewer.blocked_outcome("c14", self.facts("c14"), "AI_QUOTA_EXHAUSTED", "no credits")
        self.assertEqual(outcome["verdict"], lite_errors.BLOCKED)
        self.assertEqual(outcome["failure_class"], "AI_QUOTA_EXHAUSTED")
        self.assertIsNone(outcome["opinion"])
        self.assertIsNotNone(outcome["prompt_sha256"])


class FailureClassPolicyTests(unittest.TestCase):
    def test_quota_can_only_be_blocked(self):
        self.assertEqual(lite_errors.FAILURE_CLASS_VERDICT["AI_QUOTA_EXHAUSTED"], "BLOCKED")
        self.assertEqual(lite_errors.FAILURE_CLASS_VERDICT["INFRA_FAILURE"], "BLOCKED")
        self.assertEqual(lite_errors.FAILURE_CLASS_VERDICT["QUALITY_FAIL"], "FAIL")

    def test_bundle_rejects_quota_with_pass_verdict(self):
        round_ = fx.make_round()
        bundle = dict(round_["c14_bundle"])
        bundle["failure_class"] = "AI_QUOTA_EXHAUSTED"
        bundle["verdict"] = "PASS_SCOPED"
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_bundle.validate_c14(bundle)
        self.assertEqual(ctx.exception.reason, "bundle_pass_with_failure_class")

    def test_bundle_rejects_quota_with_blocked_verdict_only_when_consistent(self):
        round_ = fx.make_round()
        bundle = dict(round_["c14_bundle"])
        bundle["failure_class"] = "AI_QUOTA_EXHAUSTED"
        bundle["verdict"] = "BLOCKED"
        # A well-formed BLOCKED record is allowed; it simply never unlocks C13.
        lite_bundle.seal(bundle)
        self.assertEqual(bundle["verdict"], "BLOCKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
