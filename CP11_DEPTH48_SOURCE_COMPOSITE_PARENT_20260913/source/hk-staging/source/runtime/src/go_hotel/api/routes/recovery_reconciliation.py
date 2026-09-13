from __future__ import annotations
import json
from fastapi import APIRouter,Depends,Header,HTTPException,Request
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.webhooks import webhook_service
from go_hotel.journey.recovery_reconciliation import recovery_reconciliation_service
from go_hotel.recovery_adapters.registry import recovery_adapter_registry

router=APIRouter(tags=['sprint3i-recovery-reconciliation'])

class RunBody(BaseModel):
    limit:int=50
class ManualBody(BaseModel):
    resolution:str
    supplier_confirmation_id:str|None=None
    evidence_reference:str
    evidence:dict={}

@router.post('/internal/v1/recovery/adapters/{adapter_key}/webhooks')
async def supplier_recovery_webhook(adapter_key:str,request:Request,x_go_signature:str|None=Header(default=None,alias='X-GO-Signature')):
    raw=await request.body()
    if not webhook_service.verify(raw,x_go_signature): raise HTTPException(401,detail='INVALID_WEBHOOK_SIGNATURE')
    try:payload=json.loads(raw)
    except json.JSONDecodeError: raise HTTPException(400,detail='INVALID_WEBHOOK_JSON')
    try:return {'data':recovery_reconciliation_service.ingest_webhook(adapter_key,payload)}
    except (ValueError,KeyError) as e:
        msg=str(e);raise HTTPException(404 if 'NOT_FOUND' in msg else 409,detail=msg)

@router.post('/internal/v1/recovery/reconciliation/run')
def run_reconciliation(body:RunBody,p:Principal=Depends(admin_principal)):
    return {'data':recovery_reconciliation_service.run_once(max(1,min(body.limit,500)))}

@router.post('/internal/v1/recovery/reconciliation/jobs/{job_id}/resolve')
def manual_resolve(job_id:str,body:ManualBody,p:Principal=Depends(admin_principal)):
    try:return {'data':recovery_reconciliation_service.manual_resolve(job_id,body.resolution,body.supplier_confirmation_id,p.user_id,body.evidence_reference,body.evidence)}
    except ValueError as e:
        msg=str(e);raise HTTPException(404 if 'NOT_FOUND' in msg else 409,detail=msg)

@router.get('/internal/v1/recovery/adapters')
def list_adapters(p:Principal=Depends(admin_principal)):
    return {'data':[{'adapter_key':m.adapter_key,'vertical':m.vertical,'version':m.version,'capabilities':m.capabilities.__dict__} for m in recovery_adapter_registry.list()]}
