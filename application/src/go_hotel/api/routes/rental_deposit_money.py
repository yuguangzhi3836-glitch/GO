"""Isolated deposit source-bound money operations and owner-checked observation."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from go_hotel.security.deps import admin_principal, current_principal
from go_hotel.security.service import Principal
from go_hotel.services import rental_deposit_money as service

router = APIRouter(tags=['rental-deposit-isolated-money'])


@router.get('/internal/v1/admin/mobility/rentals/orders/{order_id}/deposit-money-review')
def review(order_id: str, principal: Principal = Depends(admin_principal)):
    from go_hotel.services.rental_deposit_review import review as inspect
    return call(inspect, principal, order_id)


class Source(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=1)
    expected_source_hash: str = Field(pattern='^[0-9a-f]{64}$')


class Decision(Source):
    case_id: str = Field(min_length=1, max_length=64)
    expected_case_version: int = Field(ge=1)
    expected_decision_hash: str = Field(pattern='^[0-9a-f]{64}$')


class Release(Source):
    expected_release_revision: int = Field(ge=1)
    expected_release_hash: str = Field(pattern='^[0-9a-f]{64}$')


def call(fn, *args, **kwargs):
    try:
        return {'data': fn(*args, **kwargs)}
    except PermissionError as error:
        raise HTTPException(403, detail=str(error))
    except ValueError as error:
        raise HTTPException(409, detail=str(error))


@router.get('/v1/mobility/rentals/orders/{order_id}/deposit-money/{obligation_id}')
def status(order_id: str, obligation_id: str, expected_revision: int = Query(ge=1),
           expected_source_hash: str = Query(pattern='^[0-9a-f]{64}$'), principal: Principal = Depends(current_principal)):
    return call(service.status, principal, order_id, obligation_id, expected_revision, expected_source_hash)


@router.post('/internal/v1/mobility/rentals/orders/{order_id}/deposit-money/{obligation_id}/authorize')
def authorize(order_id: str, obligation_id: str, body: Source, principal: Principal = Depends(admin_principal)):
    return call(service.authorize, principal, order_id, obligation_id, **body.model_dump())


@router.post('/internal/v1/mobility/rentals/orders/{order_id}/deposit-money/{obligation_id}/settle')
def settle(order_id: str, obligation_id: str, body: Decision, principal: Principal = Depends(admin_principal)):
    return call(service.settle, principal, order_id, obligation_id, **body.model_dump())


@router.post('/internal/v1/mobility/rentals/orders/{order_id}/deposit-money/{obligation_id}/release')
def release(order_id: str, obligation_id: str, body: Release, principal: Principal = Depends(admin_principal)):
    return call(service.release, principal, order_id, obligation_id, **body.model_dump())
