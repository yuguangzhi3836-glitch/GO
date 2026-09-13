from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from sqlalchemy import select
from go_hotel.db.models import JourneyRecoveryEvidenceChainRow
from go_hotel.domain.models import new_id


def now():
    return datetime.now(timezone.utc)


def _stable_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def append_vertical_evidence(session, vertical: str, order_id: str, kind: str, observed_status: str | None, payload: dict | None = None, source: str = "RC20_VERTICAL"):
    execution_id = f"rc20:{vertical}:{order_id}"
    execution_item_id = order_id
    last = session.scalar(
        select(JourneyRecoveryEvidenceChainRow)
        .where(JourneyRecoveryEvidenceChainRow.execution_id == execution_id)
        .order_by(JourneyRecoveryEvidenceChainRow.sequence_no.desc())
    )
    seq = (last.sequence_no if last else 0) + 1
    prev = last.entry_hash if last else "GENESIS"
    body = {
        "vertical": vertical,
        "order_id": order_id,
        "kind": kind,
        "status": observed_status,
        "payload": payload or {},
        "previous_hash": prev,
        "sequence_no": seq,
    }
    ev_hash = _stable_hash(body)
    entry_hash = _stable_hash({"evidence_hash": ev_hash, "previous_hash": prev, "sequence_no": seq})
    row = JourneyRecoveryEvidenceChainRow(
        evidence_chain_id=new_id("rc20ev"),
        execution_id=execution_id,
        execution_item_id=execution_item_id,
        supplier_operation_id=None,
        sequence_no=seq,
        evidence_kind=kind[:48],
        source=source[:24],
        external_event_id=None,
        external_operation_id=None,
        supplier_confirmation_id=(payload or {}).get("supplier_reference") or (payload or {}).get("booking_reference") or (payload or {}).get("pnr"),
        observed_status=observed_status,
        evidence_hash=ev_hash,
        previous_hash=prev,
        entry_hash=entry_hash,
        evidence_json=body,
        created_at=now(),
    )
    session.add(row)
    session.flush()
    return row


def list_vertical_evidence(session, vertical: str, order_id: str):
    execution_id = f"rc20:{vertical}:{order_id}"
    rows = session.scalars(
        select(JourneyRecoveryEvidenceChainRow)
        .where(JourneyRecoveryEvidenceChainRow.execution_id == execution_id)
        .order_by(JourneyRecoveryEvidenceChainRow.sequence_no)
    ).all()
    return [{
        "sequence_no": r.sequence_no,
        "kind": r.evidence_kind,
        "status": r.observed_status,
        "source": r.source,
        "entry_hash": r.entry_hash,
        "previous_hash": r.previous_hash,
        "payload": r.evidence_json.get("payload", {}) if isinstance(r.evidence_json, dict) else {},
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
