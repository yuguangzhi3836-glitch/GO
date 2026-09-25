"""Authenticated isolated rental damage case routes (no funds execution)."""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from go_hotel.mobility.rental import damage
from go_hotel.security.deps import admin_principal, consumer_principal, current_principal
from go_hotel.security.service import Principal

router = APIRouter(tags=['rental-damage'])


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Evidence(StrictBody):
    reference: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern='^[0-9a-f]{64}$')


class Claim(StrictBody):
    amount_minor: int = Field(strict=True, gt=0)
    currency: str = Field(min_length=3, max_length=3)
    pickup_evidence: list[Evidence] = Field(min_length=1, max_length=20)
    return_evidence: list[Evidence] = Field(min_length=1, max_length=20)


class Response(StrictBody):
    expected_version: int = Field(strict=True, gt=0)
    response: Literal['ACCEPT', 'DISPUTE']
    evidence: list[Evidence] = Field(min_length=1, max_length=20)


class Decision(StrictBody):
    expected_version: int = Field(strict=True, gt=0)
    award_minor: int = Field(strict=True, ge=0)
    reason: str = Field(min_length=1, max_length=2000)
    evidence: list[Evidence] = Field(min_length=1, max_length=20)


class Appeal(StrictBody):
    expected_version: int = Field(strict=True, gt=0)
    reason: str = Field(min_length=1, max_length=2000)
    evidence: list[Evidence] = Field(min_length=1, max_length=20)


def invoke(fn, *args, **kwargs):
    try:
        return {'data': fn(*args, **kwargs)}
    except PermissionError as error:
        raise HTTPException(403, detail=str(error)) from None
    except ValueError as error:
        msg = str(error)
        status = 404 if 'NOT_FOUND' in msg else 409 if any(x in msg for x in ('CONFLICT', 'ALREADY_EXISTS', 'REQUIRED')) else 422
        raise HTTPException(status, detail=msg) from None


@router.post('/internal/v1/admin/mobility/rentals/orders/{order_id}/damage-cases')
def open_case(order_id: str, b: Claim, p: Principal = Depends(admin_principal),
              key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(damage.open_case, p, order_id, key, **b.model_dump())


@router.post('/v1/mobility/rentals/orders/{order_id}/damage-cases/{case_id}/response')
def respond(order_id: str, case_id: str, b: Response, p: Principal = Depends(consumer_principal),
            key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(damage.respond, p, order_id, case_id, key, **b.model_dump())


@router.post('/internal/v1/admin/mobility/rentals/orders/{order_id}/damage-cases/{case_id}/decision')
def adjudicate(order_id: str, case_id: str, b: Decision, p: Principal = Depends(admin_principal),
               key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(damage.adjudicate, p, order_id, case_id, key, **b.model_dump())


@router.get('/v1/mobility/rentals/orders/{order_id}/damage-cases/{case_id}')
def get_case(order_id: str, case_id: str, p: Principal = Depends(current_principal)):
    return invoke(damage.get_case, p, order_id, case_id)


@router.post('/v1/mobility/rentals/orders/{order_id}/damage-cases/{case_id}/appeal')
def appeal(order_id: str, case_id: str, b: Appeal, p: Principal = Depends(consumer_principal),
           key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(damage.appeal, p, order_id, case_id, key, **b.model_dump())


@router.post('/internal/v1/admin/mobility/rentals/orders/{order_id}/damage-cases/{case_id}/appeal-decision')
def review_appeal(order_id: str, case_id: str, b: Decision, p: Principal = Depends(admin_principal),
                  key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(damage.review_appeal, p, order_id, case_id, key, **b.model_dump())
