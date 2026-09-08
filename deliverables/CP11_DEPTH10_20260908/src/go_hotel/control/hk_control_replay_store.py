"""PostgreSQL durable replay/idempotency store for HK control tasks."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import uuid

from sqlalchemy import select, text

from go_hotel.db.models import HotelAutoPageEventRow
from go_hotel.db.session import SessionLocal

PREFIX = "HK_CONTROL_TASK_"


def _now(): return datetime.now(timezone.utc)
def _id(): return "hape_" + uuid.uuid4().hex

def _lock_key(task_id: str) -> int:
    raw = hashlib.sha256(("hk-control:" + task_id).encode()).digest()[:8]
    n = int.from_bytes(raw, "big", signed=False)
    return n - (1 << 64) if n >= (1 << 63) else n


def _lock(s, task_id: str):
    if s.get_bind().dialect.name != "postgresql":
        raise RuntimeError("HK_CONTROL_POSTGRES_REQUIRED")
    s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _lock_key(task_id)})


def _rows(s, task_id: str | None = None):
    rows = s.scalars(select(HotelAutoPageEventRow)
        .where(HotelAutoPageEventRow.event_type.like(PREFIX + "%"))
        .order_by(HotelAutoPageEventRow.created_at.asc())).all()
    if task_id is not None:
        rows = [r for r in rows if (r.evidence_json or {}).get("task_id") == task_id]
    return rows


def _fold(rows):
    tasks, nonces = {}, set()
    for row in rows:
        ev = dict(row.evidence_json or {})
        task_id = str(ev.get("task_id") or "")
        if not task_id: continue
        state = row.event_type[len(PREFIX):]
        if ev.get("nonce"): nonces.add(str(ev["nonce"]))
        current = dict(tasks.get(task_id) or {})
        current.update(ev); current["state"] = state
        tasks[task_id] = current
    return tasks, nonces


def _append(s, state: str, ev: dict):
    s.add(HotelAutoPageEventRow(
        hotel_auto_page_event_id=_id(), hotel_id=None,
        event_type=PREFIX + state, evidence_json=ev,
        actor="HK_CONTROL", created_at=_now()))


class PostgresControlReplayStore:
    def reserve(self, *, task_id: str, nonce: str, task_sha256: str, candidate_sha256: str) -> dict:
        with SessionLocal() as s:
            _lock(s, task_id)
            tasks, nonces = _fold(_rows(s))
            existing = tasks.get(task_id)
            if nonce in nonces and (not existing or existing.get("nonce") != nonce):
                raise ValueError("CONTROL_NONCE_REPLAY")
            if existing:
                if existing.get("task_sha256") != task_sha256 or existing.get("candidate_sha256") != candidate_sha256:
                    raise ValueError("CONTROL_TASK_ID_CONFLICT")
                if existing.get("state") == "COMPLETED":
                    return {"terminal": True, "response": existing.get("response")}
                if existing.get("state") == "RESERVED":
                    raise ValueError("CONTROL_TASK_ALREADY_IN_PROGRESS")
            _append(s, "RESERVED", {"task_id": task_id, "nonce": nonce,
                "task_sha256": task_sha256, "candidate_sha256": candidate_sha256})
            s.commit()
        return {"terminal": False}

    def complete(self, *, task_id: str, response: dict) -> None:
        with SessionLocal() as s:
            _lock(s, task_id)
            tasks, _ = _fold(_rows(s, task_id))
            current = tasks.get(task_id)
            if not current or current.get("state") != "RESERVED":
                raise ValueError("CONTROL_TASK_NOT_RESERVED")
            _append(s, "COMPLETED", {"task_id": task_id, "nonce": current.get("nonce"),
                "task_sha256": current.get("task_sha256"), "candidate_sha256": current.get("candidate_sha256"),
                "response": response})
            s.commit()
