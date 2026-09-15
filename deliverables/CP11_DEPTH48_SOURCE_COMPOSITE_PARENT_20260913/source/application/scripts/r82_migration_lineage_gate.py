from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "alembic" / "versions"
REQUIRED_COMPAT_REVISION = "0111_test_account_expiry"
MAX_REVISION_LEN = 32
MAX_PG_NAME_LEN = 63

EXPECTED_R7_SHORT_REVISIONS = {
    "0075_production_connector_live_gate": "0075_442bc0d513d1",
    "0076_production_connector_runtime": "0076_126e14322d21",
    "0077_first_connector_activation_readiness": "0077_0ab7798c5638",
    "0078_first_connector_pilot_integration": "0078_e79db192807d",
    "0079_external_supplier_sandbox_certification": "0079_3211684dd25f",
    "0080_named_supplier_external_sandbox_execution": "0080_2cb588879e4e",
    "0081_first_go_hosted_direct_booking_pilot": "0081_d921b0671c22",
    "0082_hosted_direct_inventory_matrix": "0082_452aa445e8f7",
    "0083_hosted_content_operations_acceptance": "0083_396ac652da7a",
    "0084_hosted_direct_reservation_operations": "0084_bee2eab998ec",
    "0085_hosted_direct_frontdesk_uat_daily_close": "0085_bfa53313a4e7",
    "0086_alipay_sandbox_payment_activation": "0086_01748f3984db",
    "0087_guest_stay_fulfillment_settlement_eligibility": "0087_c049d2c650d7",
    "0088_post_stay_dispute_refund_reconciliation": "0088_226558bdb985",
    "0089_mother_plan_p0_product_patch": "0089_24184f9074aa",
    "0092_t20_subscription_finance_closure": "0092_d6ac03c98590",
    "0093_omnichannel_payment_finance_os": "0093_f656e2fd0f65",
    "0094_unified_money_movement_finance_close": "0094_c3116e73c367",
    "0095_supplier_multivertical_certification": "0095_59ac5a29f1d5",
    "0096_consumer_unified_lifecycle_projection": "0096_e63794766c0d",
    "0098_payment_truth_and_close_scope": "0098_1372d8c45b6f",
    "0099_order_money_supplier_atomic_truth": "0099_e9ab838ca46d",
    "0100_real_external_execution_certified_sandbox": "0100_159ffd29a7f8",
    "0101_named_provider_certification_postgres_race_proof": "0101_7ae44f334cf0",
    "0104_go_ai_multimodel_aggregation": "0104_529182b87c94",
    "0106_hotel_registration_official_association": "0106_449aeedcd91d",
    "0107_hotel_official_direct_semantics": "0107_166151c9cc6e",
    "0109_personal_travel_vault_universal_import": "0109_bf96588075fe",
    "0110_consumer_growth_official_direct_value": "0110_7012f1955180",
}
EXPECTED_REVISION_COUNT = 114
EXPECTED_HEAD = "0114_ext_truth_incident_hard"
EXPECTED_0111_PARENT = "0110_7012f1955180"
EXPECTED_0112_PARENT = "0111_test_account_expiry"
EXPECTED_0113_PARENT = "0112_ti_p0_20260829"
EXPECTED_0114_PARENT = "0113_ext_truth_ops_20260901"
EXPECTED_R7_SAFE_INDEX = "ix_recommendation_decision_gohs_version_id"
FORBIDDEN_OLD_INDEX = "ix_recommendation_decision_runtime_good_hotel_standard_version_id"

NAME_PATTERNS = [
    re.compile(r"op\.create_index\(\s*['\"]([^'\"]+)"),
    re.compile(r"op\.create_unique_constraint\(\s*['\"]([^'\"]+)"),
    re.compile(r"op\.create_foreign_key\(\s*['\"]([^'\"]+)"),
    re.compile(r"op\.create_check_constraint\(\s*['\"]([^'\"]+)"),
]


def literal_assignment(tree: ast.AST, name: str):
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        return None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            try:
                return ast.literal_eval(node.value)
            except Exception:
                return None
    return None


