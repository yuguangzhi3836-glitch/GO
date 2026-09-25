"""Synthetic independent AI opinions; no reviewer keys or signatures."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acceptance_gate import Refusal, c13_admission, c14_admission
from ai_acceptance_host import AIAdmissionHost, AIRegistration
import c13_attestation as c13


def registration(actor, principal, role):
    return AIRegistration(actor, principal, role, "development" if role == "C13" else "runtime")


class AIHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reviewer = registration("test-c13-ai", "test-dev-review-principal", "C13")
        self.runner = registration("test-c14-ai", "test-runtime-review-principal", "C14")
        self.request = {"candidate_sha": c13.CANDIDATE, "application_tree": c13.TREE,
                        "test_scope_sha256": c13.SCOPE}

    def host(self, reviewer=None, runner=None):
        return AIAdmissionHost("test-implementation", reviewer or self.reviewer, self.root,
                               b"synthetic artifact fixture", runner)

    def opinion_record(self):
        record = {"contract": "GO_C13_INDEPENDENT_OPINION_V2", **self.request,
                  "artifact_sha256": c13.ARTIFACT_SHA256, "run_id": c13.RUN_ID,
                  "artifact_id": c13.ARTIFACT_ID, "junit_tests": 61, "junit_failures": 0,
                  "pg_cases": 10, "pg_failures": 0, "reviewer_id": self.reviewer.actor_id,
                  "review_execution_id": self.reviewer.principal_id,
                  "review_reference": "test-only://reviews/c13/1",
                  "opinion": "Synthetic independent review: fixed scope covered; no deployment authority.",
                  "reviewer_independent": True, "verdict": "PASS_SCOPED",
                  "issued_at": "2026-09-25T01:00:00Z"}
        return c13.canonical(record) + b"\n"

    def publish_fixture(self, raw):
        digest = hashlib.sha256(raw).hexdigest()
        (self.root / (digest + ".json")).write_bytes(raw)
        (self.root / (digest + ".json")).chmod(0o600)
        return "sha256:" + digest

    def test_c13_qualification_does_not_require_runtime_runner(self):
        host = self.host()
        result = c13_admission(self.request, host)
        self.assertEqual(result["runner_id"], self.reviewer.actor_id)
        with self.assertRaisesRegex(Refusal, "ai_registration_missing"):
            host.qualify_actor("C14", c13.CANDIDATE)

    def test_human_wrong_side_role_and_missing_execution_rejected(self):
        for changes in ({"kind": "human"}, {"side": "runtime"}, {"role": "C14"},
                        {"principal_id": ""}):
            with self.subTest(changes=changes), self.assertRaises(Refusal):
                self.host(reviewer=replace(self.reviewer, **changes))

    def test_separate_names_with_same_principal_rejected(self):
        with self.assertRaisesRegex(Refusal, "not_independent"):
            self.host(reviewer=replace(self.reviewer, principal_id="test-implementation"))
        for changes in ({"principal_id": self.reviewer.principal_id},
                        {"principal_id": "test-implementation"}, {"actor_id": self.reviewer.actor_id}):
            with self.subTest(changes=changes), self.assertRaisesRegex(Refusal, "not_independent"):
                self.host(runner=replace(self.runner, **changes))

    def test_unsigned_opinion_readback_and_c14_binding(self):
        raw = self.opinion_record()
        reference = self.publish_fixture(raw)
        # This test isolates the trust/readback adapter. It does not replace
        # artifact inspection in production, or assert a real C13/C14 PASS.
        with patch.object(c13, "inspect_artifact") as inspect:
            result = c14_admission({**self.request, "c13_evidence_reference": reference},
                                   self.host(runner=self.runner))
        inspect.assert_called_once_with(b"synthetic artifact fixture")
        self.assertEqual(result["c13_evidence_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["runner_id"], self.runner.actor_id)

    def test_invalid_artifact_not_bypassed(self):
        reference = self.publish_fixture(self.opinion_record())
        with self.assertRaisesRegex(Refusal, "c13_artifact_integrity"):
            self.host().verify_c13_evidence(reference)

    def test_unsigned_opinion_requires_trusted_recorder_storage(self):
        reference = self.publish_fixture(self.opinion_record())
        path = self.root / (reference[7:] + ".json")
        path.chmod(0o666)
        with self.assertRaisesRegex(Refusal, "review_file_permissions"):
            self.host().verify_c13_evidence(reference)
        path.chmod(0o600)
        self.root.chmod(0o777)
        with self.assertRaisesRegex(Refusal, "review_store_permissions"):
            self.host().verify_c13_evidence(reference)

    def test_wrong_execution_empty_opinion_and_changed_candidate_rejected(self):
        for change, reason in (({"review_execution_id": "implementation"}, "c13_reviewer"),
                               ({"candidate_sha": "a" * 40}, "c13_fixed_binding"),
                               ({"opinion": " "}, "c13_review_opinion"),
                               ({"review_reference": ""}, "c13_review_opinion")):
            record = json.loads(self.opinion_record())
            record.update(change)
            reference = self.publish_fixture(c13.canonical(record) + b"\n")
            with self.subTest(change=change), patch.object(c13, "inspect_artifact"), self.assertRaisesRegex(Refusal, reason):
                self.host().verify_c13_evidence(reference)

    def test_digest_substitution_missing_reference_and_symlink_rejected(self):
        reference = self.publish_fixture(self.opinion_record())
        target = self.root / (reference[7:] + ".json")
        target.write_bytes(b"different bytes")
        with self.assertRaisesRegex(Refusal, "c13_content_digest"):
            self.host().verify_c13_evidence(reference)
        target.unlink()
        with self.assertRaisesRegex(Refusal, "c13_verdict_readback"):
            self.host().verify_c13_evidence(reference)
        other = self.root / "other"
        other.write_bytes(self.opinion_record())
        target.symlink_to(other)
        with self.assertRaisesRegex(Refusal, "c13_verdict_readback"):
            self.host().verify_c13_evidence(reference)
        for reference in ("../verdict.json", "https://example.invalid/verdict", "sha256:" + "A" * 64):
            with self.subTest(reference=reference), self.assertRaisesRegex(Refusal, "c13_content_reference"):
                self.host().verify_c13_evidence(reference)


if __name__ == "__main__":
    unittest.main()
