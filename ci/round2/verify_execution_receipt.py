#!/usr/bin/env python3
"""Admit source-bound execution receipts without claiming authentication.

The validator proves record binding and time-bounded heartbeat freshness only.
It does not authenticate a worker identity or prove process liveness.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

CANONICAL_BASE = "dcb68a652429aa01e8428ce9f582e4bab6a6175e"
FIXED_CANDIDATE_SHA = "911d6e13bceaf83bb62c775f33a325bbd68af885"
APPLICATION_GIT_TREE = "dd815baf0105cce603e9a28b002cfb9d8b95d186"
APPLICATION_SOURCE_FINGERPRINT_SHA256 = "a64f8185f19f1c78a70fc6662fbafc85f69273745a95503f97c2948ab6d85374"
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
              "stale_running": False,
              "meaning": "Local source-bound ACK/start/heartbeat record admission only"}
    if not isinstance(receipt, dict):
        errors.append("receipt must be an object")
        return result
    if isinstance(max_heartbeat_age_seconds, bool) or not isinstance(max_heartbeat_age_seconds, int) or max_heartbeat_age_seconds <= 0:
        errors.append("max_heartbeat_age_seconds must be a positive integer")
        return result
    identities = {"cell_id": expected_cell, "task_id": expected_task, "agent": expected_agent,
                  "canonical_base": CANONICAL_BASE, "fixed_candidate_sha": FIXED_CANDIDATE_SHA,
                  "application_git_tree": APPLICATION_GIT_TREE,
                  "application_source_fingerprint_sha256": APPLICATION_SOURCE_FINGERPRINT_SHA256}
    for field, expected in identities.items():
        if not isinstance(expected, str) or not expected.strip() or receipt.get(field) != expected:
            errors.append(f"{field} identity mismatch")
    if receipt.get("status") != "RUNNING":
        errors.append("receipt.status must explicitly be RUNNING; ASSIGNED is not an ACK/start")

    times = {name: _instant(receipt.get(name), name, errors)
             for name in ("acknowledged_at", "started_at", "heartbeat_at")}
    observation = _instant(observed_at or datetime.now(timezone.utc).isoformat(), "observed_at", errors)
    if all(times.values()) and observation:
        if not times["acknowledged_at"] <= times["started_at"] <= times["heartbeat_at"] <= observation:
            errors.append("timestamps must satisfy acknowledged_at <= started_at <= heartbeat_at <= observed_at")
        elif observation - times["heartbeat_at"] > timedelta(seconds=max_heartbeat_age_seconds):
            result["stale_running"] = True
            errors.append("RUNNING heartbeat expired; receipt is stale and must not remain RUNNING")
        else:
            result["heartbeat_fresh"] = True

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
