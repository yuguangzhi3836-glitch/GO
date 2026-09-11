from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.external_sandbox_certification import external_sandbox_certification_service as svc
router=APIRouter(prefix='/internal/v1/external-sandbox-certification',tags=['external-supplier-sandbox-certification'])
class Payload(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/dashboard')
def dashboard(p:Principal=Depends(admin_principal)):return {'data':svc.dashboard()}
@router.post('/intakes')
def intake(b:Payload,p:Principal=Depends(admin_principal)):return call(svc.create_intake,b.model_dump(exclude_none=True),p.user_id)
@router.put('/intakes/{intake_id}')
def update(intake_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.update_intake,intake_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/intakes/{intake_id}/credential-bindings')
def credential(intake_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.bind_credential,intake_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/intakes/{intake_id}/assess')
def assess(intake_id:str,p:Principal=Depends(admin_principal)):return call(svc.assess,intake_id,p.user_id)
@router.post('/intakes/{intake_id}/suites')
def suite(intake_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.create_suite,intake_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/suites/{suite_id}/execute')
def execute(suite_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.execute,suite_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/runs/{run_id}/evidence')
def evidence(run_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.import_evidence,run_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/runs/{run_id}/callback-proofs')
def callback(run_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.callback_proof,run_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/runs/{run_id}/decision')
def decide(run_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.decide,run_id,b.model_dump(exclude_none=True),p.user_id)
@router.get('/runs/{run_id}')
def status(run_id:str,p:Principal=Depends(admin_principal)):return call(svc.status,run_id)
