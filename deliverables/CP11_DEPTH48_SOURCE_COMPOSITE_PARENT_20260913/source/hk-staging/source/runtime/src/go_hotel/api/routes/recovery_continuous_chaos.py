from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_continuous_chaos import recovery_continuous_chaos_service as svc
router=APIRouter(tags=['sprint4e-continuous-chaos-waiver-governance'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class ScheduleBody(BaseModel): environment:str='PROD';schedule_key:str;cadence_seconds:int=Field(ge=60);scenarios:list[dict]
class WaiverBody(BaseModel): environment:str='PROD';reason:str;risk_summary:str;evidence_reference:str;risk_acceptor:str;starts_at:datetime;expires_at:datetime;remediation_owner:str|None=None;remediation_summary:str|None=None
@router.post('/internal/v1/recovery/runtime/trust-plane/chaos/schedules')
def schedule(b:ScheduleBody,p:Principal=Depends(admin_principal)):return call(svc.create_schedule,b.environment,b.schedule_key,b.cadence_seconds,b.scenarios,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/chaos/scheduler/tick')
def tick(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.tick,environment,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/trend/evaluate')
def trend(environment:str='PROD',p:Principal=Depends(admin_principal)):return call(svc.evaluate_trend,environment,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/waivers')
def waiver(b:WaiverBody,p:Principal=Depends(admin_principal)):return call(svc.request_waiver,b.environment,b.reason,b.risk_summary,b.evidence_reference,b.risk_acceptor,b.starts_at,b.expires_at,p.user_id,b.remediation_owner,b.remediation_summary)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/waivers/{waiver_id}/approve')
def approve(waiver_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_waiver,waiver_id,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/continuous-status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
