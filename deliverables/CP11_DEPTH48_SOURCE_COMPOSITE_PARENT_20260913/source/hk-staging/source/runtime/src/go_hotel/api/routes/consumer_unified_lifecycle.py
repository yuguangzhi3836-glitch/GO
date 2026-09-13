from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import consumer_principal,admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service as svc
router=APIRouter(tags=['consumer-unified-multivertical-lifecycle'])
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/consumer-lifecycle/project')
def project(b:P,p:Principal=Depends(admin_principal)):return call(svc.project,b.model_dump(exclude_none=True))
@router.get('/v1/consumer/unified-trips')
def trips(p:Principal=Depends(consumer_principal)):return {'data':{'items':svc.list(p.user_id)}}
@router.get('/v1/consumer/unified-trips/{lid}')
def detail(lid:str,p:Principal=Depends(consumer_principal)):return call(svc.detail,p.user_id,lid)
