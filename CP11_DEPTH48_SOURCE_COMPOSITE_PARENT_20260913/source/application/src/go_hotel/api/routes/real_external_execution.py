from fastapi import APIRouter,Depends,HTTPException,Header
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.real_external_execution import real_external_execution_service as svc
router=APIRouter(tags=['p0-0100-real-external-execution'])
class Payload(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/internal/v1/p0/0100/readiness')
def readiness(p:Principal=Depends(admin_principal)):return {'data':svc.readiness()}
@router.post('/internal/v1/p0/0100/payment-intents/{intent_id}/execute')
def payment_execute(intent_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.execute_payment,intent_id,b.model_dump()['execution_authorization_id'],b.model_dump(exclude_none=True))
@router.post('/internal/v1/p0/0100/fulfillments/{fulfillment_id}/execute')
def supplier_execute(fulfillment_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.execute_supplier,fulfillment_id,b.model_dump()['execution_authorization_id'],b.model_dump(exclude_none=True))
@router.post('/v1/webhooks/p0/0100/payment/{operation_id}')
def payment_callback(operation_id:str,b:Payload,x_go_delivery_id:str=Header(alias='X-GO-Delivery-ID'),x_go_signature_sha256:str=Header(alias='X-GO-Signature-SHA256')):return call(svc.payment_callback,operation_id,x_go_delivery_id,b.model_dump(exclude_none=True),x_go_signature_sha256)
@router.post('/v1/webhooks/p0/0100/supplier/{operation_id}')
def supplier_callback(operation_id:str,b:Payload,x_go_delivery_id:str=Header(alias='X-GO-Delivery-ID'),x_go_signature_sha256:str=Header(alias='X-GO-Signature-SHA256')):return call(svc.supplier_callback,operation_id,x_go_delivery_id,b.model_dump(exclude_none=True),x_go_signature_sha256)
@router.post('/v1/webhooks/p0/0100/psp-settlement/{operation_id}')
def settlement_callback(operation_id:str,b:Payload,x_go_delivery_id:str=Header(alias='X-GO-Delivery-ID'),x_go_signature_sha256:str=Header(alias='X-GO-Signature-SHA256')):return call(svc.psp_settlement_callback,operation_id,x_go_delivery_id,b.model_dump(exclude_none=True),x_go_signature_sha256)
@router.post('/v1/webhooks/p0/0100/bank-feed/{provider_key}')
def bank_feed(provider_key:str,b:Payload,x_go_delivery_id:str=Header(alias='X-GO-Delivery-ID'),x_go_signature_sha256:str=Header(alias='X-GO-Signature-SHA256')):return call(svc.bank_feed,provider_key,x_go_delivery_id,b.model_dump(exclude_none=True),x_go_signature_sha256)
@router.post('/internal/v1/p0/0100/payment-intents/{intent_id}/reconcile')
def reconcile(intent_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.reconcile,intent_id,b.model_dump()['external_transaction_id'])
