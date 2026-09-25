"""Positive path: a complete synthetic C14 -> C13 lifecycle.

This proves the GitHub-level execution chain works end to end. It does **not**
prove that a real AI review happened: every opinion here comes from the labelled
deterministic stub, and no run talks to GitHub.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_aggregate  # noqa: E402
import lite_ai_reviewer  # noqa: E402
import lite_bundle  # noqa: E402
import lite_canonical  # noqa: E402
import lite_chain  # noqa: E402
import lite_errors  # noqa: E402
import lite_fixtures as fx  # noqa: E402


class PositiveRoundTests(unittest.TestCase):
    def test_round_is_accepted(self):
        decision = lite_chain.require(**fx.chain_kwargs())
        self.assertTrue(decision.ok)
        self.assertEqual(decision.decision, "ACCEPT")
        self.assertIsNotNone(decision.final_root)
        self.assertEqual(decision.eligibility["deployment_eligible"], True)
        self.assertIs(decision.eligibility["authorizes_any_action"], False)
        self.assertIs(decision.eligibility["human_authorization_required"], True)

    def test_roots_differ_between_cells(self):
        decision = lite_chain.require(**fx.chain_kwargs())
        self.assertNotEqual(decision.c14_root, decision.c13_root)

    def test_final_root_is_recomputable_and_sensitive(self):
        round_ = fx.make_round()
        decision = lite_chain.require(**fx.chain_kwargs(round_))
        same = lite_aggregate.compute(
            candidate_sha=round_["c14_bundle"]["candidate_sha"],
            application_tree=round_["c14_bundle"]["application_tree"],
            c14_root=round_["c14_bundle"][lite_bundle.C14_ROOT_FIELD],
            c14_verdict="PASS_SCOPED",
            c13_root=round_["c13_bundle"][lite_bundle.C13_ROOT_FIELD],
            c13_verdict="PASS_SCOPED",
            ledger_binding={key: round_["dispatch"][key] for key in (
                "cell_pair", "c14_task_id", "c13_task_id", "issue_number",
                "c14_ledger_reference", "c13_ledger_reference")},
        )
        self.assertEqual(same["FINAL_ROOT"], decision.final_root)

        other_round = fx.make_round(c13_execution_id="stub-c13-ai-execution-0002")
        other = lite_chain.require(**fx.chain_kwargs(other_round))
        self.assertNotEqual(other.final_root, decision.final_root)

    def test_not_applicable_is_a_legal_c14_terminal_state(self):
        round_ = fx.make_round(
            c14_verdict="NOT_APPLICABLE",
            c14_remediation="NOT_REQUIRED",
            c14_not_applicable={
                "review_scope": "synthetic scope with no applicable rule set",
                "basis": "no declared rule set applies to this synthetic candidate",
                "applicable_rule_set": "NONE_DECLARED",
                "applicable_rule_version": "n/a",
                "why_not_applicable": "the synthetic fixture touches no regulated surface",
            },
        )
        decision = lite_chain.require(**fx.chain_kwargs(round_))
        self.assertTrue(decision.ok)
        self.assertEqual(decision.eligibility["deployment_eligible"], True)
        self.assertEqual(decision.eligibility["reason"], "EVIDENCE_ELIGIBLE")

    def test_ai_passes_do_not_label_the_round_as_a_real_review(self):
        decision = lite_chain.require(**fx.chain_kwargs())
        self.assertEqual(decision.notes["ai_provider"]["c14"], lite_ai_reviewer.STUB_PROVIDER)
        self.assertEqual(decision.notes["ai_provider"]["c13"], lite_ai_reviewer.STUB_PROVIDER)

    def test_witness_slots_stay_reserved(self):
        lite_aggregate.require_witness_slots_absent(None, None)
        with self.assertRaises(lite_errors.Reject) as ctx:
            lite_aggregate.require_witness_slots_absent({"signature": "x"}, None)
        self.assertEqual(ctx.exception.reason, "witness_slots_must_stay_reserved_this_round")

    def test_require_raises_when_the_round_is_not_acceptable(self):
        round_ = fx.make_round(c14_verdict="FAIL", c14_failure_class="RULE_FAIL", c14_blocking=["synthetic breach"])
        with self.assertRaises(lite_errors.Block):
            lite_chain.require(**fx.chain_kwargs(round_))


class SyntheticLifecycleTests(unittest.TestCase):
    """Section 35: one complete synthetic lifecycle, both bundles ready for CC."""

    def test_full_lifecycle_produces_two_sealed_bundles(self):
        facts_c14 = fx.role_facts("c14")
        facts_c13 = fx.role_facts("c13")
        # Fresh, separate AI executions: two different providers-ids on purpose.
        c14_outcome = lite_ai_reviewer.run("c14", facts_c14, stub=True)
        c13_outcome = lite_ai_reviewer.run("c13", facts_c13, stub=True)
        self.assertNotEqual(c14_outcome["ai_execution_id"], c13_outcome["ai_execution_id"])

        round_ = fx.make_round(
            c14_execution_id=c14_outcome["ai_execution_id"],
            c13_execution_id=c13_outcome["ai_execution_id"],
            c14_verdict=c14_outcome["verdict"],
            c13_verdict=c13_outcome["verdict"],
        )
        decision = lite_chain.require(**fx.chain_kwargs(round_))

        with tempfile.TemporaryDirectory() as directory:
            sealed = {}
            for role in ("c14", "c13"):
                bundle = round_[f"{role}_bundle"]
                path = pathlib.Path(directory) / f"{role}_bundle.json"
                path.write_bytes(lite_canonical.canonical(bundle))
                sealed[role] = json.loads(path.read_text(encoding="utf-8"))
                lite_bundle.verify_root(sealed[role])
            self.assertEqual(sealed["c14"][lite_bundle.C14_ROOT_FIELD], decision.c14_root)
            self.assertEqual(sealed["c13"][lite_bundle.C13_ROOT_FIELD], decision.c13_root)

        self.assertIs(sealed["c14"]["authorizes_any_action"], False)
        self.assertIs(sealed["c13"]["authorizes_any_action"], False)
        self.assertEqual(sealed["c13"]["c14_prerequisite"]["c14_candidate_sha"], sealed["c13"]["candidate_sha"])

    def test_c14_uses_no_quality_machinery(self):
        """C14 must not have become a second C13: no Docker/PostgreSQL in its record."""
        round_ = fx.make_round()
        c14_keys = set(round_["c14_bundle"])
        for forbidden in ("machine_job", "junit_sha256", "stdout_sha256", "manifest_sha256", "quality_findings"):
            self.assertNotIn(forbidden, c14_keys)

    def test_c13_machine_job_records_the_quality_sandbox(self):
        round_ = fx.make_round()
        machine = round_["c13_bundle"]["machine_job"]
        self.assertEqual(machine["postgres_version"], "18.4")
        self.assertTrue(machine["docker_used"])
        self.assertEqual(machine["junit_sha256"], round_["c13_bundle"]["junit_sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
