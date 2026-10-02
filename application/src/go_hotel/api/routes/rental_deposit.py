"""C04 owner consent and verified read-only deposit source views."""
from fastapi import APIRouter, Depends, Header
from pydantic import Field

from go_hotel.api.routes.rental_damage import StrictBody, Evidence, invoke
from go_hotel.mobility.rental import deposit_authority as authority, damage
from go_hotel.mobility.rental.changes import transaction
from go_hotel.security.deps import consumer_principal, admin_principal, current_principal
from go_hotel.security.service import Principal

router = APIRouter(tags=['rental-deposit-obligation'])


class SourceConfirmation(StrictBody):
    expected_revision: int = Field(strict=True, gt=0)
    expected_source_hash: str = Field(pattern='^[0-9a-f]{64}$')


class Acceptance(SourceConfirmation):
    accepted: bool = Field(strict=True)


class ReturnConfirmation(SourceConfirmation):
    evidence: list[Evidence] = Field(min_length=1, max_length=20)


@router.get('/v1/mobility/rentals/orders/{order_id}/deposit-obligation')
def get_obligation(order_id: str, p: Principal = Depends(current_principal)):
    def read():
        try: return authority.get_obligation(p, order_id)
        except ValueError as e:
            if str(e) == 'DEPOSIT_OBLIGATION_NOT_FOUND': return None
            raise
    return invoke(read)


@router.post('/v1/mobility/rentals/orders/{order_id}/deposit-obligation')
def propose(order_id: str, b: StrictBody, p: Principal = Depends(consumer_principal),
            key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(authority.propose, p, order_id, key)


@router.post('/v1/mobility/rentals/orders/{order_id}/deposit-obligation/{obligation_id}/accept')
def accept(order_id: str, obligation_id: str, b: Acceptance, p: Principal = Depends(consumer_principal),
           key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(authority.accept, p, order_id, obligation_id, key, **b.model_dump())


@router.post('/v1/mobility/rentals/orders/{order_id}/deposit-obligation/{obligation_id}/renew')
def renew(order_id: str, obligation_id: str, b: SourceConfirmation, p: Principal = Depends(consumer_principal),
          key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(authority.renew, p, order_id, obligation_id, key, **b.model_dump())


@router.get('/v1/mobility/rentals/orders/{order_id}/damage-cases')
def damage_cases(order_id: str, p: Principal = Depends(current_principal)):
    def read():
        with transaction() as s:
            damage._order(s, p, order_id)
            cases = {}
            for event in damage._history(s, order_id):
                cases[event['case']['case_id']] = event['case']
            return {'items': list(cases.values())}
    return invoke(read)


@router.get('/internal/v1/admin/mobility/rentals/orders/{order_id}/deposit-obligation/{obligation_id}/cases/{case_id}/decision')
def decision_preview(order_id: str, obligation_id: str, case_id: str, p: Principal = Depends(admin_principal)):
    return invoke(authority.decision_preview, p, order_id, obligation_id, case_id)


@router.post('/internal/v1/admin/mobility/rentals/orders/{order_id}/deposit-obligation/{obligation_id}/return-review')
def close_return(order_id: str, obligation_id: str, b: ReturnConfirmation, p: Principal = Depends(admin_principal),
                 key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(authority.close_return, p, order_id, obligation_id, key, **b.model_dump())


@router.get('/internal/v1/admin/mobility/rentals/orders/{order_id}/deposit-obligation/{obligation_id}/release')
def release_preview(order_id: str, obligation_id: str, p: Principal = Depends(admin_principal)):
    return invoke(authority.release_preview, p, order_id, obligation_id)
