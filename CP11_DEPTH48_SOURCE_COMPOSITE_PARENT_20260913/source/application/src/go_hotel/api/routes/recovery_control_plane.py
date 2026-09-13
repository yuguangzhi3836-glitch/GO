from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_control_plane import recovery_control_plane_service
from go_hotel.journey.recovery_sla import recovery_sla_service

router=APIRouter(tags=['sprint3k-recovery-sla-control-plane'])
class AssignBody(BaseModel):
    assigned_to:str
    note:str|None=None
class TransferBody(BaseModel):
    queue_key:str
    assigned_to:str|None=None
    note:str|None=None
class CloseBody(BaseModel):
    note:str|None=None

@router.get('/internal/v1/recovery/control-plane/cases')
def list_cases(state:str|None=None,limit:int=Query(100,ge=1,le=500),p:Principal=Depends(admin_principal)):
    return {'data':recovery_control_plane_service.list(state,limit)}
@router.get('/internal/v1/recovery/control-plane/cases/{case_id}')
def get_case(case_id:str,p:Principal=Depends(admin_principal)):
    try:return {'data':recovery_control_plane_service.detail(case_id)}
    except ValueError as e:raise HTTPException(404,detail=str(e))
@router.post('/internal/v1/recovery/control-plane/cases/{case_id}/assign')
def assign_case(case_id:str,body:AssignBody,p:Principal=Depends(admin_principal)):
    try:return {'data':recovery_control_plane_service.assign(case_id,p.user_id,body.assigned_to,body.note)}
    except ValueError as e:raise HTTPException(404,detail=str(e))
@router.post('/internal/v1/recovery/control-plane/cases/{case_id}/acknowledge')
def acknowledge_case(case_id:str,p:Principal=Depends(admin_principal)):
    try:return {'data':recovery_control_plane_service.acknowledge(case_id,p.user_id)}
    except ValueError as e:raise HTTPException(404,detail=str(e))
@router.get('/internal/v1/recovery/control-plane/sla-policies')
def sla_policies(p:Principal=Depends(admin_principal)):
    return {'data':{'items':recovery_sla_service.policies()}}
@router.get('/internal/v1/recovery/control-plane/queues')
def ops_queues(p:Principal=Depends(admin_principal)):
    return {'data':{'items':recovery_sla_service.queues()}}
@router.post('/internal/v1/recovery/control-plane/sla/tick')
def sla_tick(limit:int=Query(100,ge=1,le=500),p:Principal=Depends(admin_principal)):
    return {'data':recovery_sla_service.tick(limit)}
@router.post('/internal/v1/recovery/control-plane/cases/{case_id}/transfer')
def transfer_case(case_id:str,body:TransferBody,p:Principal=Depends(admin_principal)):
    try:
        recovery_sla_service.transfer(case_id,p.user_id,body.queue_key,body.assigned_to,body.note);return {'data':recovery_control_plane_service.detail(case_id)}
    except ValueError as e:raise HTTPException(404,detail=str(e))
@router.post('/internal/v1/recovery/control-plane/cases/{case_id}/close')
def close_case(case_id:str,body:CloseBody,p:Principal=Depends(admin_principal)):
    try:
        recovery_sla_service.close(case_id,p.user_id,body.note);return {'data':recovery_control_plane_service.detail(case_id)}
    except ValueError as e:
        msg=str(e);raise HTTPException(409 if msg.startswith('RECOVERY_CASE_RESOLUTION_EVIDENCE_REQUIRED') else 404,detail=msg)
