from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import supplier_principal,admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.supplier_multivertical import supplier_multivertical_service as svc
router=APIRouter(tags=['supplier-multivertical-certification'])
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.put('/v1/supplier/verticals/{vertical}/capabilities/{capability}')
def configure(vertical:str,capability:str,b:P,p:Principal=Depends(supplier_principal)):return call(svc.configure,p.supplier_id,vertical,capability,b.model_dump(exclude_none=True))
@router.get('/v1/supplier/verticals')
def status(p:Principal=Depends(supplier_principal)):return {'data':svc.status(p.supplier_id)}
@router.post('/internal/v1/suppliers/{supplier_id}/verticals/{vertical}/certify')
def certify(supplier_id:str,vertical:str,b:P,p:Principal=Depends(admin_principal)):return call(svc.certify,supplier_id,vertical,b.model_dump(exclude_none=True),p.user_id)
