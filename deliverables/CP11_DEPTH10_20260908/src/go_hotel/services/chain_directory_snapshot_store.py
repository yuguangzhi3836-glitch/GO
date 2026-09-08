"""PostgreSQL durable authority for hierarchical directory discovery/checkpoints.

The client cursor contains only a small opaque snapshot id. Frontier, visited aliases,
discovered properties, page digests, frozen inventory and emission offset live in
PostgreSQL. Checkpoints are append-only and protected by a PostgreSQL advisory lock.
No process-local or client-carried full directory state is authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import uuid

from sqlalchemy import select, text

from go_hotel.db.models import HotelAutoPageEventRow
from go_hotel.db.session import SessionLocal

PREFIX = "CHAIN_DIRECTORY_SNAPSHOT_"


def _now(): return datetime.now(timezone.utc)
def _event_id(): return "hape_" + uuid.uuid4().hex
def _snapshot_id(): return "dirsnap_" + uuid.uuid4().hex
def _lock_key(snapshot_id: str) -> int:
    raw = hashlib.sha256(("chain-directory:" + snapshot_id).encode()).digest()[:8]
    value = int.from_bytes(raw, "big", signed=False)
    return value - (1 << 64) if value >= (1 << 63) else value


def _lock(session, snapshot_id: str) -> None:
    if session.get_bind().dialect.name != "postgresql":
        raise RuntimeError("CHAIN_DIRECTORY_POSTGRES_REQUIRED")
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _lock_key(snapshot_id)})


def _rows(session, snapshot_id: str):
    rows = session.scalars(
        select(HotelAutoPageEventRow)
        .where(HotelAutoPageEventRow.event_type.like(PREFIX + "%"))
        .order_by(HotelAutoPageEventRow.created_at.asc(), HotelAutoPageEventRow.hotel_auto_page_event_id.asc())
    ).all()
    return [r for r in rows if str((r.evidence_json or {}).get("snapshot_id") or "") == snapshot_id]


def _append(session, state_name: str, payload: dict, actor: str) -> None:
    session.add(HotelAutoPageEventRow(
        hotel_auto_page_event_id=_event_id(),
        hotel_id=None,
        event_type=PREFIX + state_name,
        evidence_json=payload,
        actor=actor,
        created_at=_now(),
    ))


def _state_sha(state: dict) -> str:
    raw = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class DirectorySnapshotView:
    snapshot_id: str
    chain: str
    state: dict
    revision: int
    state_sha256: str


class PostgresDirectorySnapshotStore:
    def create(self, *, chain: str, initial_state: dict, actor: str = "SYSTEM") -> DirectorySnapshotView:
        if not chain or not isinstance(initial_state, dict):
            raise ValueError("CHAIN_DIRECTORY_SNAPSHOT_CREATE_INVALID")
        snapshot_id = _snapshot_id()
        state = dict(initial_state)
        digest = _state_sha(state)
        with SessionLocal() as s:
            _lock(s, snapshot_id)
            _append(s, "CHECKPOINT", {
                "snapshot_id": snapshot_id,
                "chain": chain,
                "revision": 1,
                "state_sha256": digest,
                "state": state,
            }, actor)
            s.commit()
        return DirectorySnapshotView(snapshot_id, chain, state, 1, digest)

    def load(self, *, snapshot_id: str, expected_chain: str | None = None) -> DirectorySnapshotView:
        with SessionLocal() as s:
            rows = _rows(s, snapshot_id)
        if not rows:
            raise ValueError("CHAIN_DIRECTORY_SNAPSHOT_NOT_FOUND")
        last = dict(rows[-1].evidence_json or {})
        chain = str(last.get("chain") or "")
        if expected_chain is not None and chain != expected_chain:
            raise ValueError("CHAIN_DIRECTORY_SNAPSHOT_CHAIN_MISMATCH")
        state = last.get("state")
        if not isinstance(state, dict):
            raise ValueError("CHAIN_DIRECTORY_SNAPSHOT_STATE_INVALID")
        digest = _state_sha(state)
        if digest != last.get("state_sha256"):
            raise ValueError("CHAIN_DIRECTORY_SNAPSHOT_DIGEST_MISMATCH")
        return DirectorySnapshotView(snapshot_id, chain, state, int(last.get("revision") or 0), digest)

    def checkpoint(self, *, snapshot_id: str, expected_revision: int, state: dict, actor: str = "SYSTEM") -> DirectorySnapshotView:
        if not isinstance(state, dict):
            raise ValueError("CHAIN_DIRECTORY_SNAPSHOT_STATE_INVALID")
        with SessionLocal() as s:
            _lock(s, snapshot_id)
            rows = _rows(s, snapshot_id)
            if not rows:
                raise ValueError("CHAIN_DIRECTORY_SNAPSHOT_NOT_FOUND")
            last = dict(rows[-1].evidence_json or {})
            current_revision = int(last.get("revision") or 0)
            if current_revision != int(expected_revision):
                raise ValueError("CHAIN_DIRECTORY_SNAPSHOT_REVISION_CONFLICT")
            chain = str(last.get("chain") or "")
            revision = current_revision + 1
            digest = _state_sha(state)
            _append(s, "CHECKPOINT", {
                "snapshot_id": snapshot_id,
                "chain": chain,
                "revision": revision,
                "state_sha256": digest,
                "state": dict(state),
            }, actor)
            s.commit()
        return DirectorySnapshotView(snapshot_id, chain, dict(state), revision, digest)

    def checkpoint_count(self, snapshot_id: str) -> int:
        with SessionLocal() as s:
            return len(_rows(s, snapshot_id))


postgres_directory_snapshot_store = PostgresDirectorySnapshotStore()
