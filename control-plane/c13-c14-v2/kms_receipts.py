"""Google Cloud KMS HSM P-256 adapter for Command Center receipts only.

The installed CC injects an authenticated KeyManagementServiceClient and a
separately trusted, numeric key-version name + SPKI SHA-256 fingerprint.
No default credentials, project, key, private key or sign call exists at import.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from acceptance_gate import C14_ACTION, C14_ENVIRONMENT, Refusal
from c13_attestation import CANDIDATE, TREE, SCOPE
from house_bridge import RECEIPT_CONTRACT, RECEIPT_FIELDS, canonical


def crc32c(raw: bytes) -> int:
    """Castagnoli CRC, not the IEEE CRC used by zlib.crc32."""
    value = 0xFFFFFFFF
    for byte in raw:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0x82F63B78 if value & 1 else 0)
    return value ^ 0xFFFFFFFF


def _enum_name(value):
    return getattr(value, "name", value)


def _checksum(value):
    value = getattr(value, "value", value)
    return value if type(value) is int and 0 <= value <= 0xFFFFFFFF else None


def receipt_payload(raw: bytes) -> dict:
    """Narrow the signing API to canonical, frozen-source receipt objects."""
    if type(raw) is not bytes or not 0 < len(raw) <= 32000:
        raise Refusal("kms_receipt_bytes")
    try:
        record = json.loads(raw)
        if (type(record) is not dict or set(record) != RECEIPT_FIELDS - {"signature"} or
                canonical(record) != raw):
            raise Refusal("kms_receipt_schema")
    except (ValueError, UnicodeError) as exc:
        raise Refusal("kms_receipt_schema") from exc
    fixed = {"schema_version": "1", "contract": RECEIPT_CONTRACT,
             "action_id": C14_ACTION, "environment": C14_ENVIRONMENT,
             "candidate_sha": CANDIDATE, "application_tree": TREE,
             "test_scope_sha256": SCOPE, "verification_state": "EVIDENCE_VERIFIED",
             "terminal_state": "COMPLETE", "authorizes_any_action": False,
             "test_count": 71}
    if any(type(record[k]) is not type(v) or record[k] != v for k, v in fixed.items()):
        raise Refusal("kms_receipt_scope")
    for key in ("c13_evidence_sha256", "evidence_sha256", "junit_sha256", "stdout_sha256", "manifest_sha256"):
        if type(record[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", record[key]):
            raise Refusal("kms_receipt_digest")
    if (record["verdict"] not in ("PASS_SCOPED", "FAIL", "BLOCKED") or
            any(type(record[k]) is not int or not 0 <= record[k] <= 71
                for k in ("failure_count", "error_count", "skipped_count")) or
            (record["verdict"] == "PASS_SCOPED" and any(record[k] for k in
                ("failure_count", "error_count", "skipped_count")))):
        raise Refusal("kms_receipt_outcome")
    if any(type(record[k]) is not str or not record[k] for k in ("task_id", "nonce", "runner_id", "verified_at")):
        raise Refusal("kms_receipt_identity")
    return record


class KmsReceiptSigner:
    """Four host methods are composed with ReceiptStore via ControlReceiptRoute.

    The client must use the official TLS endpoint and CC-only workload identity.
    This adapter never creates keys, changes IAM or signs a C13/Task payload.
    """

    def __init__(self, client, key_version: str, trusted_fingerprint: str):
        if (type(key_version) is not str or not re.fullmatch(
                r"projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+/cryptoKeyVersions/[1-9][0-9]*", key_version) or
                type(trusted_fingerprint) is not str or not re.fullmatch(r"[0-9a-f]{64}", trusted_fingerprint)):
            raise Refusal("kms_host_binding")
        self.client, self.key_version, self.fingerprint = client, key_version, trusted_fingerprint

    def _public_key(self):
        try:
            response = self.client.get_public_key(request={"name": self.key_version}, retry=None, timeout=10)
        except Exception as exc:
            raise Refusal("kms_public_key_unavailable") from exc
        try:
            if (response.name != self.key_version or _enum_name(response.algorithm) != "EC_SIGN_P256_SHA256" or
                    _enum_name(response.protection_level) != "HSM"):
                raise Refusal("kms_public_key_binding")
            pem = response.pem.encode("ascii")
            if _checksum(response.pem_crc32c) != crc32c(pem):
                raise Refusal("kms_public_key_checksum")
            public = serialization.load_pem_public_key(pem)
            if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(public.curve, ec.SECP256R1):
                raise Refusal("kms_public_key_curve")
            der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            if hashlib.sha256(der).hexdigest() != self.fingerprint:
                raise Refusal("kms_public_key_fingerprint")
            return public
        except (AttributeError, TypeError, ValueError, UnicodeError) as exc:
            if isinstance(exc, Refusal):
                raise
            raise Refusal("kms_public_key_response") from exc

    def sign_control_receipt(self, raw: bytes) -> str:
        receipt_payload(raw)
        public = self._public_key()  # read back pinned key and HSM before signing
        digest = hashlib.sha256(raw).digest()
        try:
            response = self.client.asymmetric_sign(request={"name": self.key_version,
                "digest": {"sha256": digest}, "digest_crc32c": crc32c(digest)}, retry=None, timeout=10)
        except Exception as exc:
            raise Refusal("kms_sign_unavailable") from exc
        try:
            if (response.name != self.key_version or _enum_name(response.protection_level) != "HSM" or
                    response.verified_digest_crc32c is not True or
                    type(response.signature) is not bytes or not 8 <= len(response.signature) <= 72 or
                    _checksum(response.signature_crc32c) != crc32c(response.signature)):
                raise Refusal("kms_signature_response")
            public.verify(response.signature, raw, ec.ECDSA(hashes.SHA256()))
        except (AttributeError, TypeError, ValueError, InvalidSignature) as exc:
            raise Refusal("kms_signature_response") from exc
        return base64.b64encode(response.signature).decode("ascii")

    def verify_control_receipt(self, raw: bytes, signature: str) -> bool:
        receipt_payload(raw)
        public = self._public_key()
        try:
            if type(signature) is not str or len(signature) > 128:
                return False
            der = base64.b64decode(signature, validate=True)
            public.verify(der, raw, ec.ECDSA(hashes.SHA256()))
        except (ValueError, TypeError, binascii.Error, InvalidSignature):
            return False
        return True
