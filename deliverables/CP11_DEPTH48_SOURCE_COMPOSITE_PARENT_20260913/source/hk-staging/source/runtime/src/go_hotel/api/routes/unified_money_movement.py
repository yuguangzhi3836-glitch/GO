from fastapi import APIRouter,Depends,Header,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.unified_money_movement import unified_money_movement_service as svc
router=APIRouter(prefix='/internal/v1/finance',tags=['unified-money-movement-finance-close'])
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/payment-intents/{iid}/movements')
def movement(iid:str,b:P,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(admin_principal)):return call(svc.create,iid,b.model_dump(exclude_none=True),idempotency_key,p.user_id)
@router.post('/scoped-closes')
def close(b:P,p:Principal=Depends(admin_principal)):return call(svc.prepare_close,b.model_dump(exclude_none=True),p.user_id)
@router.post('/scoped-closes/{cid}/approve')
def approve(cid:str,p:Principal=Depends(admin_principal)):return call(svc.approve_close,cid,p.user_id)
@router.get('/status')
def status(p:Principal=Depends(admin_principal)):return {'data':svc.status()}
