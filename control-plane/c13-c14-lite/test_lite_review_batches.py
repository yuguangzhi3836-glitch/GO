"""Offline provider doubles. No credentials, paid calls or formal review PASS."""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import lite_ai_reviewer as ai
import lite_review_batches as batches
import lite_review_pacing as pacing
import lite_chain
import lite_cli
import lite_fixtures as fx
from lite_canonical import canonical, digest, digest_bytes


def facts():
    return {"candidate_sha": "a" * 40, "application_tree": "b" * 40,
            "changed_paths": ["application/one.py", "docs/history.txt"],
            "review_brief": {"body": "Offline test of complete coverage"},
            "rule_sources": [{"text": "Offline authoritative-rule fixture"}],
            "candidate_diff": "diff --git a/application/one.py b/application/one.py\n" +
                "+跨文件付款与幂等\n" * 3000 +
                "diff --git a/docs/history.txt b/docs/history.txt\n" + "+historical evidence\n" * 1500}


def opinion(role, sha, verdict="PASS_SCOPED"):
    result = ai._stub_opinion(role, {"candidate_sha": sha})
    result.update(summary="OFFLINE MOCK provider opinion; no real review", verdict=verdict)
    if role == "c14" and verdict in ("FAIL", "BLOCKED"):
        result.update(blocking_issues=["OFFLINE MOCK blocker"], remediation_status="OPEN")
    return result


class Provider:
    def __init__(self, leaf_verdict="PASS_SCOPED", final_verdict="PASS_SCOPED", fail_part=None,
                 duplicate_id=False, bad_binding=False, bad_json=False, oversized=False):
        self.leaf_verdict, self.final_verdict = leaf_verdict, final_verdict
        self.fail_part, self.duplicate_id, self.bad_binding = fail_part, duplicate_id, bad_binding
        self.bad_json, self.oversized = bad_json, oversized
        self.prompts = []

    def __call__(self, *, prompt, schema, role, **kwargs):
        self.prompts.append(prompt)
        if "part_id" in schema["required"]:
            supplied = json.loads(prompt.split("FROZEN CANDIDATE\n", 1)[1].split("\nPART REVIEW:", 1)[0])
            part = supplied["review_part"]
            if part["part_id"] == self.fail_part:
                raise ai.ReviewUnavailable("AI_QUOTA_EXHAUSTED", "offline quota fixture", http_status=429)
            report = {"part_id": part["part_id"], "content_sha256": part["content_sha256"],
                      "opinion": opinion(role, supplied["candidate_sha"], self.leaf_verdict),
                      "integration_notes": "application/one.py interacts with docs/history.txt; offline fixture"}
            if self.bad_binding:
                report["content_sha256"] = "f" * 64
            if self.oversized:
                report["integration_notes"] = "x" * 5000
            execution_id = "mock-" + part["part_id"]
        else:
            supplied = json.loads(prompt.split("FROZEN CANDIDATE\n", 1)[1].split("\nFINAL WHOLE-CANDIDATE", 1)[0])
            report = opinion(role, supplied["candidate_sha"], self.final_verdict)
            execution_id = "mock-final-fresh"
        text = "{" if self.bad_json else json.dumps(report, ensure_ascii=False)
        payload = {"id": "duplicate" if self.duplicate_id else execution_id,
                   "status": "completed", "output_text": text}
        return payload, text, canonical(payload)


