from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.connector_activation_readiness import connector_activation_readiness_service as svc
router=APIRouter(prefix='/internal/v1/connector-activation-readiness',tags=['first-real-connector-activation-readiness'])
class Payload(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/dashboard')
def dashboard(p:Principal=Depends(admin_principal)):return {'data':svc.dashboard()}
@router.get('/templates/{vertical}')
def template(vertical:str,p:Principal=Depends(admin_principal)):return {'data':svc.onboarding_template(vertical)}
@router.put('/connectors/{connector_id}/profile')
def profile(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.upsert_profile,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/connectors/{connector_id}/kms-bindings')
def kms(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.bind_kms,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/connectors/{connector_id}/production-accounts')
def account(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.register_account,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/connectors/{connector_id}/ip-allowlists')
def allowlist(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.set_allowlist,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/connectors/{connector_id}/webhook-endpoints')
def webhook(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.configure_webhook,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/webhook-endpoints/{endpoint_id}/rotate-key')
def rotate(endpoint_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.rotate_webhook_key,endpoint_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/connectors/{connector_id}/certifications')
def certify(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.run_certification,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/connectors/{connector_id}/drills')
def drill(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.record_drill,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/connectors/{connector_id}/financial-closure')
def financial(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.verify_financial_closure,connector_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/connectors/{connector_id}/assess')
def assess(connector_id:str,p:Principal=Depends(admin_principal)):return call(svc.assess,connector_id,p.user_id)
