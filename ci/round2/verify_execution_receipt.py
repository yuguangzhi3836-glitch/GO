#!/usr/bin/env python3
"""Additional local receipt admission check; does not replace ledger validation.

Checks the claimed agent ACK/start and bound execution output. These strings
are evidence metadata, not cryptographic worker authentication or liveness.
No transport, server request, state mutation or automatic RUNNING transition.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

SOURCE_ANCHOR = "fef9c748adb77d37ba5d4dc4fa4662eb668303a1"
PARENT_CANDIDATE = "a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b"


def verify(receipt, evidence_root, *, expected_cell, expected_task, expected_agent):
    errors = []
    result = {"gate": "HOLD", "errors": errors, "authenticated_worker_identity": False,
              "live_worker_liveness_verified": False, "meaning": "Local ACK/start/output record admission only"}
    if not isinstance(receipt, dict):
        errors.append("receipt must be an object")
        return result
    identities = {"cell_id": expected_cell, "task_id": expected_task, "agent": expected_agent,
                  "source_anchor": SOURCE_ANCHOR, "parent_candidate_commit": PARENT_CANDIDATE}
    for field, expected in identities.items():
        if not isinstance(expected, str) or not expected.strip() or receipt.get(field) != expected:
            errors.append(f"{field} identity mismatch")
    if receipt.get("status") != "RUNNING":
        errors.append("receipt.status must explicitly be RUNNING; ASSIGNED is not an ACK/start")
    times = {}
    for name in ("acknowledged_at", "started_at", "observed_at"):
        try:
            value = receipt.get(name)
            if not isinstance(value, str):
                raise ValueError("missing")
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("timezone required")
            times[name] = stamp
        except ValueError:
            errors.append(f"{name} requires an actual timezone-qualified timestamp")
    if len(times) == 3 and not times["acknowledged_at"] <= times["started_at"] <= times["observed_at"]:
        errors.append("acknowledged_at must precede started_at and observed_at")
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
    args = parser.parse_args()
    try:
        result = verify(json.loads(args.receipt.read_text()), args.evidence_root,
                        expected_cell=args.expected_cell, expected_task=args.expected_task, expected_agent=args.expected_agent)
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"gate": "HOLD", "errors": [str(error)]}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["gate"] == "PASS_SCOPED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
