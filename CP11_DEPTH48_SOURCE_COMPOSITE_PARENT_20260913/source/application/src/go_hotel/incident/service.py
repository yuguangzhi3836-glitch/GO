from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import IncidentControlRow, SecuritySignalRow
import uuid

def utcnow(): return datetime.now(timezone.utc)

SWITCH_SCOPES={"GLOBAL_WRITES","BOOKING_WRITES","PAYMENT_WRITES","REFUND_WRITES","CONNECTOR_TRAFFIC","SUPPLIER_CONSOLE_WRITES","ADMIN_HIGH_RISK_WRITES"}

class IncidentControlService:
    def list_switches(self):
        with SessionLocal() as s:
            return s.scalars(select(IncidentControlRow).order_by(IncidentControlRow.scope)).all()
    def active(self,scope:str)->bool:
        with SessionLocal() as s:
            r=s.scalar(select(IncidentControlRow).where(IncidentControlRow.scope==scope,IncidentControlRow.status=="ACTIVE")); return bool(r)
    def set_switch(self,scope:str,active:bool,actor_id:str,reason:str,expires_at=None):
        if scope not in SWITCH_SCOPES: raise ValueError("UNKNOWN_SWITCH_SCOPE")
        with SessionLocal() as s:
            r=s.scalar(select(IncidentControlRow).where(IncidentControlRow.scope==scope))
            if not r:
                r=IncidentControlRow(control_id=f"ctl_{uuid.uuid4().hex}",scope=scope,status="INACTIVE",reason=None,activated_by=None,activated_at=None,expires_at=None,updated_at=utcnow()); s.add(r)
            r.status="ACTIVE" if active else "INACTIVE"; r.reason=reason; r.activated_by=actor_id; r.activated_at=utcnow() if active else r.activated_at; r.expires_at=expires_at; r.updated_at=utcnow(); s.commit(); s.refresh(r); return r
    def record_security_signal(self,signal_type:str,severity:str,request_id:str|None=None,actor_id:str|None=None,client_ip:str|None=None,metadata:dict|None=None):
        with SessionLocal() as s:
            r=SecuritySignalRow(signal_id=f"sec_{uuid.uuid4().hex}",signal_type=signal_type,severity=severity,status="OPEN",request_id=request_id,actor_id=actor_id,client_ip=client_ip,metadata_json=metadata or {},created_at=utcnow()); s.add(r); s.commit(); return r

incident_service=IncidentControlService()
