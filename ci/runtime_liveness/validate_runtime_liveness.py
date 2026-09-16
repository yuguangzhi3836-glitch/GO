#!/usr/bin/env python3
"""Fail-closed liveness gate for GO Cell executors."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

CELL_IDS = {f"C{i:02d}" for i in range(1, 15)}
ACTIVE = {"ACKED", "RUNNING", "DIAGNOSE", "FIX", "RETEST"}
TERMINAL = {"EXITED", "DONE_SCOPED", "BLOCKED_EXTERNAL", "BLOCKED_WITH_EVIDENCE"}
DEFAULT_MAX_HEARTBEAT_AGE_SECONDS = 120


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def validate(snapshot: dict, now: datetime | None = None,
             max_heartbeat_age_seconds: int = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    errors: list[str] = []
    stale: list[str] = []
    live: list[str] = []

    if isinstance(max_heartbeat_age_seconds, bool) or not isinstance(max_heartbeat_age_seconds, int) or max_heartbeat_age_seconds <= 0:
        return {"gate": "HOLD", "reason": "INVALID_POLICY", "errors": ["max heartbeat age must be a positive integer"]}
    if not isinstance(snapshot, dict):
        return {"gate": "HOLD", "reason": "INVALID_SNAPSHOT", "errors": ["snapshot must be an object"]}
    try:
        observed_at = instant(snapshot["observed_at"])
    except (KeyError, TypeError, ValueError) as error:
        return {"gate": "HOLD", "reason": "INVALID_SNAPSHOT", "errors": [f"observed_at: {error}"]}
    if observed_at > now + timedelta(seconds=5):
        errors.append("observed_at is in the future")

    executors = snapshot.get("executors")
    if not isinstance(executors, list):
        return {"gate": "HOLD", "reason": "INVALID_SNAPSHOT", "errors": errors + ["executors must be a list"]}

    seen: set[str] = set()
    lease_ids: set[str] = set()
    for executor in executors:
        if not isinstance(executor, dict):
            errors.append("executor entry must be an object")
            continue
        cell_id = executor.get("cell_id")
        if cell_id not in CELL_IDS:
            errors.append(f"invalid cell_id: {cell_id}")
            continue
        if cell_id in seen:
            errors.append(f"duplicate executor: {cell_id}")
            stale.append(cell_id)
            continue
        seen.add(cell_id)
        status = executor.get("status")
        if status not in ACTIVE | TERMINAL:
            errors.append(f"{cell_id}: invalid status")
            stale.append(cell_id)
            continue
        if status in ACTIVE:
            try:
                heartbeat = instant(executor["heartbeat_at"])
                lease_expires = instant(executor["lease_expires_at"])
            except (KeyError, TypeError, ValueError) as error:
                errors.append(f"{cell_id}: active executor requires heartbeat and lease: {error}")
                stale.append(cell_id)
                continue
            identifiers = ("task_id", "source_sha", "attempt_id", "lease_id")
            if any(not isinstance(executor.get(name), str) or not executor[name].strip() for name in identifiers):
                errors.append(f"{cell_id}: active executor requires task/source/attempt/lease binding")
                stale.append(cell_id)
                continue
            if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", executor["source_sha"]):
                errors.append(f"{cell_id}: source_sha must be a canonical lowercase Git identity")
                stale.append(cell_id)
                continue
            lease_id = executor["lease_id"]
            if lease_id in lease_ids:
                errors.append(f"{cell_id}: duplicate lease_id")
                stale.append(cell_id)
                continue
            lease_ids.add(lease_id)
            if heartbeat > observed_at + timedelta(seconds=5):
                errors.append(f"{cell_id}: heartbeat is in the future")
                stale.append(cell_id)
                continue
            if observed_at - heartbeat > timedelta(seconds=max_heartbeat_age_seconds):
                stale.append(cell_id)
                continue
            if lease_expires <= observed_at:
                stale.append(cell_id)
                continue
            live.append(cell_id)

    expected = snapshot.get("expected_executable_cells", [])
    if (not isinstance(expected, list) or any(cell not in CELL_IDS for cell in expected)
            or len(expected) != len(set(expected))):
        errors.append("expected_executable_cells must contain unique valid Cell IDs")
        expected = []
    affected = sorted(set(expected) - set(live))
    all_cells_exited = bool(expected) and not live

    if all_cells_exited:
        gate, reason = "SCHEDULER_FAIL", "ALL_CELLS_EXITED"
    elif stale or affected:
        gate, reason = "SCHEDULER_FAIL", "CELL_EXECUTOR_MISSING_OR_STALE"
    elif errors:
        gate, reason = "HOLD", "INVALID_SNAPSHOT"
    else:
        gate, reason = "PASS_SCOPED", "LIVE_LEASES_VERIFIED"

    return {
        "gate": gate, "reason": reason, "observed_at": snapshot.get("observed_at"),
        "live_cells": sorted(live), "stale_cells": sorted(set(stale)),
        "affected_cells": affected, "all_cells_exited": all_cells_exited,
        "errors": errors,
        "meaning": "Fresh external lease/heartbeat liveness only; not product, C14, C13, release, deploy, or production PASS.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--now")
    parser.add_argument("--max-heartbeat-age-seconds", type=int, default=DEFAULT_MAX_HEARTBEAT_AGE_SECONDS)
    args = parser.parse_args()
    result = validate(json.loads(args.snapshot.read_text()), instant(args.now) if args.now else None,
                      args.max_heartbeat_age_seconds)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["gate"] == "PASS_SCOPED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
