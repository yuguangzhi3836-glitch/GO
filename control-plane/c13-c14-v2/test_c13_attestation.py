import base64
import hashlib
import json
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from c13_attestation import (ARTIFACT_ID, ARTIFACT_SHA256, CANDIDATE, RUN_ID,
                             SCOPE, TREE, Refusal, canonical, verify)


class C13AttestationTests(unittest.TestCase):
    def make_record(self, artifact):
        key = ec.generate_private_key(ec.SECP256R1())  # synthetic test key only
        public = key.public_key()
        pem = public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        unsigned = {"contract": "GO_C13_INDEPENDENT_VERDICT_V1", "candidate_sha": CANDIDATE,
                    "application_tree": TREE, "test_scope_sha256": SCOPE,
                    "artifact_sha256": ARTIFACT_SHA256, "run_id": RUN_ID,
                    "artifact_id": ARTIFACT_ID, "junit_tests": 61, "junit_failures": 0,
                    "pg_cases": 10, "pg_failures": 0, "reviewer_id": "independent-reviewer",
                    "reviewer_independent": True, "verdict": "PASS_SCOPED",
                    "issued_at": "2026-09-24T16:00:00Z"}
        sig = key.sign(canonical(unsigned), ec.ECDSA(hashes.SHA256()))
        record = {**unsigned, "signature": {"algorithm": "ECDSA_P256_SHA256",
                   "key_fingerprint_sha256": hashlib.sha256(der).hexdigest(),
                   "der_base64": base64.b64encode(sig).decode()}}
        return canonical(record) + b"\n", pem

    def test_missing_real_artifact_fails_closed(self):
        raw, pem = self.make_record(b"synthetic")
        with self.assertRaisesRegex(Refusal, "c13_artifact_integrity"):
            verify(raw, b"synthetic", pem, "independent-reviewer")

    def test_untrusted_identity_and_tampering_refused(self):
        raw, pem = self.make_record(b"synthetic")
        with self.assertRaisesRegex(Refusal, "c13_reviewer"):
            verify(raw, b"", pem, "other-reviewer")
        tampered = json.loads(raw)
        tampered["candidate_sha"] = "a" * 40
        with self.assertRaisesRegex(Refusal, "c13_fixed_binding"):
            verify(canonical(tampered) + b"\n", b"", pem, "independent-reviewer")
        with self.assertRaisesRegex(Refusal, "c13_record_schema"):
            verify(json.dumps(json.loads(raw)).encode() + b"\n", b"", pem, "independent-reviewer")


if __name__ == "__main__":
    unittest.main()
