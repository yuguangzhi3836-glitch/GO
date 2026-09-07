"""PostgreSQL-backed durable media metadata ledger for multi-worker hotel builds.

This replaces the correctness role previously played by a process-local JSON index.
Binary media files remain immutable content-addressed objects; authoritative metadata,
rights state and publication state are recorded transactionally in PostgreSQL via the
existing HotelAutoPageEventRow event stream. Advisory transaction locks serialize
mutations for the same asset across workers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import uuid

from sqlalchemy import select, text

from go_hotel.db.models import HotelAutoPageEventRow
from go_hotel.db.session import SessionLocal


PREFIX = "MEDIA_INDEX_"
PUBLISHABLE_RIGHTS = {"AUTHORIZED", "HOTEL_SUBMITTED", "LICENSED", "DISTRIBUTION_LICENSE", "PUBLIC_DOMAIN"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ident() -> str:
    return "hape_" + uuid.uuid4().hex


def _lock_key(asset_id: str) -> int:
    raw = hashlib.sha256(("media:" + asset_id).encode("utf-8")).digest()[:8]
    value = int.from_bytes(raw, "big", signed=False)
    return value - (1 << 64) if value >= (1 << 63) else value


def _pg_lock(session, asset_id: str) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _lock_key(asset_id)})


def _event(session, state: str, payload: dict, actor: str):
    session.add(HotelAutoPageEventRow(
        hotel_auto_page_event_id=_ident(),
        hotel_id=payload.get("hotel_id"),
        event_type=PREFIX + state,
        evidence_json=payload,
        actor=actor,
        created_at=_now(),
    ))


def _rows(session, asset_id: str | None = None):
    rows = session.scalars(
        select(HotelAutoPageEventRow)
        .where(HotelAutoPageEventRow.event_type.like(PREFIX + "%"))
        .order_by(HotelAutoPageEventRow.created_at.asc())
    ).all()
    if asset_id is not None:
        rows = [r for r in rows if (r.evidence_json or {}).get("asset_id") == asset_id]
    return rows


def _is_publishable(record: dict) -> bool:
    return (
        record.get("cache_state") == "VALIDATED"
        and record.get("rights_state") in PUBLISHABLE_RIGHTS
        and bool(record.get("rights_owner"))
        and bool(record.get("rights_evidence_reference"))
        and record.get("publication_state") != "REVOKED"
    )


def _fold(rows) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        ev = dict(row.evidence_json or {})
        asset_id = str(ev.get("asset_id") or "")
        if not asset_id:
            continue
        state = row.event_type[len(PREFIX):]
        if state == "REGISTERED":
            current = dict(ev.get("record") or {})
            current["asset_id"] = asset_id
            out[asset_id] = current
        elif asset_id in out and state == "RIGHTS_DECIDED":
            current = dict(out[asset_id])
            current.update(dict(ev.get("rights") or {}))
            out[asset_id] = current
        elif asset_id in out and state == "PUBLICATION_CHANGED":
            current = dict(out[asset_id])
            current["publication_state"] = ev.get("publication_state")
            out[asset_id] = current
        elif asset_id in out and state == "REVOKED":
            current = dict(out[asset_id])
            current["publication_state"] = "REVOKED"
            current["revoke_reason"] = ev.get("reason")
            out[asset_id] = current
    for record in out.values():
        record["publishable"] = _is_publishable(record)
    return out


@dataclass(frozen=True)
class DurableMediaIndexService:
    def register(self, record: dict, *, actor: str = "SYSTEM") -> dict:
        required = {"asset_id", "hotel_id", "sha256", "cache_file", "cache_state", "role"}
        if not isinstance(record, dict) or any(not record.get(k) for k in required):
            raise ValueError("MEDIA_INDEX_RECORD_INCOMPLETE")
        asset_id = str(record["asset_id"])
        with SessionLocal() as s:
            _pg_lock(s, asset_id)
            current = _fold(_rows(s, asset_id)).get(asset_id)
            if current:
                immutable = ("hotel_id", "sha256", "cache_file", "role", "room_type_id")
                if any(current.get(k) != record.get(k) for k in immutable):
                    raise ValueError("MEDIA_INDEX_ASSET_ID_CONFLICT")
                s.commit()
                return current
            clean = dict(record)
            clean.setdefault("rights_state", "RIGHTS_UNKNOWN")
            clean.setdefault("publication_state", "HOLD")
            _event(s, "REGISTERED", {"asset_id": asset_id, "hotel_id": clean.get("hotel_id"), "record": clean}, actor)
            s.commit()
        return self.get(asset_id)

    def decide_rights(self, asset_id: str, *, rights_state: str, actor: str,
                      rights_owner: str | None = None, evidence_reference: str | None = None,
                      rights_basis: str | None = None) -> dict:
        state = str(rights_state or "").upper()
        if state in PUBLISHABLE_RIGHTS and (not rights_owner or not evidence_reference):
            raise ValueError("MEDIA_INDEX_PUBLISHABLE_RIGHTS_EVIDENCE_REQUIRED")
        with SessionLocal() as s:
            _pg_lock(s, asset_id)
            current = _fold(_rows(s, asset_id)).get(asset_id)
            if not current:
                raise ValueError("MEDIA_INDEX_ASSET_NOT_FOUND")
            rights = {
                "rights_state": state,
                "rights_owner": rights_owner,
                "rights_evidence_reference": evidence_reference,
                "rights_basis": rights_basis,
                "rights_decided_by": actor,
                "rights_decided_at": _now().isoformat(),
            }
            _event(s, "RIGHTS_DECIDED", {"asset_id": asset_id, "hotel_id": current.get("hotel_id"), "rights": rights}, actor)
            s.commit()
        return self.get(asset_id)

    def set_publication(self, asset_id: str, *, publish: bool, actor: str = "SYSTEM") -> dict:
        with SessionLocal() as s:
            _pg_lock(s, asset_id)
            current = _fold(_rows(s, asset_id)).get(asset_id)
            if not current:
                raise ValueError("MEDIA_INDEX_ASSET_NOT_FOUND")
            if publish and not _is_publishable(current):
                raise ValueError("MEDIA_INDEX_ASSET_NOT_PUBLISHABLE")
            state = "PUBLISHED" if publish else "HOLD"
            _event(s, "PUBLICATION_CHANGED", {"asset_id": asset_id, "hotel_id": current.get("hotel_id"), "publication_state": state}, actor)
            s.commit()
        return self.get(asset_id)

    def revoke(self, asset_id: str, *, reason: str, actor: str = "SYSTEM") -> dict:
        with SessionLocal() as s:
            _pg_lock(s, asset_id)
            current = _fold(_rows(s, asset_id)).get(asset_id)
            if not current:
                raise ValueError("MEDIA_INDEX_ASSET_NOT_FOUND")
            _event(s, "REVOKED", {"asset_id": asset_id, "hotel_id": current.get("hotel_id"), "reason": str(reason)[:1000]}, actor)
            s.commit()
        return self.get(asset_id)

    def get(self, asset_id: str) -> dict:
        with SessionLocal() as s:
            current = _fold(_rows(s, asset_id)).get(asset_id)
        if not current:
            raise ValueError("MEDIA_INDEX_ASSET_NOT_FOUND")
        return current

    def list_assets(self, *, hotel_id: str | None = None, room_type_id: str | None = None,
                    publishable_only: bool = False) -> list[dict]:
        with SessionLocal() as s:
            values = list(_fold(_rows(s)).values())
        if hotel_id:
            values = [x for x in values if x.get("hotel_id") == hotel_id]
        if room_type_id:
            values = [x for x in values if x.get("room_type_id") == room_type_id]
        if publishable_only:
            values = [x for x in values if x.get("publishable")]
        return sorted(values, key=lambda x: (x.get("hotel_id") or "", x.get("role") or "", x.get("asset_id") or ""))


durable_media_index_service = DurableMediaIndexService()
