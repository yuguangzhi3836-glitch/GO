from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.production_connectors import production_connector_service as svc

router=APIRouter(prefix='/internal/v1/production-connectors',tags=['production-connector-control-plane'])
class Payload(BaseModel): model_config={'extra':'allow'}
def call(fn,*args):
 try: return {'data':fn(*args)}
 except ValueError as exc: raise HTTPException(409,detail=str(exc))

@router.get('/dashboard')
def dashboard(p:Principal=Depends(admin_principal)): return {'data':svc.dashboard()}
@router.post('')
def register(b:Payload,p:Principal=Depends(admin_principal)): return call(svc.register,b.model_dump(exclude_none=True),p.user_id)
@router.post('/{connector_id}/capabilities')
def capabilities(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)): return call(svc.bind_capabilities,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/{connector_id}/authority')
def authority(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)): return call(svc.bind_authority,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/{connector_id}/credential-references')
def credential(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)): return call(svc.bind_credential,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/{connector_id}/certifications')
def certification(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)): return call(svc.record_certification,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.put('/{connector_id}/runtime-health')
def health(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)): return call(svc.bind_health,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/{connector_id}/live-gate-assessments')
def gate(connector_id:str,p:Principal=Depends(admin_principal)): return call(svc.assess_live_gate,connector_id,p.user_id)
@router.post('/{connector_id}/activation-changes')
def request_activation(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)): return call(svc.request_activation,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/activation-changes/{change_id}/approve')
def approve_activation(change_id:str,p:Principal=Depends(admin_principal)): return call(svc.approve_activation,change_id,p.user_id)
@router.put('/{connector_id}/kill-switch')
def kill_switch(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)): return call(svc.set_kill_switch,connector_id,b.model_dump(exclude_none=True),p.user_id)
