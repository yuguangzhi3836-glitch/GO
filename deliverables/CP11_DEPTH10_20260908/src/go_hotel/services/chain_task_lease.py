"""Persistent chain-hotel task ledger using existing HotelAutoPageEventRow.

The previous regional Redis BRPOP path removes a message before work is durably
acknowledged. This ledger makes the DB event stream the durable source of truth:
enqueue -> claim(lease) -> heartbeat -> ack, with retry/dead-letter semantics.

PostgreSQL advisory transaction locks serialize claims across workers without a
new table. Expired leases become claimable again, so worker death is recoverable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import uuid

from sqlalchemy import select, text

from go_hotel.db.models import HotelAutoPageEventRow
from go_hotel.db.session import SessionLocal


EVENT_PREFIX = "CHAIN_BUILD_TASK_"
TERMINAL = {"ACKED", "DEAD"}
CLAIMABLE = {"QUEUED", "RETRY_WAIT", "LEASED"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ident() -> str:
    return "hape_" + uuid.uuid4().hex


def _lock_key(task_id: str) -> int:
    raw = hashlib.sha256(task_id.encode("utf-8")).digest()[:8]
    value = int.from_bytes(raw, "big", signed=False)
    return value - (1 << 64) if value >= (1 << 63) else value


def _event_name(state: str) -> str:
    return EVENT_PREFIX + state


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class TaskView:
    task_id: str
    state: str
    payload: dict
    attempt: int
    worker_id: str | None
    lease_until: datetime | None
    retry_at: datetime | None
    last_error: str | None

    def claimable(self, at: datetime) -> bool:
        if self.state == "QUEUED":
            return True
        if self.state == "RETRY_WAIT":
            return self.retry_at is None or self.retry_at <= at
        if self.state == "LEASED":
            return self.lease_until is None or self.lease_until <= at
        return False


def _fold(rows) -> dict[str, TaskView]:
    state: dict[str, TaskView] = {}
    for row in rows:
        ev = row.evidence_json or {}
        task_id = str(ev.get("task_id") or "")
        if not task_id:
            continue
        event_state = row.event_type[len(EVENT_PREFIX):] if row.event_type.startswith(EVENT_PREFIX) else ""
        previous = state.get(task_id)
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else (previous.payload if previous else {})
        attempt = int(ev.get("attempt") if ev.get("attempt") is not None else (previous.attempt if previous else 0))
        state[task_id] = TaskView(
            task_id=task_id,
            state=event_state,
            payload=payload,
            attempt=attempt,
            worker_id=ev.get("worker_id"),
            lease_until=_parse_time(ev.get("lease_until")),
            retry_at=_parse_time(ev.get("retry_at")),
            last_error=ev.get("error") or (previous.last_error if previous else None),
        )
    return state


def _append(s, state: str, evidence: dict, actor: str = "SYSTEM"):
    s.add(HotelAutoPageEventRow(
        hotel_auto_page_event_id=_ident(),
        hotel_id=evidence.get("hotel_id"),
        event_type=_event_name(state),
        evidence_json=evidence,
        actor=actor,
        created_at=_now(),
    ))


def _events(s, task_id: str | None = None):
    rows = s.scalars(
        select(HotelAutoPageEventRow)
        .where(HotelAutoPageEventRow.event_type.like(EVENT_PREFIX + "%"))
        .order_by(HotelAutoPageEventRow.created_at.asc())
    ).all()
    if task_id is not None:
        rows = [r for r in rows if (r.evidence_json or {}).get("task_id") == task_id]
    return rows


def _pg_try_lock(s, task_id: str) -> bool:
    dialect = s.get_bind().dialect.name
    if dialect != "postgresql":
        # Durable semantics are production-approved only on PostgreSQL. Tests and
        # local dev can still exercise state folding, but multi-process claim
        # safety must not be asserted on SQLite.
        return True
    return bool(s.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _lock_key(task_id)}).scalar())


class ChainTaskLeaseService:
    def enqueue(self, *, task_id: str, payload: dict, actor: str = "SYSTEM") -> TaskView:
        if not task_id or not isinstance(payload, dict):
            raise ValueError("CHAIN_TASK_INVALID")
        with SessionLocal() as s:
            if not _pg_try_lock(s, task_id):
                raise ValueError("CHAIN_TASK_BUSY")
            current = _fold(_events(s, task_id)).get(task_id)
            if current and current.state not in {"DEAD"}:
                s.commit()
                return current
            _append(s, "QUEUED", {"task_id": task_id, "payload": payload, "attempt": 0}, actor)
            s.commit()
        return self.get(task_id)

    def get(self, task_id: str) -> TaskView:
        with SessionLocal() as s:
            current = _fold(_events(s, task_id)).get(task_id)
        if current is None:
            raise ValueError("CHAIN_TASK_NOT_FOUND")
        return current

    def list(self) -> list[TaskView]:
        with SessionLocal() as s:
            return list(_fold(_events(s)).values())

    def claim(self, *, worker_id: str, lease_seconds: int = 120, actor: str = "SYSTEM") -> TaskView | None:
        if not worker_id or not 15 <= int(lease_seconds) <= 900:
            raise ValueError("CHAIN_TASK_LEASE_INVALID")
        at = _now()
        # Candidate scan is followed by a transaction advisory lock and re-read,
        # so two workers cannot successfully claim the same task on PostgreSQL.
        candidates = sorted(
            (x for x in self.list() if x.claimable(at)),
            key=lambda x: (x.retry_at or datetime.min.replace(tzinfo=timezone.utc), x.task_id),
        )
        for candidate in candidates:
            with SessionLocal() as s:
                if not _pg_try_lock(s, candidate.task_id):
                    continue
                current = _fold(_events(s, candidate.task_id)).get(candidate.task_id)
                now = _now()
                if current is None or not current.claimable(now):
                    s.commit()
                    continue
                attempt = current.attempt + 1
                lease_until = now + timedelta(seconds=int(lease_seconds))
                _append(s, "LEASED", {
                    "task_id": current.task_id,
                    "payload": current.payload,
                    "attempt": attempt,
                    "worker_id": worker_id,
                    "lease_until": _iso(lease_until),
                }, actor)
                s.commit()
            return self.get(candidate.task_id)
        return None

    def heartbeat(self, *, task_id: str, worker_id: str, lease_seconds: int = 120, actor: str = "SYSTEM") -> TaskView:
        if not 15 <= int(lease_seconds) <= 900:
            raise ValueError("CHAIN_TASK_LEASE_INVALID")
        with SessionLocal() as s:
            if not _pg_try_lock(s, task_id):
                raise ValueError("CHAIN_TASK_BUSY")
            current = _fold(_events(s, task_id)).get(task_id)
            now = _now()
            if current is None or current.state != "LEASED" or current.worker_id != worker_id:
                raise ValueError("CHAIN_TASK_LEASE_OWNERSHIP_REQUIRED")
            if current.lease_until and current.lease_until <= now:
                raise ValueError("CHAIN_TASK_LEASE_EXPIRED")
            lease_until = now + timedelta(seconds=int(lease_seconds))
            _append(s, "LEASED", {
                "task_id": task_id,
                "payload": current.payload,
                "attempt": current.attempt,
                "worker_id": worker_id,
                "lease_until": _iso(lease_until),
            }, actor)
            s.commit()
        return self.get(task_id)

    def ack(self, *, task_id: str, worker_id: str, result: dict | None = None, actor: str = "SYSTEM") -> TaskView:
        with SessionLocal() as s:
            if not _pg_try_lock(s, task_id):
                raise ValueError("CHAIN_TASK_BUSY")
            current = _fold(_events(s, task_id)).get(task_id)
            now = _now()
            if current is None or current.state != "LEASED" or current.worker_id != worker_id:
                raise ValueError("CHAIN_TASK_LEASE_OWNERSHIP_REQUIRED")
            if current.lease_until and current.lease_until <= now:
                raise ValueError("CHAIN_TASK_LEASE_EXPIRED")
            _append(s, "ACKED", {
                "task_id": task_id,
                "payload": current.payload,
                "attempt": current.attempt,
                "worker_id": worker_id,
                "result": result or {},
            }, actor)
            s.commit()
        return self.get(task_id)

    def fail(self, *, task_id: str, worker_id: str, error: str, retryable: bool = True,
             max_attempts: int = 5, actor: str = "SYSTEM") -> TaskView:
        if not 1 <= int(max_attempts) <= 10:
            raise ValueError("CHAIN_TASK_MAX_ATTEMPTS_INVALID")
        with SessionLocal() as s:
            if not _pg_try_lock(s, task_id):
                raise ValueError("CHAIN_TASK_BUSY")
            current = _fold(_events(s, task_id)).get(task_id)
            if current is None or current.state != "LEASED" or current.worker_id != worker_id:
                raise ValueError("CHAIN_TASK_LEASE_OWNERSHIP_REQUIRED")
            terminal = (not retryable) or current.attempt >= int(max_attempts)
            if terminal:
                _append(s, "DEAD", {
                    "task_id": task_id,
                    "payload": current.payload,
                    "attempt": current.attempt,
                    "worker_id": worker_id,
                    "error": str(error)[:4000],
                }, actor)
            else:
                delay = min(900, 5 * (2 ** max(0, current.attempt - 1)))
                retry_at = _now() + timedelta(seconds=delay)
                _append(s, "RETRY_WAIT", {
                    "task_id": task_id,
                    "payload": current.payload,
                    "attempt": current.attempt,
                    "worker_id": worker_id,
                    "error": str(error)[:4000],
                    "retry_at": _iso(retry_at),
                }, actor)
            s.commit()
        return self.get(task_id)


chain_task_lease_service = ChainTaskLeaseService()
