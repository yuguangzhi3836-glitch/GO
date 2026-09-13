from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_data_governance import recovery_data_governance_service as svc
router=APIRouter(tags=['sprint3p-recovery-data-governance'])
class MappingBody(BaseModel): vertical:str;adapter_key:str;supplier_id:str
class KillBody(BaseModel): scope_type:str;scope_key:str;enabled:bool;reason:str|None=None
@router.post('/internal/v1/recovery/learning/data-quality/tick')
def quality_tick(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.assess_quality()}}
@router.get('/internal/v1/recovery/learning/data-quality')
def quality(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.quality()}}
@router.get('/internal/v1/recovery/learning/quarantine')
def quarantine(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.quarantines()}}
@router.post('/internal/v1/recovery/learning/supplier-mappings')
def mapping(b:MappingBody,p:Principal=Depends(admin_principal)):return {'data':svc.upsert_supplier_mapping(b.vertical,b.adapter_key,b.supplier_id,p.user_id)}
@router.get('/internal/v1/recovery/learning/supplier-mappings')
def mappings(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.mappings()}}
@router.get('/internal/v1/recovery/learning/privacy-budgets')
def budgets(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.privacy_budgets()}}
@router.post('/internal/v1/recovery/learning/kill-switches')
def kill(b:KillBody,p:Principal=Depends(admin_principal)):
    # Sprint 3Q: direct Admin mutation is intentionally blocked. Incident/change-control owns production stop/resume.
    raise HTTPException(409,detail='USE_LEARNING_INCIDENT_CHANGE_CONTROL')
@router.get('/internal/v1/recovery/learning/kill-switches')
def kills(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.switches()}}
