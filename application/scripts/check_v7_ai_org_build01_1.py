#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from go_hotel.autonomy import ALL_CELL_REGISTRY, ALL_CELLS, C14_AI_LEGAL


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / "governance/autonomy/V7_0_AI_LEGAL_AND_AUTHORITY_POLICY_BUILD01_1.json").read_text())
    checks = {
        "existing_13_cells_preserved_plus_c14": len(ALL_CELLS) == 14 and C14_AI_LEGAL.cell_id == "C14",
        "c14_unique_control_domain_owner": ALL_CELL_REGISTRY.owner_for("AI_CONSTITUTIONAL_LEGAL_REGULATORY_CONTROL").cell_id == "C14",
        "all_ai_actions_authority_checked": policy["authority_gate"]["coverage"] == "100_PERCENT_OF_AI_ACTIONS",
        "authority_fail_closed": policy["authority_gate"]["fail_closed"] is True,
        "legal_routing_is_dynamic_exposure": policy["legal_routing"]["basis"] == "DYNAMIC_LEGAL_EXPOSURE",
        "green_label_not_whitelist": policy["legal_routing"]["not_basis"] == "BUSINESS_OR_GREEN_OPERATION_LABEL",
        "c14_no_business_truth_authority": policy["c14"]["business_truth_authority"] is False,
        "no_legal_rule_fails_closed": policy["c14"]["no_rule_behavior"] == "LEGAL_HOLD",
        "no_business_feature_expansion": policy["business_feature_expansion"] is False,
    }
    failed = [k for k, v in checks.items() if not v]
    print(json.dumps({"build": "V7.0 AI Organization Build 01.1", "checks": checks, "result": "PASS" if not failed else "FAIL", "failed": failed}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
