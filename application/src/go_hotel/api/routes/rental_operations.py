"""Authenticated operator/consumer statements, atomically stored by domain commands.

Statements are actor claims, not verified photographs or supplier inspections.
No money instruction is executed by these routes.
"""
from fastapi import APIRouter, Depends, Header
from pydantic import Field
from typing import Literal

from go_hotel.api.routes.rental_damage import StrictBody, invoke
from go_hotel.core.config import settings
from go_hotel.mobility.rental import damage, deposit_authority
from go_hotel.mobility.rental.changes import transaction
from go_hotel.security.deps import current_principal, consumer_principal, admin_principal, supplier_principal
from go_hotel.security.service import Principal
from go_hotel.services.omnichannel_payment import digest

router = APIRouter(tags=['rental-operations'])


class Statement(StrictBody):
    statement: str = Field(min_length=1, max_length=4000)


class CaseStatement(Statement):
    expected_version: int = Field(strict=True, gt=0)


class Response(CaseStatement):
    response: Literal['ACCEPT', 'DISPUTE']


class Decision(CaseStatement):
    statement: str = Field(min_length=1, max_length=2000)
    award_minor: int = Field(strict=True, ge=0)


class Appeal(CaseStatement):
    statement: str = Field(min_length=1, max_length=2000)


class ReturnStatement(Statement):
    expected_revision: int = Field(strict=True, gt=0)
    expected_source_hash: str = Field(pattern='^[0-9a-f]{64}$')


class Claim(StrictBody):
    amount_minor: int = Field(strict=True, gt=0)
    currency: str = Field(min_length=3, max_length=3)
    pickup_statement: str = Field(min_length=1, max_length=4000)
    return_statement: str = Field(min_length=1, max_length=4000)


def statement_evidence(p, order_id, case_id, action, text):
    if not text.strip(): raise ValueError('DAMAGE_STATEMENT_REQUIRED')
    statement = {'kind': 'ACTOR_STATEMENT_UNVERIFIED', 'actor_id': p.user_id,
        'actor_type': p.actor_type, 'order_id': order_id, 'case_id': case_id,
        'action': action, 'text': text}
    sha = digest(statement)
    return [{'reference': 'rental-statement://' + sha, 'sha256': sha, 'statement': statement}]


def workspace(p, order_id):
    with transaction() as s:
        o = damage._order(s, p, order_id, allow_supplier=True)
        cases = {}
        history = damage._history(s, order_id)
        for event in history:
            cases[event['case']['case_id']] = event['case']
        events = deposit_authority._events(s, o)
        obligation = events[-1]['obligation'] if events else None
        release = deposit_authority._release_event(s, o)
        enabled = settings.app_env.lower() in {'local', 'test', 'demo'}
        actions = []
        if (enabled and p.actor_type == 'SUPPLIER_USER' and 'supplier:orders' in p.permissions
                and not cases and not release and o.status == 'COMPLETED'):
            actions.append('OPEN')
        if enabled and p.actor_type == 'GO_ADMIN' and 'admin:approve' in p.permissions:
            if not cases and not release and o.status == 'COMPLETED': actions.append('OPEN')
            if (not cases and not release and obligation and obligation['state'] == 'ACTIVATED'
                    and o.status in {'COMPLETED','REFUNDED'} and p.user_id != o.account_id):
                actions.append('RETURN_REVIEW')
        items = []
        for case in cases.values():
            permitted = []
            if enabled and p.actor_type == 'CONSUMER':
                if case['status'] == 'AWAITING_CUSTOMER': permitted.append('RESPONSE')
                if case['status'] == 'ADJUDICATED': permitted.append('APPEAL')
            if enabled and p.actor_type == 'GO_ADMIN' and 'admin:approve' in p.permissions:
                excluded = {case['owner_id'], case['opened_by']}
                if case['status'] == 'REVIEW_REQUIRED' and p.user_id not in excluded:
                    permitted.append('DECISION')
                if (case['status'] == 'APPEAL_REVIEW_REQUIRED' and p.user_id not in excluded
                        | {d['reviewer_id'] for d in case['decision_history']}):
                    permitted.append('APPEAL_DECISION')
            items.append({'case': case, 'actions': permitted})
        receipts = [{'key': e['key'], 'case_id': e['case']['case_id'], 'version': e['case']['version']}
                    for e in history if e['actor_id'] == p.user_id]
        if release and release['actor_id'] == p.user_id:
            receipts.append({'key': release['key'], 'release_revision': release['release']['release_revision']})
        return {'order_id': order_id, 'order_status': o.status, 'currency': o.currency,
            'actor_type': p.actor_type, 'actor_id': p.user_id, 'writes_enabled': enabled,
            'cases': items, 'actions': actions, 'obligation': obligation, 'receipts': receipts,
            'release': release['release'] if release else None,
            'financial_authority': 'C11', 'data_mode': 'ISOLATED_CONTRACT_FIXTURE', 'external_live': False}


