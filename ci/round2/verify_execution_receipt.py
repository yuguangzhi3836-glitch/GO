#!/usr/bin/env python3
"""Admit source-bound execution receipts without claiming authentication.

The validator proves record binding and time-bounded heartbeat freshness only.
It does not authenticate a worker identity or prove process liveness.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
import threading

CANONICAL_BASE = "dcb68a652429aa01e8428ce9f582e4bab6a6175e"
FIXED_CANDIDATE_SHA = "911d6e13bceaf83bb62c775f33a325bbd68af885"
APPLICATION_GIT_TREE = "dd815baf0105cce603e9a28b002cfb9d8b95d186"
APPLICATION_SOURCE_FINGERPRINT_SHA256 = "a64f8185f19f1c78a70fc6662fbafc85f69273745a95503f97c2948ab6d85374"
CURRENT_TASK_ID = "V70-R3-C12-01"
LEGACY_SOURCE_ANCHOR = "fef9c748adb77d37ba5d4dc4fa4662eb668303a1"
LEGACY_PARENT_CANDIDATE = "a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b"
DEFAULT_MAX_HEARTBEAT_AGE_SECONDS = 300


def _instant(value, name, errors):
    try:
        if not isinstance(value, str):
            raise ValueError("missing")
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("timezone required")
        return stamp
    except (TypeError, ValueError):
        errors.append(f"{name} requires an actual timezone-qualified timestamp")
        return None


def verify(receipt, evidence_root, *, expected_cell, expected_task, expected_agent,
           observed_at=None, max_heartbeat_age_seconds=DEFAULT_MAX_HEARTBEAT_AGE_SECONDS):
    errors = []
    result = {"gate": "HOLD", "errors": errors, "authenticated_worker_identity": False,
              "live_worker_liveness_verified": False, "heartbeat_fresh": False,
              "stale_running": False, "required_transition": None,
              "meaning": "Local source-bound ACK/start/heartbeat record admission only"}
    if not isinstance(receipt, dict):
        errors.append("receipt must be an object")
        return result
    if isinstance(max_heartbeat_age_seconds, bool) or not isinstance(max_heartbeat_age_seconds, int) or max_heartbeat_age_seconds <= 0:
        errors.append("max_heartbeat_age_seconds must be a positive integer")
        return result
    current_binding = expected_task == CURRENT_TASK_ID
    if current_binding:
        identities = {"cell_id": expected_cell, "task_id": expected_task, "agent": expected_agent,
                      "canonical_base": CANONICAL_BASE, "fixed_candidate_sha": FIXED_CANDIDATE_SHA,
                      "application_git_tree": APPLICATION_GIT_TREE,
                      "application_source_fingerprint_sha256": APPLICATION_SOURCE_FINGERPRINT_SHA256}
    else:
        identities = {"cell_id": expected_cell, "task_id": expected_task, "agent": expected_agent,
                      "source_anchor": LEGACY_SOURCE_ANCHOR,
                      "parent_candidate_commit": LEGACY_PARENT_CANDIDATE}
    for field, expected in identities.items():
        if not isinstance(expected, str) or not expected.strip() or receipt.get(field) != expected:
            errors.append(f"{field} identity mismatch")
    if receipt.get("status") != "RUNNING":
        errors.append("receipt.status must explicitly be RUNNING; ASSIGNED is not an ACK/start")

    time_names = ("acknowledged_at", "started_at", "heartbeat_at") if current_binding else ("acknowledged_at", "started_at")
    times = {name: _instant(receipt.get(name), name, errors) for name in time_names}
    observation = _instant(observed_at or datetime.now(timezone.utc).isoformat(), "observed_at", errors)
    if all(times.values()) and observation:
        if current_binding:
            if not times["acknowledged_at"] <= times["started_at"] <= times["heartbeat_at"] <= observation:
                errors.append("timestamps must satisfy acknowledged_at <= started_at <= heartbeat_at <= observed_at")
            elif observation - times["heartbeat_at"] > timedelta(seconds=max_heartbeat_age_seconds):
                result["stale_running"] = True
                result["required_transition"] = "STALE"
                errors.append("RUNNING heartbeat expired; receipt is stale and must not remain RUNNING")
            else:
                result["heartbeat_fresh"] = True
        elif not times["acknowledged_at"] <= times["started_at"] <= observation:
            errors.append("timestamps must satisfy acknowledged_at <= started_at <= observed_at")

    evidence = receipt.get("execution_evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("execution_evidence must contain bound process/tool output")
        evidence = []
    root = Path(evidence_root).resolve()
    for item in evidence:
        if not isinstance(item, dict):
            errors.append("execution_evidence entry must be an object")
            continue
        if item.get("kind") not in ("PROCESS_OUTPUT", "TOOL_RESULT"):
            errors.append("execution_evidence kind must be PROCESS_OUTPUT or TOOL_RESULT")
        rel, digest = item.get("path"), item.get("sha256")
        if not isinstance(rel, str) or not rel.strip():
            errors.append("execution_evidence path missing")
            continue
        path = (root / rel).resolve()
        if Path(rel).is_absolute() or not path.is_relative_to(root) or not path.is_file():
            errors.append(f"execution_evidence missing or outside root: {rel}")
            continue
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"execution_evidence invalid sha256: {rel}")
            continue
        try:
            data = path.read_bytes()
            if not data or hashlib.sha256(data).hexdigest() != digest:
                errors.append(f"execution_evidence empty or checksum mismatch: {rel}")
        except OSError as error:
            errors.append(f"execution_evidence unreadable: {rel}: {error}")
    if not errors:
        result["gate"] = "PASS_SCOPED"
    return result



IDENTITY_ASSERTION_ALGORITHM = "HMAC-SHA256"
DEFAULT_MAX_ASSERTION_LIFETIME_SECONDS = 300
_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _assertion_payload(assertion):
    fields = ("algorithm", "key_id", "worker_id", "task_id", "candidate_sha",
              "nonce", "issued_at", "expires_at")
    return {name: assertion.get(name) for name in fields}


def sign_identity_assertion(assertion, trust_key):
    """Return a lowercase hex signature over the canonical assertion payload."""
    if not isinstance(trust_key, bytes) or len(trust_key) < 32:
        raise ValueError("identity trust key must contain at least 32 bytes")
    payload = json.dumps(_assertion_payload(assertion), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False).encode()
    return hmac.new(trust_key, payload, hashlib.sha256).hexdigest()


class DurableNonceStore:
    """SQLite-backed atomic nonce consumption durable across process restarts."""

    def __init__(self, path):
        self.path = str(path)
        self._init_lock = threading.Lock()
        with self._init_lock, sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS identity_nonce (
                nonce TEXT PRIMARY KEY,
                expires_at TEXT NOT NULL,
                consumed_at TEXT NOT NULL
            )""")

    def consume(self, nonce, expires_at, observed_at):
        """Atomically consume once. Storage errors propagate so admission fails closed."""
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("DELETE FROM identity_nonce WHERE expires_at < ?", (observed_at,))
                db.execute(
                    "INSERT INTO identity_nonce(nonce, expires_at, consumed_at) VALUES (?, ?, ?)",
                    (nonce, expires_at, observed_at),
                )
                db.execute("COMMIT")
                return True
            except sqlite3.IntegrityError:
                db.execute("ROLLBACK")
                return False
            except Exception:
                db.execute("ROLLBACK")
                raise


