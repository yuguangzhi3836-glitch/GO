"""Synthetic contract fixtures only: never formal C14/C13 review evidence."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from runtime import Runtime, RuntimeErrorInvariant
from review_chain import CandidateBinding, ReviewChain
from handoff import ReviewRequest, request_independent_review, verify_review_binding
from lite_bundle import seal


SHA = "a" * 40
TREE = "b" * 40
BINDING = CandidateBinding(SHA, TREE, "synthetic-ci-evidence")


def synthetic_bundle(verdict="PASS_SCOPED"):
    return seal({
        "schema_version": "go.c13c14.lite.c14_bundle.v1", "cell_id": "C14",
        "task_id": "C14-synthetic-rule-review", "issue_number": 285,
        "ledger_reference": {"round_id": "synthetic-round", "cell_id": "C14", "task_id": "C14-synthetic-rule-review"},
        "candidate_sha": SHA, "application_tree": TREE,
        "nonce": "synthetic-c14-nonce-00000001", "rule_review_scope_sha256": "1" * 64,
        "authority_commit": "c" * 40, "rule_input_sha256": "2" * 64,
        "rule_sources": [{"repository_path": "synthetic-rule-source", "git_blob_sha": "d" * 40, "sha256": "3" * 64}],
        "not_applicable": {"review_scope": "synthetic scope", "basis": "synthetic basis",
                           "applicable_rule_set": "synthetic rules", "applicable_rule_version": "synthetic-v1",
                           "why_not_applicable": "synthetic scoped non-applicability"} if verdict == "NOT_APPLICABLE" else None,
        "github_run_id": 1, "github_run_attempt": 1,
        "workflow_ref": "synthetic/c14-rule-compliance.yml", "workflow_sha": "e" * 40,
        "ai_provider": "synthetic", "ai_model": "synthetic-fixture",
        "ai_execution_id": "synthetic-c14-execution", "principal_id": "synthetic-principal",
        "review_execution_id": "synthetic-c14-execution", "prompt_sha256": "4" * 64,
        "input_sha256": "5" * 64, "opinion_sha256": "6" * 64,
        "findings": [], "blocking_issues": ["synthetic refusal"] if verdict in ("FAIL", "BLOCKED") else [],
        "remediation_status": "NOT_REQUIRED", "verdict": verdict, "failure_class": None,
        "decision_origin": "AI_REVIEW", "ai_called": True,
        "issued_at": "2026-09-30T00:00:00Z", "authorizes_any_action": False,
    })


class ReviewChainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "runtime.db"
        self.rt = Runtime(self.path)
        self.chain = ReviewChain(self.rt)

    def tearDown(self):
        self.temp.cleanup()

    def completed_c14(self, bundle=None, *, result=None):
        task_id = self.chain.start_c14("C4", BINDING)
        task = self.rt.claim("C14", worker_id="synthetic-c14-worker")
        self.assertEqual(task.task_id, task_id)
        if result is None:
            result = {"c14_bundle": synthetic_bundle() if bundle is None else bundle}
        self.rt.complete("C14", task_id, worker_id="synthetic-c14-worker", expected_attempt=task.attempts, success=True, result=result)
        return task_id

    def assert_no_c13(self):
        self.assertIsNone(self.rt.claim("C13", worker_id="synthetic-c13-worker"))

    def test_order_is_c14_then_c13_and_reverse_entrypoints_are_removed(self):
        t14 = self.chain.start_c14("C4", BINDING)
        self.assert_no_c13()
        self.assertFalse(hasattr(self.chain, "start_c13"))
        self.assertFalse(hasattr(self.chain, "advance_to_c14"))
        with self.assertRaises(RuntimeErrorInvariant):
            self.chain.advance_to_c13(c14_task_id=t14, binding=BINDING)
        task = self.rt.claim("C14", worker_id="synthetic-c14-worker")
        with self.assertRaises(RuntimeErrorInvariant):
            self.chain.advance_to_c13(c14_task_id=t14, binding=BINDING)
        self.rt.complete("C14", task.task_id, worker_id="synthetic-c14-worker", expected_attempt=task.attempts, success=True,
                         result={"c14_bundle": synthetic_bundle()})
        t13 = self.chain.advance_to_c13(c14_task_id=t14, binding=BINDING)
        queued = self.rt.claim("C13", worker_id="synthetic-c13-worker")
        self.assertEqual(queued.task_id, t13)
        self.assertEqual(queued.payload["c14_prerequisite"]["c14_verdict"], "PASS_SCOPED")
        self.assertTrue(verify_review_binding(queued.payload))

    def test_missing_task_and_direct_c13_request_are_rejected(self):
        with self.assertRaises(RuntimeErrorInvariant):
            self.chain.advance_to_c13(c14_task_id="missing", binding=BINDING)
        with self.assertRaises(RuntimeErrorInvariant):
            request_independent_review(self.rt, ReviewRequest("C4", "C13", SHA, TREE, BINDING.evidence_ref))
        with self.assertRaises(RuntimeErrorInvariant):
            self.chain.start_c14("C13", BINDING)
        self.assert_no_c13()

    def test_bare_pass_is_not_a_sealed_review(self):
        task_id = self.completed_c14(result={"verdict": "PASS"})
        with self.assertRaises(RuntimeErrorInvariant):
            self.chain.advance_to_c13(c14_task_id=task_id, binding=BINDING)
        self.assert_no_c13()

    def test_candidate_tree_and_evidence_reference_cannot_change(self):
        task_id = self.completed_c14()
        for binding in (CandidateBinding("f" * 40, TREE, BINDING.evidence_ref),
                        CandidateBinding(SHA, "f" * 40, BINDING.evidence_ref),
                        CandidateBinding(SHA, TREE, "other-evidence")):
            with self.subTest(binding=binding), self.assertRaises(RuntimeErrorInvariant):
                self.chain.advance_to_c13(c14_task_id=task_id, binding=binding)
        self.assert_no_c13()

    def test_fail_and_blocked_do_not_unlock_c13(self):
        for verdict in ("FAIL", "BLOCKED"):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as temp:
                rt = Runtime(Path(temp)/"r.db")
                chain = ReviewChain(rt)
                task_id = chain.start_c14("C4", BINDING)
                task = rt.claim("C14", worker_id="synthetic-c14")
                rt.complete("C14", task_id, worker_id="synthetic-c14", expected_attempt=task.attempts, success=True,
                            result={"c14_bundle": synthetic_bundle(verdict)})
                with self.assertRaises(RuntimeErrorInvariant):
                    chain.advance_to_c13(c14_task_id=task_id, binding=BINDING)
                self.assertIsNone(rt.claim("C13", worker_id="synthetic-c13"))

    def test_tampered_bundle_and_open_remediation_are_rejected(self):
        for field, value in (("C14_ROOT", "0" * 64), ("remediation_status", "OPEN")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                bundle = synthetic_bundle()
                bundle[field] = value
                rt = Runtime(Path(temp)/"r.db")
                chain = ReviewChain(rt)
                task_id = chain.start_c14("C4", BINDING)
                task = rt.claim("C14", worker_id="synthetic-c14")
                rt.complete("C14", task_id, worker_id="synthetic-c14", expected_attempt=task.attempts, success=True, result={"c14_bundle": bundle})
                with self.assertRaises(RuntimeErrorInvariant):
                    chain.advance_to_c13(c14_task_id=task_id, binding=BINDING)

    def test_resealed_wrong_candidate_or_tree_is_rejected(self):
        for field in ("candidate_sha", "application_tree"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                bundle = synthetic_bundle()
                bundle[field] = "f" * 40
                bundle = seal(bundle)
                rt = Runtime(Path(temp)/"r.db")
                chain = ReviewChain(rt)
                task_id = chain.start_c14("C4", BINDING)
                task = rt.claim("C14", worker_id="synthetic-c14")
                rt.complete("C14", task_id, worker_id="synthetic-c14", expected_attempt=task.attempts, success=True, result={"c14_bundle": bundle})
                with self.assertRaises(RuntimeErrorInvariant):
                    chain.advance_to_c13(c14_task_id=task_id, binding=BINDING)

    def test_not_applicable_requires_the_formal_scope_and_basis_record(self):
        task_id = self.completed_c14(synthetic_bundle("NOT_APPLICABLE"))
        t13 = self.chain.advance_to_c13(c14_task_id=task_id, binding=BINDING)
        self.assertEqual(self.rt.claim("C13", worker_id="synthetic-c13").task_id, t13)
        bad = synthetic_bundle("NOT_APPLICABLE")
        bad["not_applicable"] = None
        with self.assertRaises(ValueError):
            seal(bad)

    def test_restart_and_replay_keep_one_bound_c13_task(self):
        task_id = self.completed_c14()
        t13 = self.chain.advance_to_c13(c14_task_id=task_id, binding=BINDING)
        restarted = Runtime(self.path)
        self.assertEqual(ReviewChain(restarted).advance_to_c13(c14_task_id=task_id, binding=BINDING), t13)
        task = restarted.claim("C13", worker_id="synthetic-c13")
        self.assertTrue(verify_review_binding(task.payload))
        tampered = copy.deepcopy(task.payload)
        tampered["c14_prerequisite"]["c14_root"] = "0" * 64
        self.assertFalse(verify_review_binding(tampered))
        self.assertIsNone(restarted.claim("C13", worker_id="synthetic-second-c13"))

    def test_tampered_completion_evidence_blocks_handoff(self):
        task_id = self.completed_c14()
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE evidence SET body_json='{}' WHERE task_id=? AND event_type='TASK_COMPLETED'", (task_id,))
        with self.assertRaises(RuntimeErrorInvariant):
            self.chain.advance_to_c13(c14_task_id=task_id, binding=BINDING)
        self.assert_no_c13()


if __name__ == "__main__":
    unittest.main()
