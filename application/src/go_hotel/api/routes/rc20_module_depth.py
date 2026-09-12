from fastapi import APIRouter, Depends
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.rc20_module_depth import readiness

router = APIRouter(prefix='/internal/v1/admin/operations', tags=['rc20-module-depth'])

@router.get('/module-depth')
def module_depth(p: Principal = Depends(admin_principal)):
    return {'data': readiness()}
