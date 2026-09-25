"""Unsigned AI opinions plus synthetic machine bus; no real C14 conclusion."""
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from acceptance_gate import Refusal
from ai_acceptance_host import AIAdmissionHost, AIReviewGroup
from c14_isolated_runner import execute
from c14_review import conclude
from house_bridge import canonical, digest, iso, issue, receive_evidence
from test_c14_isolated_runner import PINNED_REQUEST, RunnerHost


class C14ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.review_host = AIAdmissionHost("implementation-run",
            AIReviewGroup("c13-ai", "c13-run", "C13", "development"), self.root, b"",
            AIReviewGroup("hk-c14", "c14-run", "C14", "runtime"))
        self.host = RunnerHost()
        for name in ("read_review_opinion", "c14_review_identity", "qualify_actor"):
            setattr(self.host, name, getattr(self.review_host, name))
        self.task = issue(PINNED_REQUEST, "C14", 100, self.host)

    def complete(self):
        execute(self.task, 101, self.host)
        self.receipt = receive_evidence(self.task, 101, self.host)["receipt"]

    def record(self):
        return {"contract": "GO_C14_INDEPENDENT_OPINION_V1", "role": "C14",
                "reviewer_id": "hk-c14", "review_execution_id": "c14-run",
                "issued_at": iso(102), "opinion": "Synthetic independent scoped opinion; no release authority.",
                "review_reference": "test-only://c14-review/1", "verdict": "PASS_SCOPED",
                **{key: self.receipt[key] for key in ("candidate_sha", "application_tree",
                    "test_scope_sha256", "task_id", "nonce", "evidence_sha256")},
                "receipt_sha256": digest(canonical(self.receipt) + b"\n")}

    def publish(self, record):
        raw = canonical(record) + b"\n"
        fingerprint = digest(raw)
        path = self.root / (fingerprint + ".json")
        path.write_bytes(raw)
        path.chmod(0o600)
        return "sha256:" + fingerprint

    def test_unsigned_independent_opinion_concludes_without_ai_keys(self):
        self.complete()
        record = self.record()
        self.assertNotIn("signature", record)
        result = conclude(self.task, 102, self.host, self.publish(record))
        self.assertEqual(result["verdict"], "PASS_SCOPED")
        self.assertFalse(result["authorizes_any_action"])

    def test_green_runtime_tests_without_opinion_are_not_c14_pass(self):
        self.complete()
        with self.assertRaisesRegex(Refusal, "c13_verdict_readback"):
            conclude(self.task, 102, self.host, "sha256:" + "0" * 64)

    def test_missing_or_mismatched_review_cannot_be_substituted(self):
        self.complete()
        for key, value in (("review_execution_id", "implementation-run"),
                           ("candidate_sha", "a" * 40), ("test_scope_sha256", "a" * 64),
                           ("evidence_sha256", "b" * 64), ("receipt_sha256", "c" * 64),
                           ("role", "C13"), ("task_id", "other-task")):
            record = self.record()
            record[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(Refusal, "c14_review_binding"):
                conclude(self.task, 102, self.host, self.publish(record))

    def test_empty_or_future_review_is_refused(self):
        self.complete()
        for change, reason in (({"opinion": " "}, "c14_review_opinion"),
                               ({"issued_at": iso(103)}, "c14_review_time"),
                               ({"issued_at": iso(100)}, "c14_review_time")):
            record = self.record() | change
            with self.subTest(change=change), self.assertRaisesRegex(Refusal, reason):
                conclude(self.task, 102, self.host, self.publish(record))

    def test_ai_rejection_overrides_green_technical_results(self):
        self.complete()
        for verdict in ("FAIL", "BLOCKED"):
            result = conclude(self.task, 102, self.host, self.publish(self.record() | {"verdict": verdict}))
            self.assertEqual(result["verdict"], verdict)
            self.assertFalse(result["authorizes_any_action"])

    def test_ai_pass_cannot_override_failed_runtime_test(self):
        original = self.host.run_fixed_isolated_suite
        def failing(*args):
            run = original(*args)
            root = ET.fromstring(run["junit"])
            suite = root.find("testsuite")
            suite.set("failures", "1")
            ET.SubElement(suite.find("testcase"), "failure")
            return run | {"junit": ET.tostring(root)}
        self.host.run_fixed_isolated_suite = failing
        self.complete()
        with self.assertRaisesRegex(Refusal, "c14_review_contradicts_tests"):
            conclude(self.task, 102, self.host, self.publish(self.record()))

    def test_unsigned_ai_review_never_bypasses_machine_evidence_authenticity(self):
        self.complete()
        reference = self.publish(self.record())
        key = self.task["task_id"], self.task["nonce"]
        evidence = json.loads(self.host.results[key])
        evidence["signature"] = "forged"
        self.host.results[key] = canonical(evidence) + b"\n"
        with self.assertRaisesRegex(Refusal, "evidence_signature"):
            conclude(self.task, 102, self.host, reference)


if __name__ == "__main__":
    unittest.main()
