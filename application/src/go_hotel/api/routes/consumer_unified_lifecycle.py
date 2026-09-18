from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import consumer_principal,admin_principal,connector_admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service as svc
from go_hotel.services.consumer_trip_index import list_trips
router=APIRouter(tags=['consumer-unified-multivertical-lifecycle'])
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a,**kwargs):
 try:return {'data':fn(*a,**kwargs)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/internal/v1/consumer-lifecycle/project')
def project(b:P,p:Principal=Depends(admin_principal)):return call(svc.project,b.model_dump(exclude_none=True))
@router.get('/v1/consumer/unified-trips')
def trips(p:Principal=Depends(consumer_principal)):
 try:return {'data':{'items':list_trips(p.user_id)}}
 except ValueError as e:
  raise HTTPException(503 if 'PROVIDER_TRUTH_REQUIRED' in str(e) else 409,detail=str(e))
@router.post('/v1/consumer/unified-trips/external-orders',status_code=201)
def import_external_order(b:P,p:Principal=Depends(consumer_principal)):return call(svc.import_external_order,p.user_id,b.model_dump(exclude_none=True),trusted_provider=False)
@router.post('/internal/v1/consumer-lifecycle/external-orders/project')
def project_external_order(b:P,p:Principal=Depends(connector_admin_principal)):
 data=b.model_dump(exclude_none=True);account_id=data.pop('account_id',None);adapter_id=data.pop('adapter_id',None)
 if not account_id:raise HTTPException(422,detail='ACCOUNT_ID_REQUIRED')
 return call(svc.import_external_order,account_id,data,trusted_provider=True,adapter_id=adapter_id)
@router.get('/v1/consumer/unified-trips/{lid}')
def detail(lid:str,p:Principal=Depends(consumer_principal)):return call(svc.detail,p.user_id,lid)
