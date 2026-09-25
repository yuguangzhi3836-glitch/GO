"""Local contract tests. Ephemeral keys below are not registered identities."""
import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from acceptance_gate import Refusal, c13_admission, c14_admission
from ai_acceptance_host import AIAdmissionHost, AIRegistration
import c13_attestation as c13


def registration(key, actor, principal, role):
    public = key.public_key()
    der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    pem = public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return AIRegistration(actor, principal, role, "development" if role == "C13" else "runtime",
                          pem, hashlib.sha256(der).hexdigest())


class AIHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.reviewer = registration(self.key, "test-c13-ai", "test-dev-review-principal", "C13")
        self.runner = registration(ed25519.Ed25519PrivateKey.generate(), "test-c14-ai", "test-runtime-review-principal", "C14")
        self.request = {"candidate_sha": c13.CANDIDATE, "application_tree": c13.TREE,
                        "test_scope_sha256": c13.SCOPE}

    def host(self, reviewer=None, runner=None):
        return AIAdmissionHost("test-implementation", reviewer or self.reviewer, self.root,
                               b"synthetic artifact fixture", runner)

    def signed_record(self, key=None):
        unsigned = {"contract": "GO_C13_INDEPENDENT_VERDICT_V1", **self.request,
                    "artifact_sha256": c13.ARTIFACT_SHA256, "run_id": c13.RUN_ID,
                    "artifact_id": c13.ARTIFACT_ID, "junit_tests": 61, "junit_failures": 0,
                    "pg_cases": 10, "pg_failures": 0, "reviewer_id": self.reviewer.actor_id,
                    "reviewer_independent": True, "verdict": "PASS_SCOPED",
                    "issued_at": "2026-09-25T01:00:00Z"}
        signature = (key or self.key).sign(c13.canonical(unsigned), ec.ECDSA(hashes.SHA256()))
        return c13.canonical({**unsigned, "signature": {"algorithm": "ECDSA_P256_SHA256",
                             "key_fingerprint_sha256": self.reviewer.key_fingerprint_sha256,
                             "der_base64": base64.b64encode(signature).decode()}}) + b"\n"

    def publish_fixture(self, raw):
        digest = hashlib.sha256(raw).hexdigest()
        (self.root / (digest + ".json")).write_bytes(raw)
        return "sha256:" + digest

    def test_c13_qualification_does_not_require_runtime_runner(self):
        host = self.host()
        result = c13_admission(self.request, host)
        self.assertEqual(result["runner_id"], self.reviewer.actor_id)
        with self.assertRaisesRegex(Refusal, "ai_registration_missing"):
            host.qualify_actor("C14", c13.CANDIDATE)

    def test_human_wrong_side_role_and_unpinned_key_rejected(self):
        for changes in ({"kind": "human"}, {"side": "runtime"}, {"role": "C14"},
                        {"key_fingerprint_sha256": "0" * 64}, {"principal_id": ""}):
            with self.subTest(changes=changes), self.assertRaises(Refusal):
                self.host(reviewer=replace(self.reviewer, **changes))
        with self.assertRaisesRegex(Refusal, "key_binding"):
            self.host(reviewer=registration(ec.generate_private_key(ec.SECP384R1()), "a", "b", "C13"))

    def test_separate_names_with_same_principal_rejected(self):
        with self.assertRaisesRegex(Refusal, "not_independent"):
            self.host(reviewer=replace(self.reviewer, principal_id="test-implementation"))
        for changes in ({"principal_id": self.reviewer.principal_id},
                        {"principal_id": "test-implementation"}, {"actor_id": self.reviewer.actor_id}):
            with self.subTest(changes=changes), self.assertRaisesRegex(Refusal, "not_independent"):
                self.host(runner=replace(self.runner, **changes))

    def test_exact_readback_signature_and_c14_binding(self):
        raw = self.signed_record()
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
        reference = self.publish_fixture(self.signed_record())
        with self.assertRaisesRegex(Refusal, "c13_artifact_integrity"):
            self.host().verify_c13_evidence(reference)

    def test_wrong_signer_and_mutated_verdict_rejected(self):
        bad_signature = self.signed_record(ec.generate_private_key(ec.SECP256R1()))
        record = json.loads(self.signed_record())
        record["issued_at"] = "2026-09-25T02:00:00Z"
        for raw in (bad_signature, c13.canonical(record) + b"\n"):
            reference = self.publish_fixture(raw)
            with patch.object(c13, "inspect_artifact"), self.assertRaisesRegex(Refusal, "c13_signature"):
                self.host().verify_c13_evidence(reference)

    def test_digest_substitution_missing_reference_and_symlink_rejected(self):
        reference = self.publish_fixture(self.signed_record())
        target = self.root / (reference[7:] + ".json")
        target.write_bytes(b"different bytes")
        with self.assertRaisesRegex(Refusal, "c13_content_digest"):
            self.host().verify_c13_evidence(reference)
        target.unlink()
        with self.assertRaisesRegex(Refusal, "c13_verdict_readback"):
            self.host().verify_c13_evidence(reference)
        other = self.root / "other"
        other.write_bytes(self.signed_record())
        target.symlink_to(other)
        with self.assertRaisesRegex(Refusal, "c13_verdict_readback"):
            self.host().verify_c13_evidence(reference)
        for reference in ("../verdict.json", "https://example.invalid/verdict", "sha256:" + "A" * 64):
            with self.subTest(reference=reference), self.assertRaisesRegex(Refusal, "c13_content_reference"):
                self.host().verify_c13_evidence(reference)


if __name__ == "__main__":
    unittest.main()
