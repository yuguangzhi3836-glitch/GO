"""GO Command Center <-> Hong Kong Staging signed control protocol.

This module defines a narrow, replay-resistant, allowlisted execution envelope.
It never accepts arbitrary shell commands and never targets production.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re


ALLOWED_TASK_TYPES = {
    "DEPTH10_RELEASE_GATE",
    "POSTGRES_CRASH_RECOVERY_GATE",
    "HYATT_10_REAL_E2E",
    "HOTEL_MASTERPIECE_BROWSER_GATE",
    "CONTROL_PLANE_ROUND_TRIP_GATE",
}
ALLOWED_ENVIRONMENTS = {"HK_STAGING"}
ALLOWED_AUTHORITIES = {"STAGING_READONLY", "STAGING_CONTROLLED_EXECUTE"}
MAX_CLOCK_SKEW_SECONDS = 300
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest_payload(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("CONTROL_TIMESTAMP_TZ_REQUIRED")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class VerifiedControlTask:
    task_id: str
    task_type: str
    environment: str
    authority: str
    candidate_sha256: str
    task_sha256: str
    payload: dict
    node_id: str
    nonce: str
    issued_at: datetime


def signing_material(envelope: dict) -> bytes:
    unsigned = {k: envelope[k] for k in sorted(envelope) if k != "signature"}
    return _canonical(unsigned)


def sign_envelope(envelope: dict, secret: bytes) -> str:
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < 32:
        raise ValueError("CONTROL_HMAC_SECRET_TOO_SHORT")
    return hmac.new(bytes(secret), signing_material(envelope), hashlib.sha256).hexdigest()


def verify_envelope(envelope: dict, *, secret: bytes, expected_node_id: str,
                    now: datetime | None = None) -> VerifiedControlTask:
    if not isinstance(envelope, dict):
        raise ValueError("CONTROL_ENVELOPE_REQUIRED")
    required = {
        "task_id", "task_type", "environment", "authority", "candidate_sha256",
        "task_sha256", "payload", "node_id", "nonce", "issued_at", "signature",
    }
    if set(envelope) != required:
        raise ValueError("CONTROL_ENVELOPE_SCHEMA_INVALID")
    if envelope["task_type"] not in ALLOWED_TASK_TYPES:
        raise ValueError("CONTROL_TASK_NOT_ALLOWLISTED")
    if envelope["environment"] not in ALLOWED_ENVIRONMENTS:
        raise ValueError("CONTROL_ENVIRONMENT_NOT_ALLOWED")
    if envelope["authority"] not in ALLOWED_AUTHORITIES:
        raise ValueError("CONTROL_AUTHORITY_INVALID")
    if envelope["node_id"] != expected_node_id:
        raise ValueError("CONTROL_NODE_MISMATCH")
    if not NONCE_RE.fullmatch(str(envelope["nonce"])):
        raise ValueError("CONTROL_NONCE_INVALID")
    if not SHA_RE.fullmatch(str(envelope["candidate_sha256"])):
        raise ValueError("CONTROL_CANDIDATE_SHA_INVALID")
    if not SHA_RE.fullmatch(str(envelope["task_sha256"])):
        raise ValueError("CONTROL_TASK_SHA_INVALID")
    if not isinstance(envelope["payload"], dict):
        raise ValueError("CONTROL_PAYLOAD_INVALID")
    if digest_payload(envelope["payload"]) != envelope["task_sha256"]:
        raise ValueError("CONTROL_TASK_SHA_MISMATCH")
    issued = _parse_utc(envelope["issued_at"])
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if abs((current - issued).total_seconds()) > MAX_CLOCK_SKEW_SECONDS:
        raise ValueError("CONTROL_TIMESTAMP_OUT_OF_WINDOW")
    supplied = str(envelope["signature"])
    expected = sign_envelope(envelope, secret)
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("CONTROL_SIGNATURE_INVALID")
    if envelope["authority"] == "STAGING_READONLY" and envelope["task_type"] not in {
        "DEPTH10_RELEASE_GATE", "CONTROL_PLANE_ROUND_TRIP_GATE"
    }:
        raise ValueError("CONTROL_READONLY_AUTHORITY_INSUFFICIENT")
    return VerifiedControlTask(
        task_id=str(envelope["task_id"]), task_type=str(envelope["task_type"]),
        environment=str(envelope["environment"]), authority=str(envelope["authority"]),
        candidate_sha256=str(envelope["candidate_sha256"]), task_sha256=str(envelope["task_sha256"]),
        payload=dict(envelope["payload"]), node_id=str(envelope["node_id"]), nonce=str(envelope["nonce"]),
        issued_at=issued,
    )


def build_envelope(*, task_id: str, task_type: str, authority: str, candidate_sha256: str,
                   payload: dict, node_id: str, nonce: str, issued_at: str, secret: bytes) -> dict:
    envelope = {
        "task_id": task_id,
        "task_type": task_type,
        "environment": "HK_STAGING",
        "authority": authority,
        "candidate_sha256": candidate_sha256,
        "task_sha256": digest_payload(payload),
        "payload": payload,
        "node_id": node_id,
        "nonce": nonce,
        "issued_at": issued_at,
    }
    envelope["signature"] = sign_envelope(envelope, secret)
    return envelope