def verify_identity_assertion(assertion, *, trusted_keys, expected_worker_id,
                              expected_task_id, expected_candidate_sha,
                              observed_at=None, seen_nonces=None, nonce_store=None,
                              max_lifetime_seconds=DEFAULT_MAX_ASSERTION_LIFETIME_SECONDS):
    """Verify a bounded signed identity assertion without claiming process liveness."""
    errors = []
    result = {
        "gate": "HOLD",
        "errors": errors,
        "authenticated_worker_identity": False,
        "assertion_signature_verified": False,
        "live_worker_liveness_verified": False,
        "replay_detected": False,
        "meaning": "Signed worker identity assertion only; not live process liveness",
    }
    if not isinstance(assertion, dict):
        errors.append("identity assertion must be an object")
        return result
    if not isinstance(trusted_keys, dict):
        errors.append("trusted_keys must be an explicit key-id mapping")
        return result
    if (isinstance(max_lifetime_seconds, bool) or
            not isinstance(max_lifetime_seconds, int) or max_lifetime_seconds <= 0):
        errors.append("max_lifetime_seconds must be a positive integer")
        return result
    expected = {
        "algorithm": IDENTITY_ASSERTION_ALGORITHM,
        "worker_id": expected_worker_id,
        "task_id": expected_task_id,
        "candidate_sha": expected_candidate_sha,
    }
    for name, value in expected.items():
        if not isinstance(value, str) or not value or assertion.get(name) != value:
            errors.append(f"{name} identity mismatch")
    key_id = assertion.get("key_id")
    trust_key = trusted_keys.get(key_id) if isinstance(key_id, str) else None
    if not isinstance(trust_key, bytes) or len(trust_key) < 32:
        errors.append("identity assertion key is not trusted")
    nonce = assertion.get("nonce")
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        errors.append("identity assertion nonce invalid")
    issued = _instant(assertion.get("issued_at"), "issued_at", errors)
    expires = _instant(assertion.get("expires_at"), "expires_at", errors)
    observed = _instant(observed_at or datetime.now(timezone.utc).isoformat(),
                        "observed_at", errors)
    if issued and expires and observed:
        if not issued <= observed <= expires:
            errors.append("identity assertion is not currently valid")
        if expires - issued > timedelta(seconds=max_lifetime_seconds):
            errors.append("identity assertion lifetime exceeds policy")
    signature = assertion.get("signature")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        errors.append("identity assertion signature invalid")
    elif isinstance(trust_key, bytes) and len(trust_key) >= 32:
        expected_signature = sign_identity_assertion(assertion, trust_key)
        if not hmac.compare_digest(signature, expected_signature):
            errors.append("identity assertion signature mismatch")
        else:
            result["assertion_signature_verified"] = True
    memory_store = seen_nonces if seen_nonces is not None else set()
    if nonce_store is None and isinstance(nonce, str) and nonce in memory_store:
        result["replay_detected"] = True
        errors.append("identity assertion nonce replayed")
    if not errors:
        if nonce_store is not None:
            try:
                consumed = nonce_store.consume(nonce, assertion["expires_at"], observed.isoformat())
            except Exception as error:
                errors.append(f"identity nonce storage unavailable: {error}")
                consumed = None
            if consumed is False:
                result["replay_detected"] = True
                errors.append("identity assertion nonce replayed")
        else:
            memory_store.add(nonce)
    if not errors:
        result["gate"] = "PASS_SCOPED"
        result["authenticated_worker_identity"] = True
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=Path.cwd())
    parser.add_argument("--expected-cell", required=True)
    parser.add_argument("--expected-task", required=True)
    parser.add_argument("--expected-agent", required=True)
    parser.add_argument("--observed-at")
    parser.add_argument("--max-heartbeat-age-seconds", type=int, default=DEFAULT_MAX_HEARTBEAT_AGE_SECONDS)
    args = parser.parse_args()
    try:
        result = verify(json.loads(args.receipt.read_text()), args.evidence_root,
                        expected_cell=args.expected_cell, expected_task=args.expected_task,
                        expected_agent=args.expected_agent, observed_at=args.observed_at,
                        max_heartbeat_age_seconds=args.max_heartbeat_age_seconds)
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"gate": "HOLD", "errors": [str(error)]}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["gate"] == "PASS_SCOPED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
