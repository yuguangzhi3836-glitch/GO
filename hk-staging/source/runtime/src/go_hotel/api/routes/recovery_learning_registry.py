from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_learning_registry import recovery_learning_registry_service as svc
router=APIRouter(tags=['sprint3o-recovery-learning-registry'])
class RebuildBody(BaseModel): ttl_days:int=30;anonymization_k:int=3
@router.get('/internal/v1/recovery/learning/registry')
def registry(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.list_registry()}}
@router.post('/internal/v1/recovery/learning/rebuild')
def rebuild(b:RebuildBody,p:Principal=Depends(admin_principal)):return {'data':{'benchmarks':svc.rebuild_benchmarks(b.ttl_days,b.anonymization_k),'registry':svc.rebuild_registry(b.ttl_days)}}
@router.get('/internal/v1/recovery/learning/registry/{registry_id}/provenance')
def provenance(registry_id:str,p:Principal=Depends(admin_principal)):
    try:return {'data':svc.graph(registry_id)}
    except ValueError as e:raise HTTPException(404,str(e))
@router.get('/internal/v1/recovery/learning/benchmarks')
def benchmarks(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.benchmarks()}}
@router.post('/internal/v1/recovery/learning/drift/tick')
def drift_tick(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.assess_drift()}}
@router.get('/internal/v1/recovery/learning/drift')
def drift(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.drift_history()}}
@router.post('/internal/v1/recovery/learning/registry/{registry_id}/revalidate')
def revalidate(registry_id:str,p:Principal=Depends(admin_principal)):
    try:return {'data':svc.revalidate(registry_id,p.user_id)}
    except ValueError as e:raise HTTPException(409,str(e))
