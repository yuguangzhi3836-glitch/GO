from fastapi import APIRouter, Depends
from go_hotel.core.r8_implementation_alignment import snapshot
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal

router = APIRouter(tags=["r8-release-alignment"])

@router.get("/internal/v1/admin/r8/readiness")
def r8_readiness(p: Principal = Depends(admin_principal)):
    return {"data": snapshot()}
