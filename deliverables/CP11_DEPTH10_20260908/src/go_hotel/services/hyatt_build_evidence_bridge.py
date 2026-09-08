"""Bridge explicit Hyatt build outputs into the durable E2E evidence stream.

Only fields explicitly emitted by owning production subsystems are persisted. This
module never invents parity/LKG/media facts from READY. Missing fields stay missing
and therefore keep the Hyatt acceptance matrix on HOLD.
"""
from __future__ import annotations

from .hyatt_runtime_evidence import hyatt_runtime_evidence_service as evidence


def _list(value):
    return list(value) if isinstance(value, (list, tuple, set)) else None


def record_hyatt_build_evidence(*, task_id: str, payload: dict, result: dict, actor: str = "SYSTEM") -> dict:
    if payload.get("chain") != "HYATT":
        return {"recorded": False, "reason": "NOT_HYATT"}
    property_id = str(payload.get("official_property_id") or "").strip()
    hotel_id = str(result.get("hotel_id") or "").strip()
    if not property_id or not hotel_id:
        return {"recorded": False, "reason": "IDENTITY_NOT_AVAILABLE"}

    recorded = []
    if result.get("canonical_match_count") is not None:
        evidence.record_identity(property_id=property_id, hotel_id=hotel_id,
            canonical_match_count=int(result["canonical_match_count"]), actor=actor)
        recorded.append("IDENTITY")

    official_rooms = _list(result.get("official_room_type_ids"))
    go_rooms = _list(result.get("go_room_type_ids"))
    if official_rooms is not None and go_rooms is not None:
        evidence.record_catalog(property_id=property_id, hotel_id=hotel_id,
            official_room_type_ids=[str(x) for x in official_rooms],
            go_room_type_ids=[str(x) for x in go_rooms], actor=actor)
        recorded.append("CATALOG")

    if result.get("room_media_cross_bind_count") is not None and result.get("room_bindings_checked") is not None:
        evidence.record_room_media(property_id=property_id, hotel_id=hotel_id,
            cross_bind_count=int(result["room_media_cross_bind_count"]),
            room_bindings_checked=int(result["room_bindings_checked"]), actor=actor)
        recorded.append("ROOM_MEDIA")

    scenes = _list(result.get("hotel_scene_categories"))
    if scenes is not None:
        evidence.record_scenes(property_id=property_id, hotel_id=hotel_id,
            categories=[str(x) for x in scenes],
            explicit_unborrowed_gap=result.get("scene_gap_explicit_and_unborrowed") is True,
            actor=actor)
        recorded.append("SCENES")

    lkg = result.get("lkg_evidence")
    if isinstance(lkg, dict) and "protected" in lkg:
        evidence.record_lkg(property_id=property_id, hotel_id=hotel_id,
            protected=lkg.get("protected") is True,
            previous_page_version=lkg.get("previous_page_version"),
            failed_candidate_version=lkg.get("failed_candidate_version"),
            active_page_version=lkg.get("active_page_version"), actor=actor)
        recorded.append("LKG")

    evidence.record(kind="BUILD_RUN", property_id=property_id, hotel_id=hotel_id,
        payload={"task_id": task_id, "job_id": result.get("job_id"),
                 "build_state": result.get("build_state"),
                 "page_version": result.get("page_version"),
                 "go_room_type_ids": [str(x) for x in (go_rooms or [])]}, actor=actor)
    recorded.append("BUILD_RUN")
    return {"recorded": True, "kinds": recorded}