def main() -> int:
    revisions: dict[str, tuple[str | tuple | None, pathlib.Path]] = {}
    errors: list[str] = []
    for path in sorted(VERSIONS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            errors.append(f"SYNTAX:{path.name}:{exc}")
            continue
        revision = literal_assignment(tree, "revision")
        down_revision = literal_assignment(tree, "down_revision")
        if not isinstance(revision, str):
            errors.append(f"MISSING_REVISION:{path.name}")
            continue
        if revision in revisions:
            errors.append(f"DUPLICATE_REVISION:{revision}:{path.name}")
        revisions[revision] = (down_revision, path)
        if len(revision) > MAX_REVISION_LEN:
            errors.append(f"REVISION_TOO_LONG:{len(revision)}:{revision}:{path.name}")
        for pattern in NAME_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(1)
                if len(name) > MAX_PG_NAME_LEN:
                    errors.append(f"PG_OBJECT_NAME_TOO_LONG:{len(name)}:{name}:{path.name}")

    referenced: set[str] = set()
    for revision, (down, path) in revisions.items():
        parents = () if down is None else (down if isinstance(down, tuple) else (down,))
        for parent in parents:
            if not isinstance(parent, str):
                errors.append(f"INVALID_DOWN_REVISION:{revision}:{path.name}:{parent!r}")
                continue
            referenced.add(parent)
            if parent not in revisions:
                errors.append(f"MISSING_PARENT:{revision}->{parent}:{path.name}")
    heads = sorted(set(revisions) - referenced)
    if len(heads) != 1:
        errors.append("HEAD_COUNT:" + str(len(heads)) + ":" + ",".join(heads))
    if REQUIRED_COMPAT_REVISION not in revisions:
        errors.append(f"REQUIRED_R7_COMPAT_REVISION_MISSING:{REQUIRED_COMPAT_REVISION}")
    if len(revisions) != EXPECTED_REVISION_COUNT:
        errors.append(f"REVISION_COUNT_MISMATCH:{len(revisions)}!={EXPECTED_REVISION_COUNT}")
    if heads != [EXPECTED_HEAD]:
        errors.append(f"HEAD_MISMATCH:{','.join(heads)}!={EXPECTED_HEAD}")
    if REQUIRED_COMPAT_REVISION in revisions:
        actual_parent = revisions[REQUIRED_COMPAT_REVISION][0]
        if actual_parent != EXPECTED_0111_PARENT:
            errors.append(f"0111_PARENT_MISMATCH:{actual_parent}!={EXPECTED_0111_PARENT}")
    if '0112_ti_p0_20260829' in revisions:
        actual_parent = revisions['0112_ti_p0_20260829'][0]
        if actual_parent != EXPECTED_0112_PARENT:
            errors.append(f"0112_PARENT_MISMATCH:{actual_parent}!={EXPECTED_0112_PARENT}")
    if '0113_ext_truth_ops_20260901' in revisions:
        actual_parent = revisions['0113_ext_truth_ops_20260901'][0]
        if actual_parent != EXPECTED_0113_PARENT:
            errors.append(f"0113_PARENT_MISMATCH:{actual_parent}!={EXPECTED_0113_PARENT}")
    if EXPECTED_HEAD in revisions:
        actual_parent = revisions[EXPECTED_HEAD][0]
        if actual_parent != EXPECTED_0114_PARENT:
            errors.append(f"0114_PARENT_MISMATCH:{actual_parent}!={EXPECTED_0114_PARENT}")
    current_revisions = set(revisions)
    for old, short in EXPECTED_R7_SHORT_REVISIONS.items():
        if old in current_revisions:
            errors.append(f"LEGACY_LONG_REVISION_PRESENT:{old}")
        if short not in current_revisions:
            errors.append(f"R7_SHORT_REVISION_MISSING:{short}")
    r74 = (VERSIONS / "0074_good_hotel_standard_governance.py").read_text(encoding="utf-8")
    if EXPECTED_R7_SAFE_INDEX not in r74:
        errors.append(f"R7_SAFE_INDEX_MISSING:{EXPECTED_R7_SAFE_INDEX}")
    if FORBIDDEN_OLD_INDEX in r74:
        errors.append(f"LEGACY_LONG_INDEX_PRESENT:{FORBIDDEN_OLD_INDEX}")

    if errors:
        print("R8.2_MIGRATION_LINEAGE_GATE: BLOCK")
        for error in errors:
            print(error)
        return 1

    print(f"revision_count={len(revisions)}")
    print(f"head={heads[0]}")
    print(f"required_compat_revision={REQUIRED_COMPAT_REVISION}")
    print("R8.2_MIGRATION_LINEAGE_GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
