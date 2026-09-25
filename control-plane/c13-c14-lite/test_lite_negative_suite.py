"""The required negative suite: every tamper, mismatch and ineligible state.

Case numbering follows the implementation task's section 23 / 24 so the report can
cite "N/24". Each case asserts both the outcome (REJECT vs BLOCK) and that the
engine actually reached the intended rule — a rejection for the wrong reason is not
counted as coverage.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_bundle  # noqa: E402
import lite_canonical  # noqa: E402
import lite_chain  # noqa: E402
import lite_errors  # noqa: E402
import lite_fixtures as fx  # noqa: E402
import lite_github_run  # noqa: E402
import lite_identity  # noqa: E402

COVERED = []


def reseal(bundle):
    import copy

    clone = copy.deepcopy(bundle)
    root_field = lite_bundle.C14_ROOT_FIELD if clone["cell_id"] == "C14" else lite_bundle.C13_ROOT_FIELD
    clone[root_field] = "0" * 64
    return lite_bundle.seal(clone)


class NegativeSuiteTests(unittest.TestCase):
    maxDiff = None

    def case(self, name, expected, decision=None, **overrides):
        decision = decision or lite_chain.verify_round(**fx.chain_kwargs(**overrides))
        self.assertEqual(
            decision.decision,
            expected,
            f"{name}: expected {expected}, got {decision.decision} reasons={decision.reasons}",
        )
        COVERED.append(name)
        return decision

    def assert_reason(self, decision, reason):
        self.assertIn(reason, decision.reasons, f"expected reason {reason} in {decision.reasons}")

    # --- 1-4: execution and run identity collisions -------------------------
    def test_01_implementation_equals_c13_execution(self):
        decision = self.case("01_impl_equals_c13_execution", "REJECT",
                             implementation_execution_id=fx.make_round()["c13_bundle"]["ai_execution_id"])
        self.assert_reason(decision, "implementation_equals_c13_execution")

    def test_02_implementation_equals_c14_execution(self):
        round_ = fx.make_round()
        decision = self.case("02_impl_equals_c14_execution", "REJECT", round_=round_,
                             implementation_execution_id=round_["c14_bundle"]["ai_execution_id"])
        self.assert_reason(decision, "implementation_equals_c14_execution")

    def test_03_c13_equals_c14_execution(self):
        round_ = fx.make_round()
        round_["c13_bundle"] = reseal(dict(round_["c13_bundle"], ai_execution_id=round_["c14_bundle"]["ai_execution_id"]))
        decision = self.case("03_c13_equals_c14_execution", "REJECT", round_=round_)
        self.assert_reason(decision, "c13_equals_c14_execution")

    def test_04_c13_run_equals_c14_run(self):
        round_ = fx.make_round(c14_run_id=900777, c13_run_id=900777)
        decision = self.case("04_c13_run_equals_c14_run", "REJECT", round_=round_)
        self.assert_reason(decision, "c13_run_equals_c14_run")

    # --- 5-8: sealed-record tampering ---------------------------------------
    def test_05_candidate_sha_tamper(self):
        round_ = fx.make_round()
        round_["c14_bundle"] = reseal(dict(round_["c14_bundle"], candidate_sha=fx.OTHER_CANDIDATE_SHA))
        decision = self.case("05_candidate_sha_tamper", "REJECT", round_=round_)
        self.assert_reason(decision, "opinion_candidate_mismatch")

    def test_06_application_tree_tamper(self):
        round_ = fx.make_round()
        round_["c14_bundle"] = reseal(dict(round_["c14_bundle"], application_tree=fx.seed_sha("other-tree")))
        decision = self.case("06_application_tree_tamper", "REJECT", round_=round_)
        self.assert_reason(decision, "application_tree_tamper")

    def test_07_c14_verdict_tamper(self):
        round_ = fx.make_round()
        # Flipped after sealing, without recomputing the root: the recorded verdict
        # must not be believed.
        round_["c14_bundle"] = dict(round_["c14_bundle"], verdict="BLOCKED", failure_class="RULE_FAIL")
        decision = self.case("07_c14_verdict_tamper", "REJECT", round_=round_)
        self.assert_reason(decision, "root_recompute_mismatch")

    def test_08_c14_findings_tamper(self):
        round_ = fx.make_round()
        findings = list(round_["c14_bundle"]["findings"]) + [{"id": "F-9", "severity": "MINOR", "statement": "injected"}]
        round_["c14_bundle"] = dict(round_["c14_bundle"], findings=findings)
        decision = self.case("08_c14_findings_tamper", "REJECT", round_=round_)
        self.assert_reason(decision, "root_recompute_mismatch")

    # --- 9-14: evidence-byte and identity tampering --------------------------
    def test_09_c13_opinion_tamper(self):
        decision = self.case("09_c13_opinion_tamper", "REJECT",
                             artifacts=dict(fx.make_round()["artifacts"], c13_opinion=b'{"verdict":"PASS_SCOPED"}'))
        self.assert_reason(decision, "artifact_digest_tamper")

    def test_10_junit_digest_tamper(self):
        round_ = fx.make_round()
        decision = self.case("10_junit_digest_tamper", "REJECT", round_=round_,
                             artifacts=dict(round_["artifacts"], junit=b"<testsuite failures='9'/>"))
        self.assert_reason(decision, "artifact_digest_tamper")

    def test_11_stdout_digest_tamper(self):
        round_ = fx.make_round()
        decision = self.case("11_stdout_digest_tamper", "REJECT", round_=round_,
                             artifacts=dict(round_["artifacts"], stdout=b"replaced stdout"))
        self.assert_reason(decision, "artifact_digest_tamper")

    def test_12_manifest_digest_tamper(self):
        round_ = fx.make_round()
        decision = self.case("12_manifest_digest_tamper", "REJECT", round_=round_,
                             artifacts=dict(round_["artifacts"], manifest=b'{"tests":1}'))
        self.assert_reason(decision, "artifact_digest_tamper")

    def test_13_github_run_identity_tamper(self):
        round_ = fx.make_round()
        decision = self.case("13_github_run_identity_tamper", "REJECT", round_=round_,
                             artifacts=dict(round_["artifacts"], c14_opinion=b"tampered"))
        # Independent of the bundle, the API payload itself is asserted.
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_github_run.assert_run(
                {"id": 900001, "status": "completed", "conclusion": "success",
                 "head_sha": fx.OTHER_CANDIDATE_SHA, "path": fx.C14_WORKFLOW},
                run_id=900001, head_sha=fx.CANDIDATE_SHA, workflow_path=fx.C14_WORKFLOW,
            )
        self.assertIn(ctx.exception.reason, ("run_head_sha_mismatch",))
        self.assert_reason(decision, "artifact_digest_tamper")

    def test_14_ai_execution_identity_tamper(self):
        round_ = fx.make_round()
        round_["c13_bundle"] = reseal(dict(round_["c13_bundle"], ai_execution_id="stub-c14-ai-execution-0001"))
        decision = self.case("14_ai_execution_identity_tamper", "REJECT", round_=round_)
        self.assert_reason(decision, "c13_equals_c14_execution")

    # --- 15: mixed candidates -------------------------------------------------
    def test_15_c14_candidate_a_with_c13_candidate_b(self):
        round_ = fx.make_round()
        other = fx.make_round(candidate_sha=fx.OTHER_CANDIDATE_SHA)
        round_["c13_bundle"] = other["c13_bundle"]
        decision = self.case("15_c14_candidate_a_c13_candidate_b", "REJECT", round_=round_)
        self.assertTrue(
            {"c14_candidate_a_c13_candidate_b", "opinion_candidate_mismatch"} & set(decision.reasons),
            decision.reasons,
        )

    def test_15b_prerequisite_from_a_bundle_for_b(self):
        """The dedicated code: a C13 bundle for candidate B carrying A's C14 summary."""
        round_ = fx.make_round()
        other = fx.make_round(candidate_sha=fx.OTHER_CANDIDATE_SHA)
        mixed = dict(other["c13_bundle"], c14_prerequisite=round_["prereq"])
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_bundle.seal(mixed)
        self.assertEqual(ctx.exception.reason, "c14_candidate_a_c13_candidate_b")

    # --- 16-18: prerequisite blocking ----------------------------------------
    def test_16_c14_fail_blocks_c13(self):
        round_ = fx.make_round(c14_verdict="FAIL", c14_failure_class="RULE_FAIL", c14_blocking=["synthetic breach"])
        decision = self.case("16_c14_fail_blocks_c13", "BLOCK", round_=round_)
        self.assert_reason(decision, "c14_verdict_not_admissible")

    def test_17_c14_blocked_blocks_c13(self):
        round_ = fx.make_round(c14_verdict="BLOCKED", c14_failure_class="AI_QUOTA_EXHAUSTED")
        decision = self.case("17_c14_blocked_blocks_c13", "BLOCK", round_=round_)
        self.assert_reason(decision, "c14_verdict_not_admissible")

    def test_18_missing_c14_record_blocks(self):
        round_ = fx.make_round()
        round_["c14_bundle"] = None
        decision = self.case("18_missing_c14_record", "BLOCK", round_=round_)
        self.assert_reason(decision, "c14_record_missing")

    # --- 19-20: NOT_APPLICABLE must be a recorded decision -------------------
    def na_round(self):
        return fx.make_round(
            c14_verdict="NOT_APPLICABLE",
            c14_remediation="NOT_REQUIRED",
            c14_not_applicable={
                "review_scope": "synthetic scope",
                "basis": "synthetic basis",
                "applicable_rule_set": "NONE_DECLARED",
                "applicable_rule_version": "n/a",
                "why_not_applicable": "the synthetic fixture touches no regulated surface",
            },
        )

    def test_19_na_without_scope(self):
        round_ = self.na_round()
        round_["c14_bundle"] = dict(
            round_["c14_bundle"], not_applicable=dict(round_["c14_bundle"]["not_applicable"], review_scope="")
        )
        decision = self.case("19_na_without_scope", "REJECT", round_=round_)
        self.assert_reason(decision, "c14_not_applicable_without_scope")

    def test_20_na_without_basis(self):
        round_ = self.na_round()
        round_["c14_bundle"] = dict(
            round_["c14_bundle"], not_applicable=dict(round_["c14_bundle"]["not_applicable"], basis="")
        )
        decision = self.case("20_na_without_basis", "REJECT", round_=round_)
        self.assert_reason(decision, "c14_not_applicable_without_basis")

    # --- 21-24: identity, expiry and binding ---------------------------------
    def test_21_missing_ai_execution_identity(self):
        direct = lite_identity.check({
            "implementation_execution_id": "impl",
            "c13_execution_id": "",
            "c14_execution_id": "c14",
            "c13_github_run_id": "1",
            "c14_github_run_id": "2",
            "c13_nonce": "n1",
            "c14_nonce": "n2",
        })
        self.assertIn("execution_identity_missing", direct.reasons)
        round_ = fx.make_round()
        round_["c13_bundle"] = dict(round_["c13_bundle"], ai_execution_id="")
        decision = self.case("21_missing_ai_execution_identity", "REJECT", round_=round_)
        self.assertTrue(
            {"root_recompute_mismatch", "bundle_identity_field_missing"} & set(decision.reasons),
            decision.reasons,
        )

    def test_22_expired_request(self):
        round_ = fx.make_round()
        # One second past the round's own expiry: no dependency on a hardcoded instant.
        decision = self.case("22_expired_request", "REJECT", round_=round_,
                             now=fx.just_after_expiry(round_["c13_contract"]))
        self.assert_reason(decision, "candidate_request_expired")

    def test_23_issue_task_binding_mismatch(self):
        round_ = fx.make_round()
        decision = self.case("23_issue_task_binding_mismatch", "REJECT", round_=round_,
                             dispatch=dict(round_["dispatch"], c13_task_id="C13-not-dispatched"))
        self.assert_reason(decision, "task_id_mismatch")

    def test_23b_bundle_task_disagrees_with_its_ledger_reference(self):
        round_ = fx.make_round()
        # Not resealed on purpose: structural validation must refuse it before the
        # root is even recomputed.
        round_["c14_bundle"] = dict(round_["c14_bundle"], task_id="C14-not-in-ledger")
        decision = lite_chain.verify_round(**fx.chain_kwargs(round_))
        self.assertEqual(decision.decision, "REJECT")
        self.assert_reason(decision, "bundle_ledger_task_mismatch")

    def test_24_cell_id_mismatch(self):
        round_ = fx.make_round()
        round_["c13_contract"] = fx.contract("c13", cell_id="C14")
        decision = self.case("24_cell_id_mismatch", "REJECT", round_=round_)
        self.assert_reason(decision, "cell_id_mismatch")

    def test_24b_bundle_claiming_the_other_cell_is_rejected(self):
        """A C13-shaped record claiming ``cell_id = C14`` never validates as either."""
        round_ = fx.make_round()
        round_["c13_bundle"] = dict(round_["c13_bundle"], cell_id="C14")
        decision = lite_chain.verify_round(**fx.chain_kwargs(round_))
        self.assertEqual(decision.decision, "REJECT")
        self.assert_reason(decision, "bundle_field_set_mismatch")

    def test_zz_all_24_cases_are_covered(self):
        unique = sorted(set(COVERED))
        self.assertEqual(len(unique), 24, f"covered={unique}")
        self.assertEqual(len(COVERED), len(unique))


if __name__ == "__main__":
    unittest.main(verbosity=2)
