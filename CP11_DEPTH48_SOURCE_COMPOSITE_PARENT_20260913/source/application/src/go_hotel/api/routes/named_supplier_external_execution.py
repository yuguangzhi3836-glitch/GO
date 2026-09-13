from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.named_supplier_external_execution import named_supplier_external_execution_service as svc
router=APIRouter(prefix='/internal/v1/named-supplier-execution',tags=['named-supplier-external-sandbox-execution'])
class Payload(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/dashboard')
def dashboard(p:Principal=Depends(admin_principal)):return {'data':svc.dashboard()}
@router.post('/intakes/{intake_id}/adapters')
def adapter(intake_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.register_adapter,intake_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/adapters/{adapter_id}/bindings')
def binding(adapter_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.bind_adapter,adapter_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/suites/{suite_id}/authorizations')
def authorization(suite_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.request_authorization,suite_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/authorizations/{authorization_id}/approve')
def approve(authorization_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.approve,authorization_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/authorizations/{authorization_id}/execute')
def execute(authorization_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.execute,authorization_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/attempts/{attempt_id}/transport-evidence')
def evidence(attempt_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.record_transport_evidence,attempt_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/attempts/{attempt_id}/decision')
def decision(attempt_id:str,p:Principal=Depends(admin_principal)):return call(svc.decide,attempt_id,p.user_id)
@router.get('/attempts/{attempt_id}')
def status(attempt_id:str,p:Principal=Depends(admin_principal)):return call(svc.status,attempt_id)
