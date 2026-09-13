from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from datetime import datetime, timezone
import uuid
from go_hotel.observability.metrics import metrics
from go_hotel.observability.slo import current_slo_status
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import SecuritySignalRow, ReadinessGateRunRow
from go_hotel.security.deps import require_permission
from go_hotel.security.service import Principal, audit_service
from go_hotel.incident.service import incident_service, SWITCH_SCOPES
from go_hotel.core.config import settings

router=APIRouter(tags=["sprint1v-observability"])

def iso(v): return v.isoformat() if v else None

@router.get("/metrics",response_class=PlainTextResponse,include_in_schema=False)
def prometheus_metrics(): return metrics.prometheus()

@router.get("/internal/v1/ops/slo")
def slo_status(p:Principal=Depends(require_permission("admin:read"))): return {"data":{"slos":current_slo_status()}}

@router.get("/internal/v1/ops/incident-controls")
def incident_controls(p:Principal=Depends(require_permission("admin:read"))):
    rows=incident_service.list_switches(); existing={r.scope:r for r in rows}
    return {"data":{"items":[{"scope":x,"status":existing[x].status if x in existing else "INACTIVE","reason":existing[x].reason if x in existing else None,"activated_by":existing[x].activated_by if x in existing else None,"activated_at":iso(existing[x].activated_at) if x in existing else None} for x in sorted(SWITCH_SCOPES)]}}

class SwitchBody(BaseModel): reason:str
@router.post("/internal/v1/ops/incident-controls/{scope}/activate")
def activate_switch(scope:str,body:SwitchBody,p:Principal=Depends(require_permission("admin:approve"))):
    try:r=incident_service.set_switch(scope,True,p.user_id,body.reason)
    except ValueError as e: raise HTTPException(422,detail=str(e))
    audit_service.append(p,"KILL_SWITCH_ACTIVATED","INCIDENT_CONTROL",r.control_id,after={"scope":scope,"status":"ACTIVE","reason":body.reason})
    return {"data":{"scope":scope,"status":"ACTIVE"}}
@router.post("/internal/v1/ops/incident-controls/{scope}/deactivate")
def deactivate_switch(scope:str,body:SwitchBody,p:Principal=Depends(require_permission("admin:approve"))):
    try:r=incident_service.set_switch(scope,False,p.user_id,body.reason)
    except ValueError as e: raise HTTPException(422,detail=str(e))
    audit_service.append(p,"KILL_SWITCH_DEACTIVATED","INCIDENT_CONTROL",r.control_id,after={"scope":scope,"status":"INACTIVE","reason":body.reason})
    return {"data":{"scope":scope,"status":"INACTIVE"}}

@router.get("/internal/v1/security/signals")
def security_signals(status:str|None=None,p:Principal=Depends(require_permission("admin:read"))):
    with SessionLocal() as s:
        q=select(SecuritySignalRow)
        if status:q=q.where(SecuritySignalRow.status==status)
        rows=s.scalars(q.order_by(SecuritySignalRow.created_at.desc()).limit(200)).all()
        return {"data":{"items":[{"signal_id":r.signal_id,"type":r.signal_type,"severity":r.severity,"status":r.status,"request_id":r.request_id,"actor_id":r.actor_id,"client_ip":r.client_ip,"metadata":r.metadata_json,"created_at":iso(r.created_at)} for r in rows]}}

@router.get("/internal/v1/ops/readiness")
def readiness_preview(p:Principal=Depends(require_permission("admin:read"))): return {"data":_readiness_checks()}
@router.post("/internal/v1/ops/readiness/run")
def readiness_run(p:Principal=Depends(require_permission("admin:approve"))):
    data=_readiness_checks(); now=datetime.now(timezone.utc); run_id=f"gate_{uuid.uuid4().hex}"
    with SessionLocal() as s:
        s.add(ReadinessGateRunRow(run_id=run_id,environment=settings.app_env,status=data["status"],checks_json=data["checks"],blocker_count=data["blocker_count"],executed_by=p.user_id,created_at=now)); s.commit()
    audit_service.append(p,"PRODUCTION_READINESS_GATE_RUN","READINESS_GATE",run_id,after=data)
    return {"data":{"run_id":run_id,**data}}

def _readiness_checks():
    checks=[]
    def add(key,passed,blocker,detail): checks.append({"key":key,"passed":bool(passed),"blocker":bool(blocker),"detail":detail})
    try:
        with SessionLocal() as s:s.execute(text("SELECT 1")); db=True
    except Exception: db=False
    add("database_connectivity",db,True,"Database SELECT 1")
    add("jwt_key_not_default",settings.jwt_signing_key!="dev-only-change-me-jwt",True,"Production JWT signing key configured")
    add("vault_key_not_default",settings.connector_vault_master_key!="dev-only-change-me",True,"Connector vault master key configured")
    add("secure_cookie",settings.cookie_secure if settings.app_env=="production" else True,True,"Secure cookie required in production")
    add("admin_mfa",settings.mfa_required_for_admin if settings.app_env=="production" else True,True,"GO Admin MFA required in production")
    add("oidc_or_explicit_local",settings.oidc_enabled or settings.app_env!="production",False,"OIDC recommended for production admin access")
    add("active_global_kill_switch",not incident_service.active("GLOBAL_WRITES"),True,"GLOBAL_WRITES must be inactive before release")
    blockers=sum(1 for x in checks if x["blocker"] and not x["passed"])
    return {"environment":settings.app_env,"status":"PASS" if blockers==0 else "BLOCKED","blocker_count":blockers,"checks":checks}
