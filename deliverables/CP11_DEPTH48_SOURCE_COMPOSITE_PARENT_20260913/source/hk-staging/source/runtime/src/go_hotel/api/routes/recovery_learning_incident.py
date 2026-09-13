from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_learning_incident import recovery_learning_incident_service as svc
router=APIRouter(tags=['sprint3q-recovery-learning-incident'])
class OpenBody(BaseModel):
    scope_type:str;scope_key:str='*';severity:str='SEV2';reason:str
class PostmortemBody(BaseModel):
    evidence_reference:str;summary:str;root_cause:str;corrective_actions:list[str]=Field(default_factory=list)
class ResumeRequestBody(BaseModel):
    change_window_start:datetime;change_window_end:datetime;resume_plan:dict=Field(default_factory=dict)
class CloseBody(BaseModel): closure_evidence_reference:str

def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/recovery/learning/incidents')
def open_incident(b:OpenBody,p:Principal=Depends(admin_principal)):return call(svc.open_incident,b.scope_type,b.scope_key,b.severity,b.reason,p.user_id)
@router.get('/internal/v1/recovery/learning/incidents')
def incidents(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.list()}}
@router.get('/internal/v1/recovery/learning/incidents/{incident_id}')
def incident(incident_id:str,p:Principal=Depends(admin_principal)):return call(svc.get,incident_id)
@router.post('/internal/v1/recovery/learning/incidents/{incident_id}/postmortem')
def postmortem(incident_id:str,b:PostmortemBody,p:Principal=Depends(admin_principal)):return call(svc.add_postmortem,incident_id,b.evidence_reference,b.summary,b.root_cause,b.corrective_actions,p.user_id)
@router.post('/internal/v1/recovery/learning/incidents/{incident_id}/resume-requests')
def request_resume(incident_id:str,b:ResumeRequestBody,p:Principal=Depends(admin_principal)):return call(svc.request_resume,incident_id,b.change_window_start,b.change_window_end,b.resume_plan,p.user_id)
@router.post('/internal/v1/recovery/learning/change-requests/{change_request_id}/approve')
def approve(change_request_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_resume,change_request_id,p.user_id)
@router.post('/internal/v1/recovery/learning/change-requests/{change_request_id}/execute')
def execute(change_request_id:str,p:Principal=Depends(admin_principal)):return call(svc.execute_resume,change_request_id,p.user_id,None)
@router.post('/internal/v1/recovery/learning/incidents/{incident_id}/close')
def close(incident_id:str,b:CloseBody,p:Principal=Depends(admin_principal)):return call(svc.close_incident,incident_id,p.user_id,b.closure_evidence_reference)
