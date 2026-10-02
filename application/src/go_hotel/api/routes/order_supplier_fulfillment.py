from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal, order_admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as svc
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
router=APIRouter(tags=['p0-order-money-supplier-truth'])
@router.get('/internal/v1/order-supplier-fulfillments/{fid}')
def get(fid:str,p:Principal=Depends(admin_principal)):return call(svc.get,fid)
@router.post('/internal/v1/order-supplier-fulfillments/{fid}/supplier-fact')
def fact(fid:str,b:P,p:Principal=Depends(order_admin_principal)):return call(svc.record_supplier_fact,fid,b.model_dump(exclude_none=True)|{'actor_id':p.user_id})
