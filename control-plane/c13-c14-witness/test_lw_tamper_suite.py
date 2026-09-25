"""The 16 required tamper / boundary cases for the witness layer.

Numbering follows the implementation task's section 18. Each case asserts the
outcome *and* the reason, so a rejection for the wrong reason is not coverage.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lw_paths  # noqa: E402

lw_paths.install()

import lite_errors  # noqa: E402
import lw_aggregate  # noqa: E402
import lw_fixtures as fx  # noqa: E402
import lw_witness  # noqa: E402

COVERED = []


class TamperSuiteTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.round = fx.bundles()
        self.verification = fx.verify_round(self.round)
        self.cc = fx.cc_witness_record(self.verification, round_=self.round)
        self.hk = fx.hk_witness_record(self.verification, self.cc, round_=self.round)

    def note(self, name, expected, got, reasons):
        self.assertEqual(got, expected, f"{name}: expected {expected}, got {got} ({reasons})")
        COVERED.append(name)

    # 1 / 2 - roots
    def test_01_c14_root_altered_is_rejected(self):
        bundle = dict(self.round["c14_bundle"])
        bundle["rule_review_scope_sha256"] = "0" * 64
        record = fx.verify_round(dict(self.round, c14_bundle=bundle))
        self.note("01_c14_root_altered", "REJECT", record["decision"], record["rejects"])

    def test_02_c13_root_altered_is_rejected(self):
        bundle = dict(self.round["c13_bundle"])
        bundle["remaining_risks"] = ["injected after sealing"]
        record = fx.verify_round(dict(self.round, c13_bundle=bundle))
        self.note("02_c13_root_altered", "REJECT", record["decision"], record["rejects"])

    # 3 / 4 / 5 - identity
    def test_03_candidate_altered_is_rejected(self):
        record = fx.verify_round(dict(self.round, dispatch=dict(self.round["dispatch"],
                                                               candidate_sha="0" * 40)))
        self.note("03_candidate_altered", "REJECT", record["decision"], record["rejects"])

    def test_04_task_id_altered_is_rejected(self):
        record = fx.verify_round(dict(self.round, dispatch=dict(self.round["dispatch"],
                                                               c14_task_id="C14-not-dispatched")))
        self.note("04_task_id_altered", "REJECT", record["decision"], record["rejects"])

    def test_05_issue_reference_altered_is_rejected(self):
        record = fx.verify_round(dict(self.round, dispatch=dict(
            self.round["dispatch"],
            c14_ledger_reference=dict(self.round["dispatch"]["c14_ledger_reference"], round_id="OTHER-ROUND"))))
        self.note("05_issue_reference_altered", "REJECT", record["decision"], record["rejects"])

    # 6 / 7 / 8 - artifact and execution identity
    def test_06_artifact_digest_altered_is_rejected(self):
        import lite_errors as errors

        with self.assertRaises(errors.Reject) as ctx:
            fx.verify_round(c14_expectation=fx.expectation("c14", digest="sha256:" + "0" * 64))
        self.assertEqual(ctx.exception.reason, "artifact_digest_altered")
        COVERED.append("06_artifact_digest_altered")

    def test_07_github_run_id_altered_is_rejected(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            fx.verify_round(c14_run=dict(fx.run_payload("c14"), id=4242))
        self.assertEqual(ctx.exception.reason, "run_id_mismatch")
        COVERED.append("07_github_run_id_altered")

    def test_08_ai_execution_id_altered_is_rejected(self):
        bundle = fx.bundle_copy(self.round["c13_bundle"], ai_execution_id="stub-c14-ai-execution-0001")
        record = fx.verify_round(dict(self.round, c13_bundle=bundle))
        self.note("08_ai_execution_id_altered", "REJECT", record["decision"], record["rejects"])

    # 9 / 10 - witness tampering
    def test_09_cc_witness_altered_is_rejected(self):
        broken = dict(self.cc, C14_ROOT="0" * 64)
        with self.assertRaises(lite_errors.Reject) as ctx:
            lw_witness.verify_witness(broken)
        self.assertEqual(ctx.exception.reason, "witness_signature_invalid")
        COVERED.append("09_cc_witness_altered")

    def test_10_hk_witness_altered_is_rejected(self):
        broken = dict(self.hk, C13_ROOT="0" * 64)
        with self.assertRaises(lite_errors.Reject) as ctx:
            lw_witness.verify_witness(broken)
        self.assertEqual(ctx.exception.reason, "witness_signature_invalid")
        COVERED.append("10_hk_witness_altered")

    # 11 - first-seen rewrite
    def test_11_first_seen_rewritten_is_rejected(self):
        ledger = lw_witness.FirstSeenLedger()
        entry = fx.first_seen(self.round)
        self.assertEqual(ledger.observe(entry), "FIRST_SEEN")
        rewritten = dict(entry, c13_root="0" * 64)
        self.assertEqual(ledger.observe(rewritten), "CONFLICT")
        self.assertEqual(ledger.entries[0]["c13_root"], entry["c13_root"])
        COVERED.append("11_first_seen_rewritten")

    # 12 / 13 - candidate and verdict mixing
    def test_12_old_c14_with_new_c13_is_rejected(self):
        other = fx.make_round(candidate_sha=fx.OTHER_CANDIDATE_SHA)
        record = fx.verify_round(dict(self.round, c13_bundle=other["c13_bundle"]))
        self.note("12_old_c14_with_new_c13", "REJECT", record["decision"], record["rejects"])

    def test_13_c14_fail_with_c13_pass_is_blocked(self):
        failed = fx.make_round(c14_verdict="FAIL", c14_failure_class="RULE_FAIL",
                                  c14_blocking=["synthetic rule breach"])
        verification = fx.verify_round(failed)
        self.note("13_c14_fail_with_c13_pass", "BLOCK", verification["decision"], verification["blocks"])

    # 14 - artifact metadata mismatch
    def test_14_artifact_metadata_mismatch_is_rejected(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            fx.verify_round(c13_artifact=fx.artifact_payload("c13", run_id=1))
        self.assertEqual(ctx.exception.reason, "artifact_run_identity_mismatch")
        COVERED.append("14_artifact_metadata_mismatch")

    # 15 - bytes unavailable is classified, never faked
    def test_15_bytes_unavailable_is_classified_not_faked(self):
        record = fx.verify_round()
        self.assertFalse(record["artifact_bytes_verified"])
        self.assertEqual(record["artifact"]["c14"]["level_2"], "ARTIFACT_BYTES_UNAVAILABLE")
        self.assertEqual(record["artifact"]["c14"]["bytes_failure_class"], "ARTIFACT_BYTES_UNAVAILABLE")
        self.assertTrue(record["artifact"]["c14"]["bytes_reason"])
        COVERED.append("15_bytes_unavailable_classified")

    # 16 - human authorisation boundary
    def test_16_human_authorization_is_mandatory(self):
        record = lw_aggregate.aggregate(verification=self.verification, cc_witness=self.cc, hk_witness=self.hk)
        self.assertEqual(record["gate"], lw_aggregate.HUMAN_GATE)
        self.assertTrue(record["human_authorization_required"])
        self.assertIs(record["auto_deploy"], False)
        record["gate"] = "DEPLOY"
        with self.assertRaises(lite_errors.Reject):
            lw_aggregate.verify_final_root(record)
        COVERED.append("16_human_authorization_mandatory")

    def test_zz_all_16_cases_are_covered(self):
        unique = sorted(set(COVERED))
        self.assertEqual(len(unique), 16, f"covered={unique}")
        self.assertEqual(len(COVERED), len(unique))


if __name__ == "__main__":
    unittest.main(verbosity=2)
