"""Validate the public, non-secret C14 signer trust-registration artifact.

This module deliberately does not call Google Cloud or read credentials.  It
only accepts an already-exported public key and human attestations so the same
artifact can be independently reviewed in an isolated environment.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

SCHEMA = "go.c14.signer-trust.v1"
PROJECT = "go-c14-trust-prod-509114"
SERVICE_ACCOUNT = "go-c14-receipt-signer@go-c14-trust-prod-509114.iam.gserviceaccount.com"
KEY_RESOURCE_PREFIX = (
    "projects/go-c14-trust-prod-509114/locations/global/keyRings/"
    "go-c14-receipts/cryptoKeys/go-c14-receipt-v1/cryptoKeyVersions/"
)
ALGORITHM = "EC_SIGN_P256_SHA256"
ROLE = "roles/cloudkms.signerVerifier"
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class TrustManifestRejected(ValueError):
    """Trust registration is incomplete, malformed, or outside the fixed scope."""


def canonical_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def manifest_sha256(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(manifest)).hexdigest()


def _is_utc(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate(manifest: Any) -> None:
    if not isinstance(manifest, dict):
        raise TrustManifestRejected("MANIFEST_MUST_BE_OBJECT")
    required = {"schema", "project", "kms_key_version", "algorithm", "public_key_spki_sha256",
                "service_account", "kms_role", "state", "registered_at", "verifiers"}
    if set(manifest) != required:
        raise TrustManifestRejected("MANIFEST_FIELDS_MISMATCH")
    if manifest["schema"] != SCHEMA or manifest["project"] != PROJECT:
        raise TrustManifestRejected("UNEXPECTED_TRUST_DOMAIN")
    version = manifest["kms_key_version"]
    if not isinstance(version, str) or not re.fullmatch(re.escape(KEY_RESOURCE_PREFIX) + r"[1-9][0-9]*", version):
        raise TrustManifestRejected("KMS_VERSION_MUST_BE_FIXED")
    if manifest["algorithm"] != ALGORITHM or manifest["service_account"] != SERVICE_ACCOUNT:
        raise TrustManifestRejected("UNEXPECTED_SIGNER_CONFIGURATION")
    if manifest["kms_role"] != ROLE:
        raise TrustManifestRejected("UNEXPECTED_KMS_ROLE")
    if manifest["state"] != "VERIFIED":
        raise TrustManifestRejected("TRUST_REGISTRATION_NOT_VERIFIED")
    if not HEX_64.fullmatch(manifest["public_key_spki_sha256"]):
        raise TrustManifestRejected("INVALID_SPKI_FINGERPRINT")
    if not _is_utc(manifest["registered_at"]):
        raise TrustManifestRejected("INVALID_REGISTRATION_TIME")
    verifiers = manifest["verifiers"]
    if not isinstance(verifiers, list) or len(verifiers) != 2:
        raise TrustManifestRejected("TWO_INDEPENDENT_VERIFIERS_REQUIRED")
    identities = set()
    for verifier in verifiers:
        if not isinstance(verifier, dict) or set(verifier) != {"id", "role", "verified_at", "attestation"}:
            raise TrustManifestRejected("INVALID_VERIFIER_RECORD")
        if not all(isinstance(verifier[k], str) and verifier[k] for k in ("id", "role", "attestation")):
            raise TrustManifestRejected("INVALID_VERIFIER_RECORD")
        if not _is_utc(verifier["verified_at"]):
            raise TrustManifestRejected("INVALID_VERIFIER_TIME")
        identities.add(verifier["id"])
    if len(identities) != 2:
        raise TrustManifestRejected("VERIFIERS_MUST_BE_DISTINCT")

