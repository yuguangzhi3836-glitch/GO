from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.payment_sandbox_runtime import payment_sandbox_runtime_service as svc
from go_hotel.services.payment_sandbox_cutover import payment_sandbox_cutover_service as cutover_svc

router = APIRouter(prefix="/internal/v1/payment-sandbox", tags=["payment-sandbox-readiness"])
class Payload(BaseModel): model_config={"extra":"allow"}
def call(fn,*args):
    try: return {"data":fn(*args)}
    except ValueError as exc: raise HTTPException(409,detail=str(exc))

@router.post("/aoluguya/readiness")
def configure(body:Payload,p:Principal=Depends(admin_principal)): return call(svc.configure_readiness,body.model_dump(exclude_none=True),p.user_id)
@router.get("/aoluguya/readiness")
def readiness(p:Principal=Depends(admin_principal)): return call(svc.readiness)
@router.get("/aoluguya/certification-preflight")
def certification_preflight(channel:str="ALIPAY",p:Principal=Depends(admin_principal)): return call(svc.certification_preflight,channel)
@router.post("/aoluguya/certify")
def certify(body:Payload,p:Principal=Depends(admin_principal)): return call(svc.certify,body.model_dump(exclude_none=True),p.user_id)
@router.post("/intents/{intent_id}/payment-link")
def payment_link(intent_id:str,p:Principal=Depends(admin_principal)): return call(svc.create_payment_link,intent_id,p.user_id)
@router.post("/intents/{intent_id}/settlement-release-gate")
def settlement_gate(intent_id:str,body:Payload,p:Principal=Depends(admin_principal)): return call(svc.settlement_release_gate,intent_id,body.model_dump(exclude_none=True),p.user_id)

@router.get("/aoluguya/cutover-safety")
def cutover_safety(channel:str="ALIPAY",p:Principal=Depends(admin_principal)): return call(cutover_svc.status,channel)
@router.get("/aoluguya/evidence-ledger")
def evidence_ledger(channel:str="ALIPAY",p:Principal=Depends(admin_principal)): return call(cutover_svc.evidence_ledger,channel)
@router.post("/aoluguya/{channel}/certification-revoke")
def certification_revoke(channel:str,body:Payload,p:Principal=Depends(admin_principal)): return call(cutover_svc.revoke_certification,channel,body.model_dump(exclude_none=True),p.user_id)
@router.post("/aoluguya/{channel}/credential-rotate")
def credential_rotate(channel:str,body:Payload,p:Principal=Depends(admin_principal)): return call(cutover_svc.rotate_credentials,channel,body.model_dump(exclude_none=True),p.user_id)
@router.post("/aoluguya/{channel}/executor-kill-switch")
def executor_kill_switch(channel:str,body:Payload,p:Principal=Depends(admin_principal)): return call(cutover_svc.set_executor_kill_switch,channel,body.model_dump(exclude_none=True),p.user_id)
@router.post("/aoluguya/{channel}/cutover-request")
def cutover_request(channel:str,body:Payload,p:Principal=Depends(admin_principal)): return call(cutover_svc.request_cutover,channel,body.model_dump(exclude_none=True),p.user_id)
@router.post("/aoluguya/cutover-approvals/{approval_id}/approve")
def cutover_approve(approval_id:str,body:Payload,p:Principal=Depends(admin_principal)): return call(cutover_svc.approve_cutover,approval_id,body.model_dump(exclude_none=True),p.user_id)