class PartitionedReviewTests(unittest.TestCase):
    def setUp(self):
        self.pacing = patch.object(pacing, "REQUEST_START_GAP_SECONDS", 0.0)
        self.pacing.start()
        self.addCleanup(self.pacing.stop)
        self.budget = patch.object(batches, "MAX_PROMPT_BYTES", 96 * 1024)
        self.budget.start()
        self.addCleanup(self.budget.stop)
        self.facts = facts()

    def run_review(self, provider=None, role="c14", **kwargs):
        with patch.object(ai, "_call_api", side_effect=provider or Provider()):
            return batches.run_partitioned(role, self.facts, model="offline-mock", api_key="not-a-key", timeout=1, **kwargs)

    def test_every_utf8_byte_and_historical_file_is_covered_exactly_once(self):
        plan, prompts = batches.prepare("c14", self.facts)
        self.assertGreater(len(prompts), 1)
        raw = self.facts["candidate_diff"].encode()
        recovered = b""
        for part, prompt in zip(plan["parts"], prompts):
            segment = raw[part["start_byte"]:part["end_byte"]]
            segment.decode("utf-8")
            self.assertEqual(digest_bytes(segment), part["content_sha256"])
            self.assertLessEqual(len(prompt.encode()), batches.MAX_PROMPT_BYTES)
            self.assertIn("docs/history.txt", prompt)
            recovered += segment
        self.assertEqual(recovered, raw)
        self.assertEqual(plan["diff_sha256"], digest_bytes(raw))

    def test_plan_is_deterministic(self):
        self.assertEqual(batches.prepare("c14", self.facts), batches.prepare("c14", copy.deepcopy(self.facts)))

    def test_c14_and_c13_replay_and_fresh_final_id(self):
        for role in ("c14", "c13"):
            with self.subTest(role=role):
                result = self.run_review(role=role)
                batches.verify(result, facts=self.facts)
                self.assertEqual(result["ai_execution_id"], "mock-final-fresh")
                self.assertTrue(result["review_trace"]["complete"])
                self.assertEqual(result["prompt_sha256"], digest_bytes(ai.build_prompt(role, self.facts).encode()))

    def test_full_local_reports_reach_final_prompt(self):
        provider = Provider()
        result = self.run_review(provider)
        final = provider.prompts[-1]
        for record in result["review_trace"]["parts"]:
            self.assertIn(canonical(record["report"]).decode(), final)
            self.assertIn(record["execution_id"], final)

    def test_small_input_keeps_one_request(self):
        small = {"candidate_sha": "a" * 40, "candidate_diff": "short"}
        report = opinion("c14", small["candidate_sha"])
        payload = {"id": "mock-single", "output_text": json.dumps(report)}
        with patch.object(ai, "_call_api", return_value=(payload, json.dumps(report), canonical(payload))) as call:
            result = ai.run("c14", small, api_key="not-a-key")
        self.assertEqual(call.call_count, 1)
        self.assertNotIn("review_trace", result)

    def test_large_input_routes_to_partitioned_mode(self):
        with patch.object(ai, "_call_api", side_effect=Provider()) as call:
            result = ai.run("c14", self.facts, api_key="not-a-key")
        self.assertEqual(result["review_mode"], "partitioned-v1")
        self.assertEqual(call.call_count, len(result["review_trace"]["parts"]) + 1)

    def test_stub_never_calls_provider(self):
        with patch.object(ai, "_call_api") as call:
            result = ai.run("c14", self.facts, stub=True)
        call.assert_not_called()
        self.assertEqual(result["ai_provider"], ai.STUB_PROVIDER)
        self.assertNotIn("review_trace", result)

    def test_local_fail_or_block_cannot_be_overridden(self):
        for verdict in ("FAIL", "BLOCKED"):
            with self.subTest(verdict=verdict), self.assertRaisesRegex(ai.ReviewUnavailable, "ignored_local_blocker") as caught:
                self.run_review(Provider(leaf_verdict=verdict))
            self.assertIsNotNone(caught.exception.review_trace["final"])
            self.assertFalse(caught.exception.review_trace["complete"])

    def test_final_fail_retained_as_model_opinion(self):
        result = self.run_review(Provider(leaf_verdict="FAIL", final_verdict="FAIL"))
        self.assertEqual(result["verdict"], "FAIL")
        batches.verify(result, facts=self.facts)

    def test_quota_failure_retains_completed_wave_and_no_final(self):
        provider = Provider(fail_part="part-0000")
        with self.assertRaises(ai.ReviewUnavailable) as caught:
            self.run_review(provider)
        error = caught.exception
        result = ai.failure_outcome("c14", self.facts, error)
        self.assertEqual(result["failure_class"], "AI_QUOTA_EXHAUSTED")
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertTrue(result["ai_called"])
        self.assertIsNone(result["ai_execution_id"])
        self.assertIsNone(result["review_trace"]["final"])
        self.assertGreater(len(result["review_trace"]["parts"]), 1)
        self.assertIn("response_json", result["review_trace"]["parts"][1])

    def test_preflight_refusal_makes_no_paid_call(self):
        self.facts["review_brief"] = {"body": "x" * batches.MAX_PROMPT_BYTES}
        with patch.object(ai, "_call_api") as call, self.assertRaises(ai.ReviewUnavailable) as caught:
            batches.run_partitioned("c14", self.facts, model="mock", api_key="not-a-key", timeout=1)
        call.assert_not_called()
        self.assertFalse(caught.exception.ai_called)

    def test_part_count_budget_refuses_before_calls(self):
        with patch.object(batches, "MAX_PARTS", 1), patch.object(ai, "_call_api") as call, self.assertRaisesRegex(ai.ReviewUnavailable, "part_count"):
            batches.run_partitioned("c14", self.facts, model="mock", api_key="not-a-key", timeout=1)
        call.assert_not_called()

    def test_duplicate_execution_ids_refused(self):
        with self.assertRaisesRegex(ai.ReviewUnavailable, "duplicate_execution"):
            self.run_review(Provider(duplicate_id=True))

    def test_wrong_part_binding_refused(self):
        with self.assertRaisesRegex(ai.ReviewUnavailable, "binding_mismatch"):
            self.run_review(Provider(bad_binding=True))

    def test_malformed_json_raw_response_survives(self):
        with self.assertRaisesRegex(ai.ReviewUnavailable, "opinion_not_json") as caught:
            self.run_review(Provider(bad_json=True))
        self.assertIn("response_json", caught.exception.review_trace["parts"][0])

    def test_oversized_reports_block_without_truncation(self):
        with self.assertRaisesRegex(ai.ReviewUnavailable, "report_budget") as caught:
            self.run_review(Provider(oversized=True))
        self.assertEqual(len(caught.exception.review_trace["parts"][0]["report"]["integration_notes"]), 5000)

    def test_atomic_progress_checkpoints_are_always_blocked(self):
        snapshots = []
        result = self.run_review(checkpoint=lambda value: snapshots.append(copy.deepcopy(value)))
        self.assertTrue(result["review_trace"]["complete"])
        self.assertGreater(len(snapshots), 2)
        self.assertTrue(all(s["verdict"] == "BLOCKED" and s["opinion"] is None for s in snapshots))
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory, "outcome.json")
            lite_cli._write_review_checkpoint(path, snapshots[-1])
            self.assertEqual(json.loads(path.read_text()), snapshots[-1])
            self.assertFalse(path.with_suffix(".json.checkpoint").exists())

    def test_time_budget_failure_retains_blocked_checkpoint(self):
        snapshots = []
        with patch.object(batches, "MAX_REVIEW_SECONDS", 0), self.assertRaisesRegex(ai.ReviewUnavailable, "time_budget") as caught:
            self.run_review(checkpoint=lambda value: snapshots.append(copy.deepcopy(value)))
        self.assertFalse(caught.exception.review_trace["complete"])
        self.assertTrue(snapshots)
        self.assertEqual(snapshots[-1]["verdict"], "BLOCKED")

    def test_trace_tampering_is_rejected(self):
        original = self.run_review()
        mutations = {
            "missing": lambda t: t["parts"].pop(),
            "duplicate": lambda t: t["parts"].append(copy.deepcopy(t["parts"][0])),
            "reordered": lambda t: t["parts"].reverse(),
            "raw_response": lambda t: t["parts"][0].update(response_json="{}"),
            "opinion": lambda t: t["parts"][0]["report"]["opinion"].update(summary="tampered"),
            "incomplete": lambda t: t.update(complete=False),
            "plan_hash": lambda t: t.update(plan_sha256="0" * 64),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                result = copy.deepcopy(original)
                mutate(result["review_trace"])
                with self.assertRaises(ai.ReviewUnavailable):
                    batches.verify(result, facts=self.facts)

    def test_gap_overlap_and_source_tamper_rejected_even_after_rehash(self):
        original = self.run_review()
        for delta in (-1, 1):
            result = copy.deepcopy(original)
            trace = result["review_trace"]
            trace["plan"]["parts"][1]["start_byte"] += delta
            trace["plan_sha256"] = digest(trace["plan"])
            with self.assertRaisesRegex(ai.ReviewUnavailable, "gap_overlap"):
                batches.verify(result, facts=self.facts)
        changed = copy.deepcopy(self.facts)
        changed["candidate_diff"] += "+omitted source\n"
        with self.assertRaisesRegex(ai.ReviewUnavailable, "plan_replay"):
            batches.verify(original, facts=changed)

    def test_unicode_single_line_can_be_split_without_loss(self):
        self.facts["candidate_diff"] = "diff --git a/large b/large\n+" + "付" * 35000
        plan, _ = batches.prepare("c14", self.facts)
        self.assertEqual(plan["parts"][-1]["end_byte"], len(self.facts["candidate_diff"].encode()))

    def test_invalid_opinion_enum_and_types_refused_locally(self):
        for change in ({"verdict": "PASS"}, {"findings": "none"}, {"summary": None},
                       {"remediation_status": "OPEN"}, {"candidate_sha": "b" * 40}):
            report = opinion("c14", "a" * 40)
            report.update(change)
            with self.subTest(change=change), self.assertRaises(ai.ReviewUnavailable):
                ai.validate_opinion("c14", report, "a" * 40)


class OpinionArtifactTests(unittest.TestCase):
    def test_cli_seal_and_workflow_copy_bind_exact_envelope(self):
        import test_lite_defect_fixes as original_tests
        fixture = original_tests.RuleInputRoundTests()
        with tempfile.TemporaryDirectory() as directory:
            rule_input = fixture._write_rule_input(directory, fx.rule_input_record())
            _, outcome, bundle, root = fixture._seal_a_round(directory, rule_input)
            raw = (root / "outcome.json").read_bytes()
            self.assertEqual(bundle["opinion_sha256"], digest_bytes(raw))
            self.assertNotEqual(bundle["opinion_sha256"], outcome["opinion_sha256"])
            decision = lite_chain.Decision()
            lite_chain._hash_artifacts(decision, {"c14_opinion": raw}, {"c14": bundle})
            self.assertTrue(decision.ok, decision.as_dict())

    def test_seal_refuses_credential_shaped_response_before_publication(self):
        import test_lite_defect_fixes as original_tests
        fixture = original_tests.RuleInputRoundTests()
        with tempfile.TemporaryDirectory() as directory:
            rule_input = fixture._write_rule_input(directory, fx.rule_input_record())
            _, outcome, _, root = fixture._seal_a_round(directory, rule_input)
            outcome["opinion"]["summary"] = "Bearer " + "synthetic" * 5
            outcome["opinion_sha256"] = digest(outcome["opinion"])
            (root / "outcome.json").write_text(json.dumps(outcome))
            args = argparse.Namespace(spec=root / "spec.json", contract=root / "contract.json",
                                      outcome=root / "outcome.json", facts=root / "facts.json")
            with self.assertRaisesRegex(Exception, "secret_shape"):
                lite_cli.cmd_seal(args)

    def envelope_and_bundle(self):
        facts_ = {"candidate_sha": fx.CANDIDATE_SHA}
        outcome = ai.run("c14", facts_, stub=True)
        bundle, _ = fx.build_bundle("c14", opinion_obj=outcome["opinion"])
        for key in ("verdict", "prompt_sha256", "input_sha256", "ai_provider", "ai_model", "ai_execution_id", "failure_class"):
            bundle[key] = outcome[key]
        raw = json.dumps(outcome, indent=2, sort_keys=True).encode() + b"\n"
        bundle["opinion_sha256"] = digest_bytes(raw)
        return outcome, bundle, raw

    def test_actual_workflow_envelope_bytes_are_accepted(self):
        _, bundle, raw = self.envelope_and_bundle()
        decision = lite_chain.Decision()
        lite_chain._hash_artifacts(decision, {"c14_opinion": raw}, {"c14": bundle})
        self.assertTrue(decision.ok, decision.as_dict())

    def test_inner_opinion_digest_does_not_match_workflow_artifact(self):
        outcome, bundle, raw = self.envelope_and_bundle()
        bundle["opinion_sha256"] = outcome["opinion_sha256"]
        decision = lite_chain.Decision()
        lite_chain._hash_artifacts(decision, {"c14_opinion": raw}, {"c14": bundle})
        self.assertIn("artifact_digest_tamper", decision.reasons)

    def test_rehashed_but_inconsistent_envelope_is_rejected(self):
        outcome, bundle, _ = self.envelope_and_bundle()
        outcome["ai_execution_id"] = "different"
        raw = canonical(outcome)
        bundle["opinion_sha256"] = digest_bytes(raw)
        decision = lite_chain.Decision()
        lite_chain._hash_artifacts(decision, {"c14_opinion": raw}, {"c14": bundle})
        self.assertIn("opinion_evidence_invalid", decision.reasons)

    def test_existing_canonical_opinion_artifacts_still_verify(self):
        self.assertTrue(lite_chain.require(**fx.chain_kwargs()).ok)

    def test_seal_requires_original_facts_for_partitioned_opinion(self):
        outcome, _, _ = self.envelope_and_bundle()
        outcome["review_mode"] = "partitioned-v1"
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for name, value in (("spec", {"role": "c14"}), ("contract", {}), ("outcome", outcome)):
                (root / name).write_text(json.dumps(value))
            args = argparse.Namespace(spec=root / "spec", contract=root / "contract", outcome=root / "outcome", facts=None)
            with self.assertRaisesRegex(Exception, "requires_original_facts"):
                lite_cli.cmd_seal(args)


    def test_c13_provider_failure_cannot_get_a_synthetic_sealed_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for name, value in (("spec", {"role": "c13"}), ("contract", {}),
                                ("outcome", {"opinion": None, "verdict": "BLOCKED"})):
                (root / name).write_text(json.dumps(value))
            args = argparse.Namespace(spec=root / "spec", contract=root / "contract", outcome=root / "outcome", facts=None)
            with self.assertRaisesRegex(Exception, "c13_no_provider_opinion_raw_only"):
                lite_cli.cmd_seal(args)


if __name__ == "__main__":
    unittest.main()
