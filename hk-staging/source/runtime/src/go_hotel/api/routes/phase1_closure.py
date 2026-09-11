from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.phase1_closure import phase1_closure_service as svc
router=APIRouter(prefix='/internal/v1/phase1-closure',tags=['phase1-cross-domain-closure'])
class P(BaseModel):model_config={'extra':'allow'}
@router.get('/capability-matrix')
def matrix(p:Principal=Depends(admin_principal)):return {'data':svc.capability_matrix()}
@router.post('/source-selection')
def source(b:P,p:Principal=Depends(admin_principal)):
 x=b.model_dump(exclude_none=True)
 try:return {'data':svc.select_source(x['vertical'],x['candidates'])}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/evidence-policy')
def evidence(p:Principal=Depends(admin_principal)):return {'data':svc.evidence_policy()}
