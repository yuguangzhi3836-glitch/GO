from fastapi import APIRouter,Depends,Header,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import consumer_principal,supplier_principal,admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.omnichannel_payment import ORDER_TYPES,omnichannel_payment_service as svc
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
router=APIRouter(tags=['omnichannel-payment-finance'])
@router.post('/v1/payments/intents')
def create(b:P,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(consumer_principal)):
 body=b.model_dump(exclude_none=True)
 if not isinstance(body.get('business_type'),str) or body['business_type'] not in ORDER_TYPES:
  raise HTTPException(409,detail='CONSUMER_AUTHORITATIVE_ORDER_REQUIRED')
 return call(svc.create_intent,body,idempotency_key,p.user_id)
@router.post('/v1/payments/intents/{iid}/channel')
def channel(iid:str,b:P,p:Principal=Depends(consumer_principal)):return call(svc.select_channel,iid,b.model_dump()['channel'],p.user_id,True)
@router.get('/v1/payments')
def mine(p:Principal=Depends(consumer_principal)):return {'data':svc.status(p.user_id)}
@router.get('/v1/payments/intents/{iid}/checkout-readiness')
def readiness(iid:str,p:Principal=Depends(consumer_principal)):return call(svc.checkout_readiness,iid,p.user_id)
@router.get('/v1/supplier/payment-finance')
def supplier(p:Principal=Depends(supplier_principal)):return {'data':svc.status(p.supplier_id)}
@router.post('/internal/v1/payments/merchant-bindings')
def bind(b:P,p:Principal=Depends(admin_principal)):return call(svc.bind,b.model_dump(exclude_none=True))
@router.post('/internal/v1/payments/intents/{iid}/execute')
def execute(iid:str,b:P,p:Principal=Depends(admin_principal)):return call(svc.execute,iid,b.model_dump(exclude_none=True).get('mode','CONTRACT_SIMULATOR'))
@router.post('/internal/v1/payments/attempts/{aid}/simulate')
def simulate(aid:str,b:P,p:Principal=Depends(admin_principal)):return call(svc.simulate_result,aid,b.model_dump()['result'])
@router.post('/internal/v1/payments/intents/{iid}/reconcile')
def reconcile(iid:str,b:P,p:Principal=Depends(admin_principal)):return call(svc.reconcile,iid,b.model_dump(exclude_none=True))
@router.post('/internal/v1/payments/intents/{iid}/psp-settlement-lines')
def psp_line(iid:str,b:P,p:Principal=Depends(admin_principal)):return call(svc.ingest_psp_line,iid,b.model_dump(exclude_none=True))
@router.post('/internal/v1/payments/bank-statement-lines')
def bank_line(b:P,p:Principal=Depends(admin_principal)):return call(svc.ingest_bank_line,b.model_dump(exclude_none=True))
@router.get('/internal/v1/payments/finance-status')
def finance(p:Principal=Depends(admin_principal)):return {'data':svc.status()}
@router.post('/v1/webhooks/payments/{channel}')
def webhook(channel:str,b:P,x_payment_signature:str=Header(alias='X-Payment-Signature')):return call(svc.webhook,channel,b.model_dump(exclude_none=True),x_payment_signature)
