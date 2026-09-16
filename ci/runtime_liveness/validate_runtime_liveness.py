#!/usr/bin/env python3
"""Fail-closed liveness gate for GO Cell executors.

This gate evaluates a runtime snapshot. Ledger assignment, historical evidence,
or an old process receipt never proves that an executor is alive.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

CELL_IDS = {f"C{i:02d}" for i in range(1, 15)}
ACTIVE = {"ACKED", "RUNNING", "DIAGNOSE", "FIX", "RETEST"}
TERMINAL = {"EXITED", "DONE_SCOPED", "BLOCKED_EXTERNAL", "BLOCKED_WITH_EVIDENCE"}


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def validate(snapshot: dict, now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    errors: list[str] = []
    stale: list[str] = []
    live: list[str] = []
    affected: list[str] = []

    if not isinstance(snapshot, dict):
        return {"gate": "HOLD", "reason": "INVALID_SNAPSHOT", "errors": ["snapshot must be an object"]}
    try:
        observed_at = instant(snapshot["observed_at"])
    except (KeyError, TypeError, ValueError) as error:
        return {"gate": "HOLD", "reason": "INVALID_SNAPSHOT", "errors": [f"observed_at: {error}"]}
    if observed_at > now:
        errors.append("observed_at is in the future")

    executors = snapshot.get("executors")
    if not isinstance(executors, list):
        return {"gate": "HOLD", "reason": "INVALID_SNAPSHOT", "errors": errors + ["executors must be a list"]}

    seen: set[str] = set()
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
            continue
        seen.add(cell_id)
        status = executor.get("status")
        if status not in ACTIVE | TERMINAL:
            errors.append(f"{cell_id}: invalid status")
            continue
        if status in ACTIVE:
            try:
                heartbeat = instant(executor["heartbeat_at"])
                lease_expires = instant(executor["lease_expires_at"])
            except (KeyError, TypeError, ValueError) as error:
                errors.append(f"{cell_id}: active executor requires heartbeat and lease: {error}")
                stale.append(cell_id)
                continue
            if heartbeat > observed_at or lease_expires <= observed_at:
                stale.append(cell_id)
                continue
            if not executor.get("task_id") or not executor.get("source_sha"):
                errors.append(f"{cell_id}: active executor requires task_id and source_sha")
                stale.append(cell_id)
                continue
            live.append(cell_id)

    expected = snapshot.get("expected_executable_cells", [])
    if not isinstance(expected, list) or any(cell not in CELL_IDS for cell in expected):
        errors.append("expected_executable_cells must contain valid Cell IDs")
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
        "gate": gate,
        "reason": reason,
        "observed_at": snapshot.get("observed_at"),
        "live_cells": sorted(live),
        "stale_cells": sorted(set(stale)),
        "affected_cells": affected,
        "all_cells_exited": all_cells_exited,
        "errors": errors,
        "meaning": "Fresh lease/heartbeat liveness only; not product, C14, C13, release, deploy, or production PASS.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--now")
    args = parser.parse_args()
    result = validate(json.loads(args.snapshot.read_text()), instant(args.now) if args.now else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["gate"] == "PASS_SCOPED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
