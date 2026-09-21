#!/usr/bin/env python3
"""Offline, fail-closed verifier for an independently-authorized C14 trust registration."""
from __future__ import annotations

import base64, hashlib, json, re
from datetime import datetime
from pathlib import Path
from typing import Any
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

SCHEMA = "go.c14.trust-registration.v2"
FP = re.compile(r"^sha256:[0-9a-f]{64}$")
RESOURCE = re.compile(r"^projects/go-c14-trust-prod-509114/locations/global/keyRings/go-c14-receipts/cryptoKeys/[a-z0-9-]+/cryptoKeyVersions/[1-9][0-9]*$")
BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
AUTHORITY_VERSION = "projects/go-c14-trust-prod-509114/locations/global/keyRings/go-c14-receipts/cryptoKeys/go-c14-registration-authority-v1/cryptoKeyVersions/1"
AUTHORITY_FP = "sha256:87eb0ab66bd2e1f02331b2bb402ee214194b5f186c381222f9b7edd16c29dc7f"
SIGNER_VERSION = "projects/go-c14-trust-prod-509114/locations/global/keyRings/go-c14-receipts/cryptoKeys/go-c14-receipt-v1/cryptoKeyVersions/1"
SIGNER_FP = "sha256:0ebf81cd906747a30cd0d8d44c4c2cf536c5e1277f7bf468a51b3eb3fc27ce75"

class RegistrationError(ValueError): pass

def canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def parse_utc(value: Any) -> None:
    if not isinstance(value, str) or not value.endswith("Z"): raise RegistrationError("REGISTRATION_TIME_MUST_BE_UTC_Z")
    try: datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc: raise RegistrationError("INVALID_REGISTRATION_TIME") from exc

def load_authority(path: Path) -> ec.EllipticCurvePublicKey:
    try: key = serialization.load_pem_public_key(path.read_bytes())
    except Exception as exc: raise RegistrationError("AUTHORITY_PUBLIC_KEY_UNREADABLE") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1": raise RegistrationError("AUTHORITY_KEY_MUST_BE_P256")
    der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if "sha256:" + hashlib.sha256(der).hexdigest() != AUTHORITY_FP: raise RegistrationError("AUTHORITY_FINGERPRINT_MISMATCH")
    return key

def validate_registration(registration: Any) -> dict[str, str]:
    required = {"schema","authority_key_version","authority_spki_sha256","signer_key_version","signer_spki_sha256","algorithm","registered_at"}
    if not isinstance(registration, dict) or set(registration) != required: raise RegistrationError("REGISTRATION_FIELDS_MISMATCH")
    if registration["schema"] != SCHEMA or registration["algorithm"] != "EC_SIGN_P256_SHA256": raise RegistrationError("UNSUPPORTED_REGISTRATION_SCOPE")
    if registration["authority_key_version"] != AUTHORITY_VERSION or registration["authority_spki_sha256"] != AUTHORITY_FP: raise RegistrationError("UNEXPECTED_AUTHORITY_BINDING")
    if registration["signer_key_version"] != SIGNER_VERSION or registration["signer_spki_sha256"] != SIGNER_FP: raise RegistrationError("UNEXPECTED_SIGNER_BINDING")
    if not all(isinstance(registration[x], str) and RESOURCE.fullmatch(registration[x]) for x in ("authority_key_version","signer_key_version")): raise RegistrationError("INVALID_KEY_VERSION_RESOURCE")
    if not all(isinstance(registration[x], str) and FP.fullmatch(registration[x]) for x in ("authority_spki_sha256","signer_spki_sha256")): raise RegistrationError("INVALID_SPKI_FINGERPRINT")
    if registration["authority_key_version"] == registration["signer_key_version"] or registration["authority_spki_sha256"] == registration["signer_spki_sha256"]: raise RegistrationError("AUTHORITY_AND_SIGNER_MUST_DIFFER")
    parse_utc(registration["registered_at"])
    return registration

def verify(envelope: Any, authority: ec.EllipticCurvePublicKey) -> dict[str, str]:
    if not isinstance(envelope, dict) or set(envelope) != {"registration","signature"}: raise RegistrationError("REGISTRATION_ENVELOPE_FIELDS_MISMATCH")
    registration = validate_registration(envelope["registration"])
    signature = envelope["signature"]
    if not isinstance(signature, str) or not BASE64URL.fullmatch(signature): raise RegistrationError("INVALID_REGISTRATION_SIGNATURE_ENCODING")
    try: raw = base64.b64decode(signature + "=" * (-len(signature) % 4), altchars=b"-_", validate=True)
    except Exception as exc: raise RegistrationError("INVALID_REGISTRATION_SIGNATURE_ENCODING") from exc
    try: authority.verify(raw, canonical(registration), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc: raise RegistrationError("REGISTRATION_SIGNATURE_INVALID") from exc
    return registration