@router.get('/v1/mobility/rentals/orders/{order_id}/operations')
def get_workspace(order_id: str, p: Principal = Depends(current_principal)):
    return invoke(workspace, p, order_id)


@router.post('/v1/mobility/rentals/orders/{order_id}/operations/cases/{case_id}/response')
def respond(order_id: str, case_id: str, b: Response, p: Principal = Depends(consumer_principal),
            key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(lambda: damage.respond(p, order_id, case_id, key, b.expected_version, b.response,
        statement_evidence(p, order_id, case_id, 'RESPONSE', b.statement)))


@router.post('/v1/mobility/rentals/orders/{order_id}/operations/cases/{case_id}/appeal')
def appeal(order_id: str, case_id: str, b: Appeal, p: Principal = Depends(consumer_principal),
           key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(lambda: damage.appeal(p, order_id, case_id, key, b.expected_version, b.statement,
        statement_evidence(p, order_id, case_id, 'APPEAL', b.statement)))


@router.post('/internal/v1/admin/mobility/rentals/orders/{order_id}/operations/cases')
def open_case(order_id: str, b: Claim, p: Principal = Depends(admin_principal),
              key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(lambda: damage.open_case(p, order_id, key, b.amount_minor, b.currency,
        statement_evidence(p, order_id, None, 'PICKUP_OBSERVATION', b.pickup_statement),
        statement_evidence(p, order_id, None, 'RETURN_OBSERVATION', b.return_statement)))


@router.post('/v1/supplier/mobility/rentals/orders/{order_id}/operations/cases')
def supplier_open_case(order_id: str, b: Claim, p: Principal = Depends(supplier_principal),
                      key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(lambda: damage.open_case(p, order_id, key, b.amount_minor, b.currency,
        statement_evidence(p, order_id, None, 'PICKUP_OBSERVATION', b.pickup_statement),
        statement_evidence(p, order_id, None, 'RETURN_OBSERVATION', b.return_statement)))


@router.post('/internal/v1/admin/mobility/rentals/orders/{order_id}/operations/cases/{case_id}/decision')
def adjudicate(order_id: str, case_id: str, b: Decision, p: Principal = Depends(admin_principal),
               key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(lambda: damage.adjudicate(p, order_id, case_id, key, b.expected_version, b.award_minor, b.statement,
        statement_evidence(p, order_id, case_id, 'DECISION', b.statement)))


@router.post('/internal/v1/admin/mobility/rentals/orders/{order_id}/operations/cases/{case_id}/appeal-decision')
def review_appeal(order_id: str, case_id: str, b: Decision, p: Principal = Depends(admin_principal),
                  key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(lambda: damage.review_appeal(p, order_id, case_id, key, b.expected_version, b.award_minor, b.statement,
        statement_evidence(p, order_id, case_id, 'APPEAL_DECISION', b.statement)))


@router.post('/internal/v1/admin/mobility/rentals/orders/{order_id}/operations/obligations/{obligation_id}/return-review')
def close_return(order_id: str, obligation_id: str, b: ReturnStatement, p: Principal = Depends(admin_principal),
                 key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128)):
    return invoke(lambda: deposit_authority.close_return(p, order_id, obligation_id, key, b.expected_revision,
        b.expected_source_hash, statement_evidence(p, order_id, None, 'RETURN_REVIEW', b.statement)))
