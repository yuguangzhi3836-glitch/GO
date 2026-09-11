from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.judgment.good_hotel_standard import good_hotel_standard_service as svc
router=APIRouter(prefix='/internal/v1/judgment/good-hotel-standards',tags=['go-good-hotel-standard'])
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('')
def create(b:P,p:Principal=Depends(admin_principal)):return call(svc.create,b.model_dump(exclude_none=True),p.user_id)
@router.post('/{version_id}/approve')
def approve(version_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve,version_id,p.user_id)
@router.get('')
def status(p:Principal=Depends(admin_principal)):return {'data':svc.status()}
