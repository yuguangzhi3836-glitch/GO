from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.staging_execution_evidence_orchestrator import staging_execution_evidence_orchestrator as svc
from go_hotel.services.staging_operator import staging_operator_service as operator_svc

router = APIRouter(prefix="/internal/v1/staging-execution-evidence", tags=["staging-execution-evidence"])

class AdvanceBody(BaseModel):
    evidence_reference: str
    rds_lineage_attested: bool = False

def call(fn, *args, **kwargs):
    try: return {"data": fn(*args, **kwargs)}
    except ValueError as exc: raise HTTPException(409, detail=str(exc))

@router.get("/status")
def status(p: Principal = Depends(admin_principal)):
    return call(svc.status)

@router.post("/stages/{stage}/advance")
def advance(stage: str, body: AdvanceBody, p: Principal = Depends(admin_principal)):
    return call(svc.advance, stage, p.user_id, body.evidence_reference, rds_lineage_attested=body.rds_lineage_attested)

@router.get("/operator/status")
def operator_status(p: Principal = Depends(admin_principal)):
    return call(operator_svc.operator_status)

@router.get("/operator/export")
def operator_export(p: Principal = Depends(admin_principal)):
    return call(operator_svc.export_bundle)

@router.get("/operator/checkpoints/{stage}/seal")
def operator_seal(stage: str, p: Principal = Depends(admin_principal)):
    return call(operator_svc.seal_checkpoint, stage)
