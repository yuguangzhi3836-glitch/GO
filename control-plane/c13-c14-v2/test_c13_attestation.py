import json
import unittest
from unittest.mock import patch

from c13_attestation import (ARTIFACT_ID, ARTIFACT_SHA256, CANDIDATE, RUN_ID,
                             SCOPE, TREE, Refusal, canonical, verify)


class C13AttestationTests(unittest.TestCase):
    def make_record(self):
        record = {"contract": "GO_C13_INDEPENDENT_OPINION_V2", "candidate_sha": CANDIDATE,
                  "application_tree": TREE, "test_scope_sha256": SCOPE,
                  "artifact_sha256": ARTIFACT_SHA256, "run_id": RUN_ID,
                  "artifact_id": ARTIFACT_ID, "junit_tests": 61, "junit_failures": 0,
                  "pg_cases": 10, "pg_failures": 0, "reviewer_id": "independent-reviewer",
                  "review_execution_id": "independent-ai-session",
                  "review_reference": "test-only://reviews/1", "opinion": "Synthetic scoped review.",
                  "reviewer_independent": True, "verdict": "PASS_SCOPED",
                  "issued_at": "2026-09-24T16:00:00Z"}
        return canonical(record) + b"\n"

    def check(self, raw, artifact=b"synthetic", reviewer="independent-reviewer"):
        return verify(raw, artifact, reviewer, "independent-ai-session")

    def test_unsigned_opinion_does_not_require_crypto_identity(self):
        with patch("c13_attestation.inspect_artifact") as inspect:
            result = self.check(self.make_record())
        self.assertTrue(result["verified"])
        self.assertEqual(result["actor_id"], "independent-reviewer")
        inspect.assert_called_once_with(b"synthetic")

    def test_missing_real_artifact_fails_closed(self):
        with self.assertRaisesRegex(Refusal, "c13_artifact_integrity"):
            self.check(self.make_record())

    def test_untrusted_identity_and_tampering_refused(self):
        raw = self.make_record()
        with self.assertRaisesRegex(Refusal, "c13_reviewer"):
            self.check(raw, reviewer="other-reviewer")
        tampered = json.loads(raw)
        tampered["candidate_sha"] = "a" * 40
        with self.assertRaisesRegex(Refusal, "c13_fixed_binding"):
            self.check(canonical(tampered) + b"\n")
        with self.assertRaisesRegex(Refusal, "c13_record_schema"):
            self.check(json.dumps(json.loads(raw)).encode() + b"\n")

    def test_green_ci_counts_do_not_replace_opinion(self):
        record = json.loads(self.make_record())
        record["opinion"] = ""
        with self.assertRaisesRegex(Refusal, "c13_review_opinion"):
            self.check(canonical(record) + b"\n")


if __name__ == "__main__":
    unittest.main()
