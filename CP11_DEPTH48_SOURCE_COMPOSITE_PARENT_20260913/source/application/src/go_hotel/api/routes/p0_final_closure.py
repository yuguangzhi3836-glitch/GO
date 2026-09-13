from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.p0_final_closure import p0_final_closure_service as svc
router=APIRouter(tags=['p0-final-closure'])
class Seal(BaseModel):build_sha256:str
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/internal/v1/p0/final-closure/status')
def status(p:Principal=Depends(admin_principal)):return {'data':svc.evaluate()}
@router.post('/internal/v1/p0/final-closure/seal')
def seal(b:Seal,p:Principal=Depends(admin_principal)):return call(svc.seal,b.build_sha256)
