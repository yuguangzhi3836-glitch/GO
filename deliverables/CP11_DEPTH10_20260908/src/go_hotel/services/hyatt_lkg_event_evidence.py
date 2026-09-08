"""Derive Hyatt LKG protection strictly from persisted page/publication events.

A producer-supplied boolean is insufficient. PASS requires an observed failed
candidate while a previously active version remains active after the failure. Event
history is read from PostgreSQL and evaluated in order; missing or ambiguous evidence
stays HOLD.
"""
from __future__ import annotations

from sqlalchemy import select

from go_hotel.db.models import HotelAutoPageEventRow
from go_hotel.db.session import SessionLocal

PAGE_TOKENS = ("PAGE", "LKG", "PUBLISH", "GOLDEN", "AUTO_PAGE")
FAILED_STATES = {"FAILED", "HOLD", "REJECTED", "BLOCKED", "ERROR"}
ACTIVE_STATES = {"PUBLISHED", "ACTIVE", "LIVE", "PROMOTED"}


def _version(ev: dict) -> str | None:
    for key in ("candidate_version", "page_version", "version", "failed_candidate_version"):
        value = ev.get(key)
        if value:
            return str(value)
    return None


def derive_lkg_evidence(*, hotel_id: str) -> dict:
    if not hotel_id:
        return {"lkg_protected": False, "lkg_evidence_source": "UNAVAILABLE", "reason": "HOTEL_ID_REQUIRED"}
    with SessionLocal() as s:
        rows = s.scalars(
            select(HotelAutoPageEventRow)
            .where(HotelAutoPageEventRow.hotel_id == hotel_id)
            .order_by(HotelAutoPageEventRow.created_at.asc(), HotelAutoPageEventRow.hotel_auto_page_event_id.asc())
        ).all()
    current_active = None
    failures = []
    publication_events = 0
    for row in rows:
        event_type = str(row.event_type or "").upper()
        if not any(token in event_type for token in PAGE_TOKENS):
            continue
        ev = dict(row.evidence_json or {})
        state = str(ev.get("publication_state") or ev.get("state") or ev.get("status") or "").upper()
        explicit_active = ev.get("active_page_version")
        previous = ev.get("previous_page_version")
        failed = ev.get("failed_candidate_version")
        candidate = _version(ev)
        is_failed = bool(failed) or state in FAILED_STATES or "FAIL" in event_type or "REJECT" in event_type
        is_active = bool(explicit_active) or state in ACTIVE_STATES or "PUBLISH" in event_type or "PROMOT" in event_type
        if is_active or is_failed:
            publication_events += 1
        active_before = str(previous) if previous else current_active
        if is_failed:
            failed_version = str(failed or candidate or "") or None
            active_after = str(explicit_active) if explicit_active else current_active
            protected = bool(active_before and active_after and active_before == active_after and failed_version and failed_version != active_after)
            failures.append({
                "event_id": str(row.hotel_auto_page_event_id),
                "failed_candidate_version": failed_version,
                "active_before": active_before,
                "active_after": active_after,
                "protected": protected,
            })
            if explicit_active:
                current_active = str(explicit_active)
            continue
        if explicit_active:
            current_active = str(explicit_active)
        elif is_active and candidate:
            current_active = str(candidate)
    qualifying = [x for x in failures if x["protected"]]
    return {
        "lkg_protected": bool(qualifying) and len(qualifying) == len(failures),
        "lkg_evidence_source": "POSTGRES_PUBLICATION_EVENT_LEDGER",
        "publication_event_count": publication_events,
        "failed_candidate_count": len(failures),
        "protected_failure_count": len(qualifying),
        "active_page_version": current_active,
        "failure_evidence": failures,
        "reason": None if failures else "NO_FAILED_CANDIDATE_EVENT_OBSERVED",
    }
