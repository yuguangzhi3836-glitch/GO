#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from go_hotel.autonomy.definitions import CELLS, CONTRACTS, EVENTS, DOMAIN_OWNERSHIP


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    registry_path = root / "governance/autonomy/V7_0_CELL_REGISTRY.json"
    policy_path = root / "governance/autonomy/V7_0_RISK_AND_AUTONOMY_POLICY.json"
    registry = json.loads(registry_path.read_text())
    policy = json.loads(policy_path.read_text())

    checks = {
        "exact_13_cells": len(CELLS) == 13 == len(registry["cells"]),
        "unique_final_owner": len({c.domain for c in CELLS}) == 13,
        "contracts_present": len(CONTRACTS) >= 5,
        "events_present": len(EVENTS) >= 8,
        "risk_classes_complete": set(policy["risk_classes"]) == {"R0", "R1", "R2", "R3", "R4"},
        "builder_validator_releaser_separated": policy["release_separation"] == "Builder != Validator != Releaser",
        "production_fail_closed_accountability": len(DOMAIN_OWNERSHIP.production_accountability_gaps()) == 13,
    }
    failed = [name for name, ok in checks.items() if not ok]
    print(json.dumps({"build": "V7.0 AI Autonomous Engineering Operating Layer — Build 01", "checks": checks, "result": "PASS" if not failed else "FAIL", "failed": failed}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
