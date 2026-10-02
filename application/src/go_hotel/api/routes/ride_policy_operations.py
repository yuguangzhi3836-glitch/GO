from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.mobility.ride import policy_operations as service

router = APIRouter(prefix='/internal/v1/ride-policy-operations', tags=['ride-policy-operations'])

class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    policy: dict

class Revision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: str = Field(min_length=64, max_length=64)


def call(fn, *args):
    try: return {'data': fn(*args)}
    except PermissionError as exc: raise HTTPException(403, detail=str(exc))
    except ValueError as exc: raise HTTPException(409, detail=str(exc))


@router.get('')
def diagnose(p: Principal = Depends(admin_principal)):
    return call(service.diagnose, p)


@router.post('/drafts')
def draft(b: Draft, p: Principal = Depends(admin_principal)):
    return call(service.create, p, b.policy)


@router.post('/{policy_id}/activate')
def activate(policy_id: str, b: Revision, p: Principal = Depends(admin_principal)):
    return call(service.transition, p, policy_id, b.revision, 'activate')


@router.post('/{policy_id}/revoke')
def revoke(policy_id: str, b: Revision, p: Principal = Depends(admin_principal)):
    return call(service.transition, p, policy_id, b.revision, 'revoke')
