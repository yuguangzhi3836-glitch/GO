import base64
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

import c14_signer as signer


class FakeBackend:
    def __init__(self): self.key = ec.generate_private_key(ec.SECP256R1())
    def sign(self, data): return self.key.sign(data, ec.ECDSA(hashes.SHA256()))


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
REQUEST = {"candidate_sha": "a" * 40, "application_tree": "b" * 40,
           "verdict": "PASS", "evidence_manifest_sha256": "c" * 64}


def test_p256_receipt_is_canonical_and_verifiable():
    backend = FakeBackend()
    envelope = signer.sign_receipt(REQUEST, backend, issuer="isolated-c14-signer",
                                   now=NOW, receipt_id="test-1")
    signature = base64.urlsafe_b64decode(envelope["signature"] + "==")
    backend.key.public_key().verify(signature, signer.canonical_bytes(envelope["receipt"]),
                                    ec.ECDSA(hashes.SHA256()))
    assert envelope["receipt"]["gate"] == "C14"


@pytest.mark.parametrize("payload", [
    {}, {**REQUEST, "deployment": "hong-kong"}, {**REQUEST, "production": True},
    {**REQUEST, "payment": {"action": "capture"}}, {**REQUEST, "runner": "new"},
    {**REQUEST, "dispatch": "C13"}, {**REQUEST, "secret": "x"},
    {**REQUEST, "candidate_sha": "A" * 40}, {**REQUEST, "verdict": "APPROVE"},
    {**REQUEST, "url": "https://example.invalid"},
])
def test_rejection_matrix(payload):
    with pytest.raises(signer.Rejected):
        signer.sign_receipt(payload, FakeBackend(), issuer="isolated-c14-signer", now=NOW)


def test_empty_or_non_utc_issuer_and_clock_are_rejected():
    with pytest.raises(signer.Rejected): signer.build_receipt(REQUEST, issuer="", now=NOW, receipt_id="x")
    with pytest.raises(signer.Rejected): signer.build_receipt(REQUEST, issuer="ok", now=datetime(2026, 9, 20, 12, 0), receipt_id="x")


def test_kms_resource_must_be_version_scoped():
    with pytest.raises(signer.Rejected): signer.GoogleKmsP256Backend("projects/x/locations/global/keyRings/r/cryptoKeys/k")
