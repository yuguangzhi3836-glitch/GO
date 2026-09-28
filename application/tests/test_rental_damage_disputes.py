"""Isolated adjudication evidence. No supplier or payment execution is used."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from sqlalchemy import func, select
from go_hotel.db.models import MobilityRentalOrderRow as Order, OmnichannelMoneyMovementRow as Movement
from go_hotel.db.session import SessionLocal
from go_hotel.mobility.rental import damage
from go_hotel.security.service import Principal
from go_hotel.core.config import settings


def principal(uid, actor='GO_ADMIN', permissions=None):
    return Principal(uid, uid, actor, None, [], 'test-session',
                     {'admin:approve'} if permissions is None else permissions)


MAKER = principal('maker')
CHECKER = principal('checker')
OWNER = principal('customer', 'CONSUMER', set())


def ev(char): return [{'reference': 'isolated-evidence://' + char, 'sha256': char * 64}]


@pytest.fixture
def order():
    now = datetime(2026, 9, 25)
    with SessionLocal.begin() as s:
        s.add(Order(order_id='rental-case-test', account_id=OWNER.user_id, status='COMPLETED',
            pickup_location='A', return_location='A', pickup_at='2026-09-01T10:00:00',
            return_at='2026-09-03T10:00:00', vehicle_class='COMPACT',
            insurance={'type': 'BASIC', 'excess_minor': 500000}, mileage={}, deposit_minor=200000,
            total_amount_minor=84000, currency='CNY', drivers=[], supplier_reference=None,
            created_at=now, updated_at=now))
    return 'rental-case-test'


def claim(oid, key='claim', amount=10000):
    return damage.open_case(MAKER, oid, key, amount, 'CNY', ev('a'), ev('b'))


def test_dispute_to_independent_decision_never_moves_money(order):
    c = claim(order)
    c = damage.respond(OWNER, order, c['case_id'], 'response', 1, 'DISPUTE', ev('c'))
    assert c['status'] == 'REVIEW_REQUIRED'
    c = damage.adjudicate(CHECKER, order, c['case_id'], 'decision', 2, 4000, 'Partial damage evidence', ev('d'))
    assert c['status'] == 'ADJUDICATED' and c['awarded_minor'] == 4000
    assert c['money_status'] == 'C11_MONEY_REVIEW_REQUIRED' and c['money_movement_ids'] == []
    assert damage.get_case(OWNER, order, c['case_id']) == c
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(Movement)) == 0
        assert s.get(Order, order).status == 'COMPLETED'


@pytest.mark.parametrize('response', ['ACCEPT', 'DISPUTE'])
def test_replays_are_exact_and_changed_payload_conflicts(order, response):
    first = claim(order)
    assert claim(order) == first
    with pytest.raises(ValueError, match='IDEMPOTENCY_CONFLICT'): claim(order, amount=12000)
    with pytest.raises(ValueError, match='ALREADY_EXISTS'): claim(order, key='new-claim')
    args = (OWNER, order, first['case_id'], 'response', 1, response, ev('c'))
    assert damage.respond(*args) == damage.respond(*args)
    result = damage.adjudicate(CHECKER, order, first['case_id'], 'decision', 2, 0, 'No liability', ev('d'))
    assert damage.adjudicate(CHECKER, order, first['case_id'], 'decision', 2, 0, 'No liability', ev('d')) == result
    with pytest.raises(ValueError, match='IDEMPOTENCY_CONFLICT'):
        damage.adjudicate(CHECKER, order, first['case_id'], 'decision', 2, 1, 'No liability', ev('d'))


def test_tenant_and_supplier_isolation(order):
    c = claim(order)
    for p in (principal('other', 'CONSUMER'), principal('supplier', 'SUPPLIER_USER')):
        with pytest.raises(ValueError, match='NOT_FOUND'): damage.get_case(p, order, c['case_id'])
    with pytest.raises(ValueError, match='NOT_FOUND'):
        damage.respond(principal('other', 'CONSUMER'), order, c['case_id'], 'x', 1, 'DISPUTE', ev('c'))
    with pytest.raises(PermissionError):
        damage.open_case(principal('supplier', 'SUPPLIER_USER'), order, 'x', 1, 'CNY', ev('a'), ev('b'))
    with pytest.raises(PermissionError):
        damage.open_case(principal('readonly', permissions={'admin:read'}), order, 'x', 1, 'CNY', ev('a'), ev('b'))


def test_independent_reviewer_and_customer_response_required(order):
    c = claim(order)
    with pytest.raises(ValueError, match='STATE_CONFLICT'):
        damage.adjudicate(CHECKER, order, c['case_id'], 'x', 1, 0, 'reason', ev('d'))
    damage.respond(OWNER, order, c['case_id'], 'response', 1, 'DISPUTE', ev('c'))
    with pytest.raises(PermissionError, match='INDEPENDENT'):
        damage.adjudicate(MAKER, order, c['case_id'], 'x', 2, 0, 'reason', ev('d'))
    with pytest.raises(ValueError, match='EXCEEDS'):
        damage.adjudicate(CHECKER, order, c['case_id'], 'x', 2, 10001, 'reason', ev('d'))


@pytest.mark.parametrize('amount', [True, -1, 0, 200001, 1.5])
def test_amount_limits(order, amount):
    with pytest.raises(ValueError, match='AMOUNT_INVALID'): claim(order, amount=amount)


def test_full_insurance_and_invalid_evidence_rejected(order):
    with pytest.raises(ValueError, match='DISTINCT'):
        damage.open_case(MAKER, order, 'x', 1, 'CNY', ev('a'), ev('a'))
    with pytest.raises(ValueError, match='EVIDENCE_INVALID'):
        damage.open_case(MAKER, order, 'x', 1, 'CNY', [], ev('b'))
    with SessionLocal.begin() as s: s.get(Order, order).insurance = {'excess_minor': 0}
    with pytest.raises(ValueError, match='AMOUNT_INVALID'): claim(order, amount=1)


def test_competing_responses_serialize_and_stale_version_rejects(order):
    c = claim(order)
    def run(response):
        try:
            damage.respond(OWNER, order, c['case_id'], response, 1, response, ev('c'))
            return 'PASS'
        except ValueError as e:
            assert 'VERSION_CONFLICT' in str(e)
            return 'CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, ['ACCEPT', 'DISPUTE'])) == ['CONFLICT', 'PASS']


def test_writes_forbidden_outside_isolation(order, monkeypatch):
    monkeypatch.setattr(settings, 'app_env', 'staging')
    with pytest.raises(ValueError, match='FORBIDDEN'): claim(order)


def test_api_principal_is_not_body_controlled_and_permissions_enforced(order):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from go_hotel.api.routes.rental_damage import router
    from go_hotel.security.deps import current_principal
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[current_principal] = lambda: MAKER
    body = {'amount_minor': 10000, 'currency': 'CNY', 'pickup_evidence': ev('a'), 'return_evidence': ev('b')}
    url = f'/internal/v1/admin/mobility/rentals/orders/{order}/damage-cases'
    with TestClient(app) as client:
        assert client.post(url, json={**body, 'actor': 'checker'}, headers={'Idempotency-Key': 'x'}).status_code == 422
        assert client.post(url, json=body).status_code == 422
        result = client.post(url, json=body, headers={'Idempotency-Key': 'x'})
        assert result.status_code == 200, result.text
        app.dependency_overrides[current_principal] = lambda: principal('other', 'CONSUMER')
        assert client.post(url, json=body, headers={'Idempotency-Key': 'x'}).status_code == 403
        cid = result.json()['data']['case_id']
        assert client.get(f'/v1/mobility/rentals/orders/{order}/damage-cases/{cid}').status_code == 404


def test_failed_append_rolls_back_and_retry_creates_single_case(order, monkeypatch):
    original = damage.append_vertical_evidence
    def fail_after_flush(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('INJECTED_CRASH_BEFORE_COMMIT')
    monkeypatch.setattr(damage, 'append_vertical_evidence', fail_after_flush)
    with pytest.raises(RuntimeError, match='INJECTED_CRASH'): claim(order)
    monkeypatch.setattr(damage, 'append_vertical_evidence', original)
    c = claim(order)
    assert claim(order) == c
    with SessionLocal() as s:
        assert len(damage._history(s, order)) == 1


def test_concurrent_case_retries_and_contract_snapshot_freeze(order):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(order), range(2)))
    assert results[0] == results[1]
    c = results[0]
    with SessionLocal.begin() as s:
        o = s.get(Order, order)
        o.deposit_minor = 999999
        o.insurance = {'excess_minor': 999999}
    c = damage.respond(OWNER, order, c['case_id'], 'response', 1, 'DISPUTE', ev('c'))
    assert c['contract_snapshot']['maximum_award_minor'] == 200000
    assert c['claimed_minor'] == 10000
    with pytest.raises(ValueError, match='EXCEEDS'):
        damage.adjudicate(CHECKER, order, c['case_id'], 'decision', 2, 10001, 'reason', ev('d'))


@pytest.mark.parametrize('corrupt', ['execution_item', 'embedded_order', 'owner', 'payload', 'chain'])
def test_corrupted_case_history_cannot_progress_or_append(order, corrupt):
    import copy
    from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as EvidenceRow
    c = claim(order)
    with SessionLocal.begin() as s:
        row = s.scalar(select(EvidenceRow).where(EvidenceRow.execution_id == f'rc20:RENTAL:{order}'))
        body = copy.deepcopy(row.evidence_json)
        if corrupt == 'execution_item': row.execution_item_id = 'another-order'
        elif corrupt == 'embedded_order': body['order_id'] = 'another-order'
        elif corrupt == 'owner': body['payload']['case']['owner_id'] = 'another-owner'
        elif corrupt == 'payload': body['payload']['case']['claimed_minor'] = 200000
        else: row.previous_hash = 'tampered'
        row.evidence_json = body
    with pytest.raises(ValueError, match='EVIDENCE_INTEGRITY_INVALID'):
        damage.respond(OWNER, order, c['case_id'], 'response', 1, 'DISPUTE', ev('c'))
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(EvidenceRow).where(
            EvidenceRow.execution_id == f'rc20:RENTAL:{order}')) == 1


def adjudicated(oid):
    c = claim(oid)
    damage.respond(OWNER, oid, c['case_id'], 'response', 1, 'DISPUTE', ev('c'))
    return damage.adjudicate(CHECKER, oid, c['case_id'], 'decision', 2, 5000, 'First decision', ev('d'))


def test_appeal_holds_decision_then_independent_review_preserves_history(order):
    c = adjudicated(order)
    c = damage.appeal(OWNER, order, c['case_id'], 'appeal', 3, 'Additional return evidence', ev('e'))
    assert c['status'] == 'APPEAL_REVIEW_REQUIRED' and c['actionable_award_minor'] is None
    assert c['money_instruction_state'] == 'DISPUTE_HOLD' and c['awarded_minor'] == 5000
    for reviewer in (MAKER, CHECKER):
        with pytest.raises(PermissionError, match='INDEPENDENT'):
            damage.review_appeal(reviewer, order, c['case_id'], 'review', 4, 0, 'Reversed', ev('f'))
    c = damage.review_appeal(principal('appeal-reviewer'), order, c['case_id'], 'review', 4, 0, 'Reversed', ev('f'))
    assert c['awarded_minor'] == 0 and c['money_status'] == 'C11_MONEY_REVIEW_REQUIRED'
    assert c['decision_history'][0]['award_minor'] == 5000
    assert c['decision_history'][1]['supersedes_decision_version'] == 3
    assert c['money_movement_ids'] == []
    with SessionLocal() as s:
        history = damage._history(s, order)
        assert history[2]['case']['awarded_minor'] == 5000
        assert history[3]['case']['status'] == 'APPEAL_REVIEW_REQUIRED'
        assert s.scalar(select(func.count()).select_from(Movement)) == 0


def test_appeal_retries_conflicts_wrong_owner_and_stale_review(order):
    c = adjudicated(order)
    args = (OWNER, order, c['case_id'], 'appeal', 3, 'Additional evidence', ev('e'))
    assert damage.appeal(*args) == damage.appeal(*args)
    with pytest.raises(ValueError, match='NOT_FOUND'):
        damage.appeal(principal('other', 'CONSUMER'), order, c['case_id'], 'appeal', 3, 'Additional evidence', ev('e'))
    with pytest.raises(ValueError, match='IDEMPOTENCY_CONFLICT'):
        damage.appeal(OWNER, order, c['case_id'], 'appeal', 3, 'Changed reason', ev('e'))
    with pytest.raises(ValueError, match='VERSION_CONFLICT'):
        damage.review_appeal(principal('reviewer2'), order, c['case_id'], 'review', 3, 0, 'reason', ev('f'))
    args = (principal('reviewer2'), order, c['case_id'], 'review', 4, 0, 'reason', ev('f'))
    assert damage.review_appeal(*args) == damage.review_appeal(*args)


def test_competing_appeal_review_and_crash_recovery(order, monkeypatch):
    c = adjudicated(order)
    original = damage.append_vertical_evidence
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('INJECTED_APPEAL_CRASH')
    monkeypatch.setattr(damage, 'append_vertical_evidence', interrupted)
    with pytest.raises(RuntimeError, match='APPEAL_CRASH'):
        damage.appeal(OWNER, order, c['case_id'], 'appeal', 3, 'reason', ev('e'))
    monkeypatch.setattr(damage, 'append_vertical_evidence', original)
    assert damage.get_case(OWNER, order, c['case_id'])['version'] == 3
    damage.appeal(OWNER, order, c['case_id'], 'appeal', 3, 'reason', ev('e'))
    def run(uid):
        try:
            damage.review_appeal(principal(uid), order, c['case_id'], 'review', 4, 0, 'reason', ev('f'))
            return 'PASS'
        except ValueError as e:
            assert 'VERSION_CONFLICT' in str(e)
            return 'CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, ['r2', 'r3'])) == ['CONFLICT', 'PASS']


def test_no_appeal_before_decision_or_timeout_default(order):
    c = claim(order)
    with pytest.raises(ValueError, match='STATE_CONFLICT'):
        damage.appeal(OWNER, order, c['case_id'], 'appeal', 1, 'reason', ev('e'))
    assert damage.get_case(OWNER, order, c['case_id'])['status'] == 'AWAITING_CUSTOMER'


def test_authenticated_http_appeal_and_review_endpoints(order):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from go_hotel.api.routes.rental_damage import router
    from go_hotel.security.deps import current_principal
    c = adjudicated(order)
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[current_principal] = lambda: OWNER
    base = f'/v1/mobility/rentals/orders/{order}/damage-cases/{c["case_id"]}'
    with TestClient(app) as client:
        r = client.post(base + '/appeal', json={'expected_version': 3, 'reason': 'New evidence', 'evidence': ev('e')},
                        headers={'Idempotency-Key': 'appeal'})
        assert r.status_code == 200 and r.json()['data']['money_instruction_state'] == 'DISPUTE_HOLD'
        path = '/internal/v1/admin' + base[3:] + '/appeal-decision'
        body = {'expected_version': 4, 'award_minor': 0, 'reason': 'Reversed', 'evidence': ev('f')}
        assert client.post(path, json=body, headers={'Idempotency-Key': 'review'}).status_code == 403
        app.dependency_overrides[current_principal] = lambda: CHECKER
        assert client.post(path, json=body, headers={'Idempotency-Key': 'review'}).status_code == 403
        app.dependency_overrides[current_principal] = lambda: principal('appeal-reviewer')
        r = client.post(path, json=body, headers={'Idempotency-Key': 'review'})
        assert r.status_code == 200, r.text
        assert r.json()['data']['awarded_minor'] == 0
