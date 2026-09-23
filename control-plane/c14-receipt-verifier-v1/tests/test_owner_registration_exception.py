import base64
import hashlib
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).parents[1]))
import verify_owner_registration_exception as gate
import verify_c14_registration as verifier


def test_fixed_owner_exception_requires_exact_source_signature_and_key(tmp_path, monkeypatch):
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    der = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    key = tmp_path / "authority.pem"
    key.write_bytes(pem)
    monkeypatch.setattr(verifier, "AUTHORITY_FP", "sha256:" + hashlib.sha256(der).hexdigest())
    registration = {"schema": verifier.SCHEMA, "authority_key_version": verifier.AUTHORITY_VERSION,
                    "authority_spki_sha256": verifier.AUTHORITY_FP,
                    "signer_key_version": verifier.SIGNER_VERSION,
                    "signer_spki_sha256": verifier.SIGNER_FP,
                    "algorithm": "EC_SIGN_P256_SHA256", "registered_at": "2026-09-23T04:43:52Z"}
    source = verifier.canonical(registration)
    signature = base64.urlsafe_b64encode(private.sign(source, ec.ECDSA(hashes.SHA256()))).decode().rstrip("=")
    blob = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
    for field, value in (("SHA256", hashlib.sha256(source).hexdigest()), ("BLOB", blob),
                         ("SIGNATURE", signature)):
        monkeypatch.setattr(gate, field, value)
    assert len(source) == 621
    envelope = {"registration": registration, "signature": signature}
    args = dict(commit=gate.COMMIT, path=gate.PATH, blob=blob,
                exception_mode="OWNER_SINGLE_PERSON_EXCEPTION")
    assert gate.accept(source, envelope, key, **args)["status"] == "REGISTRATION_VERIFIED_ONLY"
    for changes in (dict(exception_mode="INDEPENDENT_AUTHORITY"), dict(commit="0" * 40), dict(blob="0" * 40)):
        with pytest.raises(verifier.RegistrationError):
            gate.accept(source, envelope, key, **(args | changes))
    with pytest.raises(verifier.RegistrationError):
        gate.accept(source + b"\n", envelope, key, **args)
    with pytest.raises(verifier.RegistrationError):
        gate.accept(source, {**envelope, "signature": "bad"}, key, **args)
