"""Persistent hotel-build task ledger using existing HotelAutoPageEventRow.

DB event stream is the durable authority: enqueue -> claim(lease) -> heartbeat ->
ack, with retry/dead-letter semantics. Claims can be partitioned by task_type so
regional and chain workers cannot steal each other's work.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib, uuid
from sqlalchemy import select, text
from go_hotel.db.models import HotelAutoPageEventRow
from go_hotel.db.session import SessionLocal

EVENT_PREFIX="CHAIN_BUILD_TASK_"; TERMINAL={"ACKED","DEAD"}

def _now(): return datetime.now(timezone.utc)
def _ident(): return "hape_"+uuid.uuid4().hex
def _lock_key(task_id):
    v=int.from_bytes(hashlib.sha256(task_id.encode()).digest()[:8],"big")
    return v-(1<<64) if v >= (1<<63) else v
def _event_name(s): return EVENT_PREFIX+s
def _iso(v): return v.astimezone(timezone.utc).isoformat() if v else None
def _parse_time(v):
    if not v:return None
    d=v if isinstance(v,datetime) else datetime.fromisoformat(str(v).replace("Z","+00:00"))
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

@dataclass(frozen=True)
class TaskView:
    task_id:str; state:str; payload:dict; attempt:int; worker_id:str|None; lease_until:datetime|None; retry_at:datetime|None; last_error:str|None
    @property
    def task_type(self): return str(self.payload.get("task_type") or "")
    def claimable(self,at):
        return self.state=="QUEUED" or (self.state=="RETRY_WAIT" and (self.retry_at is None or self.retry_at<=at)) or (self.state=="LEASED" and (self.lease_until is None or self.lease_until<=at))

def _fold(rows):
    state={}
    for row in rows:
        ev=row.evidence_json or {}; tid=str(ev.get("task_id") or "")
        if not tid:continue
        st=row.event_type[len(EVENT_PREFIX):] if row.event_type.startswith(EVENT_PREFIX) else ""
        prev=state.get(tid); payload=ev.get("payload") if isinstance(ev.get("payload"),dict) else (prev.payload if prev else {})
        attempt=int(ev.get("attempt") if ev.get("attempt") is not None else (prev.attempt if prev else 0))
        state[tid]=TaskView(tid,st,payload,attempt,ev.get("worker_id"),_parse_time(ev.get("lease_until")),_parse_time(ev.get("retry_at")),ev.get("error") or (prev.last_error if prev else None))
    return state

def _append(s,state,evidence,actor="SYSTEM"):
    s.add(HotelAutoPageEventRow(hotel_auto_page_event_id=_ident(),hotel_id=evidence.get("hotel_id"),event_type=_event_name(state),evidence_json=evidence,actor=actor,created_at=_now()))
def _events(s,task_id=None):
    rows=s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type.like(EVENT_PREFIX+"%")).order_by(HotelAutoPageEventRow.created_at.asc())).all()
    return [r for r in rows if (r.evidence_json or {}).get("task_id")==task_id] if task_id is not None else rows
def _pg_try_lock(s,task_id):
    if s.get_bind().dialect.name!="postgresql":return True
    return bool(s.execute(text("SELECT pg_try_advisory_xact_lock(:k)"),{"k":_lock_key(task_id)}).scalar())

class ChainTaskLeaseService:
    def enqueue(self,*,task_id,payload,actor="SYSTEM"):
        if not task_id or not isinstance(payload,dict) or not str(payload.get("task_type") or ""):raise ValueError("CHAIN_TASK_INVALID")
        with SessionLocal() as s:
            if not _pg_try_lock(s,task_id):raise ValueError("CHAIN_TASK_BUSY")
            cur=_fold(_events(s,task_id)).get(task_id)
            if cur and cur.state!="DEAD":s.commit();return cur
            _append(s,"QUEUED",{"task_id":task_id,"payload":payload,"attempt":0},actor);s.commit()
        return self.get(task_id)
    def get(self,task_id):
        with SessionLocal() as s:cur=_fold(_events(s,task_id)).get(task_id)
        if cur is None:raise ValueError("CHAIN_TASK_NOT_FOUND")
        return cur
    def list(self):
        with SessionLocal() as s:return list(_fold(_events(s)).values())
    def claim(self,*,worker_id,lease_seconds=120,actor="SYSTEM",task_type=None):
        if not worker_id or not 15<=int(lease_seconds)<=900:raise ValueError("CHAIN_TASK_LEASE_INVALID")
        at=_now(); candidates=sorted((x for x in self.list() if x.claimable(at) and (task_type is None or x.task_type==task_type)),key=lambda x:(x.retry_at or datetime.min.replace(tzinfo=timezone.utc),x.task_id))
        for candidate in candidates:
            with SessionLocal() as s:
                if not _pg_try_lock(s,candidate.task_id):continue
                cur=_fold(_events(s,candidate.task_id)).get(candidate.task_id);now=_now()
                if cur is None or not cur.claimable(now) or (task_type is not None and cur.task_type!=task_type):s.commit();continue
                attempt=cur.attempt+1;until=now+timedelta(seconds=int(lease_seconds));_append(s,"LEASED",{"task_id":cur.task_id,"payload":cur.payload,"attempt":attempt,"worker_id":worker_id,"lease_until":_iso(until)},actor);s.commit()
            return self.get(candidate.task_id)
        return None
    def heartbeat(self,*,task_id,worker_id,lease_seconds=120,actor="SYSTEM"):
        if not 15<=int(lease_seconds)<=900:raise ValueError("CHAIN_TASK_LEASE_INVALID")
        with SessionLocal() as s:
            if not _pg_try_lock(s,task_id):raise ValueError("CHAIN_TASK_BUSY")
            cur=_fold(_events(s,task_id)).get(task_id);now=_now()
            if cur is None or cur.state!="LEASED" or cur.worker_id!=worker_id:raise ValueError("CHAIN_TASK_LEASE_OWNERSHIP_REQUIRED")
            if cur.lease_until and cur.lease_until<=now:raise ValueError("CHAIN_TASK_LEASE_EXPIRED")
            _append(s,"LEASED",{"task_id":task_id,"payload":cur.payload,"attempt":cur.attempt,"worker_id":worker_id,"lease_until":_iso(now+timedelta(seconds=int(lease_seconds)))},actor);s.commit()
        return self.get(task_id)
    def ack(self,*,task_id,worker_id,result=None,actor="SYSTEM"):
        with SessionLocal() as s:
            if not _pg_try_lock(s,task_id):raise ValueError("CHAIN_TASK_BUSY")
            cur=_fold(_events(s,task_id)).get(task_id);now=_now()
            if cur is None or cur.state!="LEASED" or cur.worker_id!=worker_id:raise ValueError("CHAIN_TASK_LEASE_OWNERSHIP_REQUIRED")
            if cur.lease_until and cur.lease_until<=now:raise ValueError("CHAIN_TASK_LEASE_EXPIRED")
            _append(s,"ACKED",{"task_id":task_id,"payload":cur.payload,"attempt":cur.attempt,"worker_id":worker_id,"result":result or {}},actor);s.commit()
        return self.get(task_id)
    def fail(self,*,task_id,worker_id,error,retryable=True,max_attempts=5,actor="SYSTEM"):
        if not 1<=int(max_attempts)<=10:raise ValueError("CHAIN_TASK_MAX_ATTEMPTS_INVALID")
        with SessionLocal() as s:
            if not _pg_try_lock(s,task_id):raise ValueError("CHAIN_TASK_BUSY")
            cur=_fold(_events(s,task_id)).get(task_id)
            if cur is None or cur.state!="LEASED" or cur.worker_id!=worker_id:raise ValueError("CHAIN_TASK_LEASE_OWNERSHIP_REQUIRED")
            if (not retryable) or cur.attempt>=int(max_attempts):_append(s,"DEAD",{"task_id":task_id,"payload":cur.payload,"attempt":cur.attempt,"worker_id":worker_id,"error":str(error)[:4000]},actor)
            else:
                retry=_now()+timedelta(seconds=min(900,5*(2**max(0,cur.attempt-1))));_append(s,"RETRY_WAIT",{"task_id":task_id,"payload":cur.payload,"attempt":cur.attempt,"worker_id":worker_id,"error":str(error)[:4000],"retry_at":_iso(retry)},actor)
            s.commit()
        return self.get(task_id)

chain_task_lease_service=ChainTaskLeaseService()
