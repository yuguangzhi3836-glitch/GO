#!/usr/bin/env python3
"""Offline, fail-closed verifier for externally signed C14 P-256 receipts."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

SCHEMA = "go.c14.receipt.v1"
FIELDS = ("schema", "receipt_id", "gate", "candidate_sha", "application_tree",
          "verdict", "issuer", "issued_at", "evidence_manifest_sha256")
SHA = re.compile(r"^[0-9a-f]{40,64}$")
FP = re.compile(r"^sha256:[0-9a-f]{64}$")
BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
EXPECTED_FIELDS = ("issuer", "candidate_sha", "application_tree", "verdict",
                   "evidence_manifest_sha256")


class VerificationError(ValueError):
    pass


def canonical_receipt_bytes(receipt: dict[str, Any]) -> bytes:
    try:
        return json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, UnicodeError, ValueError) as exc:
        raise VerificationError("RECEIPT_NOT_CANONICALIZABLE") from exc


def parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise VerificationError("ISSUED_AT_MUST_BE_UTC_Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise VerificationError("INVALID_ISSUED_AT") from exc


def validate(receipt: Any) -> dict[str, str]:
    if not isinstance(receipt, dict):
        raise VerificationError("RECEIPT_MUST_BE_OBJECT")
    if set(receipt) != set(FIELDS):
        raise VerificationError("RECEIPT_FIELDS_MISMATCH")
    if any(not isinstance(receipt[key], str) or not receipt[key] for key in FIELDS):
        raise VerificationError("INVALID_RECEIPT_FIELD")
    if receipt["schema"] != SCHEMA or receipt["gate"] != "C14":
        raise VerificationError("UNSUPPORTED_RECEIPT_SCOPE")
    if receipt["verdict"] not in {"PASS", "FAIL"}:
        raise VerificationError("UNSUPPORTED_RECEIPT_SCOPE")
    if any(not SHA.fullmatch(receipt[key]) for key in
           ("candidate_sha", "application_tree", "evidence_manifest_sha256")):
        raise VerificationError("INVALID_DIGEST")
    parse_time(receipt["issued_at"])
    return receipt


def load_key(path: Path, expected_fingerprint: str) -> ec.EllipticCurvePublicKey:
    if not FP.fullmatch(expected_fingerprint):
        raise VerificationError("INVALID_EXPECTED_FINGERPRINT")
    try:
        key = serialization.load_pem_public_key(path.read_bytes())
    except Exception as exc:
        raise VerificationError("TRUSTED_PUBLIC_KEY_UNREADABLE") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise VerificationError("TRUSTED_KEY_MUST_BE_P256")
    der = key.public_bytes(serialization.Encoding.DER,
                           serialization.PublicFormat.SubjectPublicKeyInfo)
    if "sha256:" + hashlib.sha256(der).hexdigest() != expected_fingerprint:
        raise VerificationError("TRUSTED_KEY_FINGERPRINT_MISMATCH")
    return key


def verify(envelope: Any, key: ec.EllipticCurvePublicKey, now: datetime,
           max_age_seconds: int, expected: Mapping[str, str]) -> dict[str, str]:
    if now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
        raise VerificationError("VERIFICATION_TIME_MUST_BE_UTC")
    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or max_age_seconds <= 0:
        raise VerificationError("INVALID_MAX_AGE_SECONDS")
    if set(expected) != set(EXPECTED_FIELDS) or any(not isinstance(expected[k], str) for k in EXPECTED_FIELDS):
        raise VerificationError("EXPECTED_BINDINGS_MISMATCH")
    if not isinstance(envelope, dict) or set(envelope) != {"receipt", "signature"}:
        raise VerificationError("ENVELOPE_FIELDS_MISMATCH")
    receipt = validate(envelope["receipt"])
    signature = envelope["signature"]
    if not isinstance(signature, str) or not BASE64URL.fullmatch(signature):
        raise VerificationError("INVALID_SIGNATURE_ENCODING")
    try:
        raw_signature = base64.b64decode(signature + "=" * (-len(signature) % 4),
                                         altchars=b"-_", validate=True)
    except Exception as exc:
        raise VerificationError("INVALID_SIGNATURE_ENCODING") from exc
    age = (now.astimezone(timezone.utc) - parse_time(receipt["issued_at"])).total_seconds()
    if age < -60 or age > max_age_seconds:
        raise VerificationError("RECEIPT_OUTSIDE_FRESHNESS_WINDOW")
    try:
        key.verify(raw_signature, canonical_receipt_bytes(receipt), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise VerificationError("SIGNATURE_INVALID") from exc
    if any(receipt[field] != expected[field] for field in EXPECTED_FIELDS):
        raise VerificationError("FIXED_BINDING_MISMATCH")
    return {key: receipt[key] for key in FIELDS if key not in {"schema", "gate"}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--trusted-public-key", required=True, type=Path)
    parser.add_argument("--expected-fingerprint", required=True)
    for option in EXPECTED_FIELDS:
        parser.add_argument("--expected-" + option.replace("_", "-"), required=True)
    parser.add_argument("--max-age-seconds", type=int, default=900)
    parser.add_argument("--verification-time")
    args = parser.parse_args()
    try:
        now = parse_time(args.verification_time) if args.verification_time else datetime.now(timezone.utc)
        expected = {field: getattr(args, "expected_" + field) for field in EXPECTED_FIELDS}
        summary = verify(json.loads(args.receipt.read_text()),
                         load_key(args.trusted_public_key, args.expected_fingerprint),
                         now, args.max_age_seconds, expected)
    except (OSError, json.JSONDecodeError, VerificationError) as exc:
        print(f"VERIFY_FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"verified": True, "receipt": summary}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
