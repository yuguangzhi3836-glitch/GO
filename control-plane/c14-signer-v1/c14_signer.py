"""Narrow, fail-closed C14 receipt signer. It is not a dispatcher or deployer."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

SCHEMA = "go.c14.receipt.v1"
FIELDS = (
    "schema", "receipt_id", "gate", "candidate_sha", "application_tree",
    "verdict", "issuer", "issued_at", "evidence_manifest_sha256",
)
SHA = re.compile(r"^[0-9a-f]{40,64}$")
FORBIDDEN = {
    "action", "deployment", "environment", "hong_kong", "production",
    "payment", "provider", "ota", "secret", "runner", "dispatch",
    "command", "url", "callback_url", "private_key", "key_material",
}


class Rejected(ValueError):
    """Input violates the intentionally small C14 signing contract."""


class SignatureBackend(Protocol):
    def sign(self, data: bytes) -> bytes: ...


def canonical_bytes(receipt: dict[str, Any]) -> bytes:
    """The bytes covered by the P-256 ECDSA signature."""
    return json.dumps(receipt, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _reject_if_forbidden(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() in FORBIDDEN:
                raise Rejected("FORBIDDEN_CONTROL_PLANE_FIELD")
            _reject_if_forbidden(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_if_forbidden(nested)


def build_receipt(request: Any, *, issuer: str, now: datetime,
                  receipt_id: str) -> dict[str, str]:
    if not isinstance(request, dict):
        raise Rejected("REQUEST_MUST_BE_OBJECT")
    _reject_if_forbidden(request)
    required = {"candidate_sha", "application_tree", "verdict", "evidence_manifest_sha256"}
    if set(request) != required:
        raise Rejected("REQUEST_FIELDS_MISMATCH")
    if not isinstance(issuer, str) or not issuer:
        raise Rejected("ISSUER_NOT_CONFIGURED")
    if request["verdict"] not in {"PASS", "FAIL"}:
        raise Rejected("INVALID_VERDICT")
    if any(not isinstance(request[key], str) or not SHA.fullmatch(request[key])
           for key in ("candidate_sha", "application_tree", "evidence_manifest_sha256")):
        raise Rejected("INVALID_DIGEST")
    if now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
        raise Rejected("CLOCK_MUST_BE_UTC")
    return {
        "schema": SCHEMA, "receipt_id": receipt_id, "gate": "C14",
        "candidate_sha": request["candidate_sha"],
        "application_tree": request["application_tree"], "verdict": request["verdict"],
        "issuer": issuer,
        "issued_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "evidence_manifest_sha256": request["evidence_manifest_sha256"],
    }


def sign_receipt(request: Any, backend: SignatureBackend, *, issuer: str,
                 now: datetime | None = None, receipt_id: str | None = None) -> dict[str, Any]:
    receipt = build_receipt(request, issuer=issuer,
                            now=now or datetime.now(timezone.utc),
                            receipt_id=receipt_id or str(uuid.uuid4()))
    signature = backend.sign(canonical_bytes(receipt))
    if not isinstance(signature, bytes) or not signature:
        raise Rejected("SIGNATURE_BACKEND_FAILED")
    return {"receipt": receipt,
            "signature": base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")}


class GoogleKmsP256Backend:
    """Production adapter; Cloud Run's service account obtains credentials implicitly."""
    def __init__(self, crypto_key_version: str):
        if not crypto_key_version.startswith("projects/") or "/cryptoKeyVersions/" not in crypto_key_version:
            raise Rejected("INVALID_KMS_KEY_VERSION_RESOURCE")
        self.crypto_key_version = crypto_key_version

    def sign(self, data: bytes) -> bytes:
        from google.cloud import kms  # imported only in the deployed runtime
        response = kms.KeyManagementServiceClient().asymmetric_sign(
            request={"name": self.crypto_key_version,
                     "digest": {"sha256": hashlib.sha256(data).digest()}})
        return bytes(response.signature)


def configured_backend() -> GoogleKmsP256Backend:
    resource = os.environ.get("C14_KMS_CRYPTO_KEY_VERSION", "")
    if not resource:
        raise Rejected("KMS_KEY_VERSION_NOT_CONFIGURED")
    return GoogleKmsP256Backend(resource)
