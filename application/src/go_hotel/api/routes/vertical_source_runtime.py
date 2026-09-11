from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service as svc
router=APIRouter(prefix='/internal/v1/vertical-source-decisions',tags=['vertical-source-runtime'])
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('')
def decide(b:P,p:Principal=Depends(admin_principal)):
 d=b.model_dump(exclude_none=True);return call(svc.decide,d['vertical'],d['business_id'],d.get('candidates',[]))
@router.get('/{vertical}/{business_id}')
def latest(vertical:str,business_id:str,p:Principal=Depends(admin_principal)):return {'data':svc.latest(vertical,business_id)}
