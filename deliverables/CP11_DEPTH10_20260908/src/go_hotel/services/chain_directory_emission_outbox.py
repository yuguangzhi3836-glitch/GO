"""Crash-safe PostgreSQL outbox for directory emission -> task enqueue.

A frozen directory page is PREPARED before any business task is enqueued. If the
process dies before/during enqueue or before checkpoint commit, the same prepared
page is replayed from PostgreSQL. Chain task ids are deterministic/idempotent, so
replay cannot create duplicate business tasks. The snapshot emission offset advances
only after all seeds were enqueued.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import uuid

from sqlalchemy import select, text

from go_hotel.db.models import HotelAutoPageEventRow
from go_hotel.db.session import SessionLocal

PREFIX="CHAIN_DIRECTORY_EMISSION_"

def _now(): return datetime.now(timezone.utc)
def _id(): return "hape_"+uuid.uuid4().hex
def _lock_key(snapshot_id:str)->int:
    raw=hashlib.sha256(("chain-directory:"+snapshot_id).encode()).digest()[:8]
    value=int.from_bytes(raw,"big",signed=False)
    return value-(1<<64) if value>=(1<<63) else value

def _lock(s,snapshot_id):
    if s.get_bind().dialect.name!="postgresql":raise RuntimeError("CHAIN_DIRECTORY_POSTGRES_REQUIRED")
    s.execute(text("SELECT pg_advisory_xact_lock(:k)"),{"k":_lock_key(snapshot_id)})

def _rows(s,snapshot_id,base_revision=None):
    rows=s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type.like(PREFIX+"%")).order_by(HotelAutoPageEventRow.created_at.asc(),HotelAutoPageEventRow.hotel_auto_page_event_id.asc())).all()
    out=[r for r in rows if str((r.evidence_json or {}).get("snapshot_id") or "")==snapshot_id]
    if base_revision is not None:out=[r for r in out if int((r.evidence_json or {}).get("base_revision") or -1)==int(base_revision)]
    return out

def _sha(value)->str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def _append(s,state,payload,actor):
    s.add(HotelAutoPageEventRow(hotel_auto_page_event_id=_id(),hotel_id=None,event_type=PREFIX+state,evidence_json=payload,actor=actor,created_at=_now()))

class DirectoryEmissionOutbox:
    def prepare(self,*,snapshot_id,chain,base_revision,seeds,next_state,complete,actor="SYSTEM"):
        seed_rows=[{"chain":x.chain.value,"official_property_id":x.official_property_id,"name":x.name,"property_url":x.property_url,"directory_url":x.directory_url,"country_code":x.country_code,"city":x.city} for x in seeds]
        payload_core={"snapshot_id":snapshot_id,"chain":chain,"base_revision":int(base_revision),"seeds":seed_rows,"next_state":next_state,"complete":bool(complete)}
        digest=_sha(payload_core)
        with SessionLocal() as s:
            _lock(s,snapshot_id);rows=_rows(s,snapshot_id,base_revision)
            prepared=[dict(r.evidence_json or {}) for r in rows if r.event_type==PREFIX+"PREPARED"]
            if prepared:
                existing=prepared[-1]
                if existing.get("batch_sha256")!=digest:raise ValueError("CHAIN_DIRECTORY_EMISSION_BATCH_CONFLICT")
                s.commit();return existing
            event={**payload_core,"batch_sha256":digest,"status":"PREPARED"};_append(s,"PREPARED",event,actor);s.commit();return event
    def load_prepared(self,*,snapshot_id,base_revision):
        with SessionLocal() as s:rows=_rows(s,snapshot_id,base_revision)
        prepared=[dict(r.evidence_json or {}) for r in rows if r.event_type==PREFIX+"PREPARED"]
        if not prepared:return None
        event=prepared[-1];committed=[r for r in rows if r.event_type==PREFIX+"COMMITTED"]
        event["committed"]=bool(committed);return event
    def mark_committed(self,*,snapshot_id,base_revision,committed_revision,state_sha256,actor="SYSTEM"):
        with SessionLocal() as s:
            _lock(s,snapshot_id);rows=_rows(s,snapshot_id,base_revision)
            if not any(r.event_type==PREFIX+"PREPARED" for r in rows):raise ValueError("CHAIN_DIRECTORY_EMISSION_NOT_PREPARED")
            existing=[dict(r.evidence_json or {}) for r in rows if r.event_type==PREFIX+"COMMITTED"]
            if existing:
                last=existing[-1]
                if int(last.get("committed_revision") or -1)!=int(committed_revision) or last.get("state_sha256")!=state_sha256:raise ValueError("CHAIN_DIRECTORY_EMISSION_COMMIT_CONFLICT")
                s.commit();return last
            event={"snapshot_id":snapshot_id,"base_revision":int(base_revision),"committed_revision":int(committed_revision),"state_sha256":state_sha256,"status":"COMMITTED"};_append(s,"COMMITTED",event,actor);s.commit();return event

chain_directory_emission_outbox=DirectoryEmissionOutbox()
