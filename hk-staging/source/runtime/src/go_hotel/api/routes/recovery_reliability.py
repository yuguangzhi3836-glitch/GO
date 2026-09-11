from fastapi import APIRouter,Depends
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_reliability import recovery_reliability_service
router=APIRouter(tags=['sprint3l-recovery-reliability'])
@router.post('/internal/v1/recovery/reliability/rebuild')
def rebuild(p:Principal=Depends(admin_principal)):
    return {'data':recovery_reliability_service.rebuild()}
@router.get('/internal/v1/recovery/reliability/profiles')
def profiles(p:Principal=Depends(admin_principal)):
    return {'data':{'items':recovery_reliability_service.list()}}
