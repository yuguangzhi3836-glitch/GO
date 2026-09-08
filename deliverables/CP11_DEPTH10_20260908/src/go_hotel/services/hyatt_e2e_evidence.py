"""Strict machine-readable evidence matrix for the Hyatt 10-hotel gate.

This evaluator never infers PASS from a READY build alone. The runtime producer must
supply explicit evidence for catalog parity, media isolation, durable media, LKG,
idempotency and recovery. Missing evidence is HOLD.
"""
from __future__ import annotations

REQUIRED_SCENES = {"EXTERIOR", "LOBBY", "DINING", "WELLNESS", "MEETING"}


def _bool(value):
    return value is True


def evaluate_hotel_evidence(record: dict) -> dict:
    checks = {}
    checks["ready"] = record.get("build_state") == "READY"
    checks["identity_unique"] = _bool(record.get("identity_unique"))
    checks["catalog_parity"] = (
        isinstance(record.get("official_room_type_ids"), list)
        and isinstance(record.get("go_room_type_ids"), list)
        and len(record["official_room_type_ids"]) > 0
        and set(record["official_room_type_ids"]) == set(record["go_room_type_ids"])
        and len(record["go_room_type_ids"]) == len(set(record["go_room_type_ids"]))
    )
    checks["room_media_isolation"] = _bool(record.get("room_media_isolation")) and int(record.get("room_media_cross_bind_count") or 0) == 0
    scenes = {str(x).upper() for x in (record.get("hotel_scene_categories") or [])}
    checks["hotel_scene_media"] = REQUIRED_SCENES.issubset(scenes) or _bool(record.get("scene_gap_explicit_and_unborrowed"))
    checks["durable_media"] = (
        _bool(record.get("durable_media_ledger"))
        and int(record.get("missing_blob_count") or 0) == 0
        and int(record.get("corrupt_blob_count") or 0) == 0
        and int(record.get("published_without_rights_count") or 0) == 0
    )
    checks["lkg_protected"] = _bool(record.get("lkg_protected"))
    checks["idempotent_reruns"] = (
        int(record.get("rerun_count") or 0) >= 2
        and int(record.get("duplicate_hotel_count") or 0) == 0
        and int(record.get("duplicate_room_count") or 0) == 0
        and int(record.get("unintended_page_proliferation_count") or 0) == 0
    )
    checks["forced_kill_recovery"] = (
        _bool(record.get("forced_kill_observed"))
        and _bool(record.get("lease_reclaimed"))
        and int(record.get("terminal_ack_count") or 0) == 1
    )
    passed = all(checks.values())
    return {"status": "PASS" if passed else "HOLD", "checks": checks}


def evaluate_cohort(records: list[dict]) -> dict:
    if len(records) != 10:
        return {"status": "HOLD", "reason": "HYATT_COHORT_MUST_BE_EXACTLY_10", "count": len(records), "hotels": []}
    hotels = []
    unique_property_ids = set()
    for record in records:
        property_id = str(record.get("property_id") or "")
        if not property_id or property_id in unique_property_ids:
            return {"status": "HOLD", "reason": "HYATT_COHORT_PROPERTY_ID_INVALID_OR_DUPLICATE", "property_id": property_id, "hotels": hotels}
        unique_property_ids.add(property_id)
        result = evaluate_hotel_evidence(record)
        hotels.append({"property_id": property_id, **result})
    passed = all(x["status"] == "PASS" for x in hotels)
    return {
        "status": "PASS" if passed else "HOLD",
        "count": len(records),
        "pass_count": sum(1 for x in hotels if x["status"] == "PASS"),
        "hold_count": sum(1 for x in hotels if x["status"] != "PASS"),
        "hotels": hotels,
    }
