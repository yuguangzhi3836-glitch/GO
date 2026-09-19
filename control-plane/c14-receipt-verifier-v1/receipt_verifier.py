"""Offline Ed25519 verifier for a C14 receipt.

This module verifies a detached receipt using a public key supplied by a host
trust boundary. It never generates, stores, reads, or transmits private keys.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Refusal(ValueError):
    pass


def canonical_payload(receipt: dict) -> bytes:
    payload = {k: v for k, v in receipt.items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def public_key_fingerprint(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()


def verify_c14_receipt(receipt: dict, trusted_public_key: bytes, trusted_key_fingerprint: str, expected_binding: dict) -> dict:
    required = {"schema_version", "algorithm", "key_fingerprint", "issuer", "verdict",
                "timestamp", "candidate_sha", "application_tree", "digest", "signature"}
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise Refusal("receipt_schema")
    if receipt["schema_version"] != "c14-receipt-v1" or receipt["algorithm"] != "Ed25519":
        raise Refusal("receipt_algorithm")
    if public_key_fingerprint(trusted_public_key) != trusted_key_fingerprint or receipt["key_fingerprint"] != trusted_key_fingerprint:
        raise Refusal("untrusted_key")
    if not isinstance(receipt["issuer"], str) or not receipt["issuer"] or not isinstance(receipt["timestamp"], str) or not receipt["timestamp"]:
        raise Refusal("receipt_identity")
    if receipt["verdict"] != "PASS" or not _HEX64.fullmatch(receipt["digest"]):
        raise Refusal("receipt_claim")
    if (receipt["candidate_sha"], receipt["application_tree"]) != (expected_binding["candidate_sha"], expected_binding["application_tree"]):
        raise Refusal("receipt_binding")
    try:
        signature = base64.b64decode(receipt["signature"], validate=True)
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(signature, canonical_payload(receipt))
    except (ValueError, InvalidSignature):
        raise Refusal("receipt_signature") from None
    return {"issuer": receipt["issuer"], "verdict": receipt["verdict"], "candidate_sha": receipt["candidate_sha"],
            "application_tree": receipt["application_tree"], "digest": receipt["digest"], "key_fingerprint": receipt["key_fingerprint"],
            "signature_verified": True}
