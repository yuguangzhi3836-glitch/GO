import base64
import hashlib
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

P = Path(__file__).parents[1] / "verify_c14_receipt.py"
S = importlib.util.spec_from_file_location("verifier", P)
V = importlib.util.module_from_spec(S)
S.loader.exec_module(V)
NOW = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
EXPECTED = {"issuer": "independent-test-host", "candidate_sha": "a" * 40,
            "application_tree": "b" * 40, "verdict": "PASS",
            "evidence_manifest_sha256": "c" * 64}


def envelope(private, issued_at=NOW):
    receipt = {"schema": V.SCHEMA, "receipt_id": "synthetic-1", "gate": "C14",
               **EXPECTED, "issued_at": issued_at.isoformat().replace("+00:00", "Z")}
    signature = private.sign(V.canonical_receipt_bytes(receipt), ec.ECDSA(hashes.SHA256()))
    return {"receipt": receipt, "signature": base64.urlsafe_b64encode(signature).decode().rstrip("=")}


def keyfile(tmp_path, public):
    path = tmp_path / "pub.pem"
    path.write_bytes(public.public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo))
    der = public.public_bytes(serialization.Encoding.DER,
                              serialization.PublicFormat.SubjectPublicKeyInfo)
    return path, "sha256:" + hashlib.sha256(der).hexdigest()


def trusted(tmp_path):
    private = ec.generate_private_key(ec.SECP256R1())
    path, fingerprint = keyfile(tmp_path, private.public_key())
    return private, V.load_key(path, fingerprint)


def test_valid_receipt(tmp_path):
    private, key = trusted(tmp_path)
    assert V.verify(envelope(private), key, NOW, 900, EXPECTED)["candidate_sha"] == "a" * 40


@pytest.mark.parametrize("mutate", [
    lambda e: e["receipt"].__setitem__("candidate_sha", "d" * 40),
    lambda e: e["receipt"].__setitem__("application_tree", "e" * 40),
    lambda e: e["receipt"].__setitem__("verdict", "FAIL"),
    lambda e: e["receipt"].__setitem__("issuer", "wrong-issuer"),
    lambda e: e["receipt"].__setitem__("evidence_manifest_sha256", "f" * 64),
    lambda e: e["receipt"].__setitem__("issued_at", "2026-09-21T09:44:59Z"),
    lambda e: e.__setitem__("signature", "!bad!"),
])
def test_tamper_or_stale_fails(tmp_path, mutate):
    private, key = trusted(tmp_path)
    value = envelope(private)
    mutate(value)
    with pytest.raises(V.VerificationError):
        V.verify(value, key, NOW, 900, EXPECTED)


def test_future_and_non_z_time_fail(tmp_path):
    private, key = trusted(tmp_path)
    for issued_at in (NOW + timedelta(seconds=61),):
        with pytest.raises(V.VerificationError):
            V.verify(envelope(private, issued_at), key, NOW, 900, EXPECTED)
    value = envelope(private)
    value["receipt"]["issued_at"] = "2026-09-21T10:00:00+00:00"
    with pytest.raises(V.VerificationError):
        V.verify(value, key, NOW, 900, EXPECTED)


def test_bad_trust_key_and_fingerprint_fail(tmp_path):
    path, fingerprint = keyfile(tmp_path, ed25519.Ed25519PrivateKey.generate().public_key())
    with pytest.raises(V.VerificationError):
        V.load_key(path, fingerprint)
    private = ec.generate_private_key(ec.SECP256R1())
    path, fingerprint = keyfile(tmp_path, private.public_key())
    with pytest.raises(V.VerificationError):
        V.load_key(path, fingerprint[:-1] + ("1" if fingerprint[-1] == "0" else "0"))


def test_missing_or_unsafe_expected_bindings_fail(tmp_path):
    private, key = trusted(tmp_path)
    with pytest.raises(V.VerificationError):
        V.verify(envelope(private), key, NOW, 900, {"issuer": EXPECTED["issuer"]})
    with pytest.raises(V.VerificationError):
        V.verify(envelope(private), key, NOW.replace(tzinfo=None), 900, EXPECTED)
