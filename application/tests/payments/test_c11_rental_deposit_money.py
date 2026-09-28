"""C04 source facts to the existing C11 graph, entirely isolated fixtures."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from go_hotel.core.config import settings
from go_hotel.db.models import (MobilityRentalOrderRow as Order, PaymentOrderRootRow as Root,
    OmnichannelPaymentIntentRow as Intent, OmnichannelMoneyMovementRow as Movement,
    OmnichannelLedgerEntryRow as Ledger, PaymentOrderFactBindingRow as Binding)
from go_hotel.db.session import SessionLocal
from go_hotel.mobility.rental import damage, deposit_authority as authority
from go_hotel.services import rental_deposit_money as service
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from tests.test_rental_damage_disputes import principal, OWNER, MAKER, CHECKER, ev


@pytest.fixture
def obligation():
    t = datetime(2026, 9, 25)
    with SessionLocal.begin() as session:
        session.add(Order(order_id='deposit-order', account_id=OWNER.user_id, status='CONFIRMED',
            pickup_location='A', return_location='A', pickup_at='2026-09-25T10:00:00',
            return_at='2026-09-27T10:00:00', vehicle_class='COMPACT',
            insurance={'type': 'BASIC', 'excess_minor': 500000}, mileage={}, deposit_minor=200000,
            total_amount_minor=84000, currency='CNY', drivers=[], supplier_reference=None,
            created_at=t, updated_at=t))
    proposed = authority.propose(OWNER, 'deposit-order', 'propose')
    return authority.accept(OWNER, 'deposit-order', proposed['obligation_id'], 'accept',
                            proposed['revision'], proposed['source_hash'], True)


def args(obligation):
    return ('deposit-order', obligation['obligation_id'], obligation['revision'], obligation['source_hash'])


def decide(obligation, award=4000):
    with SessionLocal.begin() as session:
        session.get(Order, 'deposit-order').status = 'COMPLETED'
    case = damage.open_case(MAKER, 'deposit-order', 'open', 10000, 'CNY', ev('a'), ev('b'))
    case = damage.respond(OWNER, 'deposit-order', case['case_id'], 'response', 1, 'DISPUTE', ev('c'))
    case = damage.adjudicate(CHECKER, 'deposit-order', case['case_id'], 'adjudicate', 2, award,
                            'Isolated adjudication', ev('d'))
    decision = authority.decision_preview(CHECKER, 'deposit-order', obligation['obligation_id'], case['case_id'])
    return decision


def settle(obligation, decision):
    return service.settle(CHECKER, *args(obligation), decision['case_id'], decision['case_version'], decision['decision_hash'])


def test_agreement_is_not_money_and_authorization_has_own_root(obligation):
    before = service.status(OWNER, *args(obligation))
    assert before['state'] == 'NOT_AUTHORIZED' and before['authorized_minor'] == 0
    result = service.authorize(CHECKER, *args(obligation))
    assert result['state'] == 'AUTHORIZED' and result['authorized_minor'] == 200000
    assert result['captured_minor'] == 0 and not result['external_live']
    with SessionLocal() as session:
        root = session.scalar(select(Root))
        assert root.business_type == 'RENTAL_DEPOSIT' and root.business_id == obligation['obligation_id']
        intent = session.get(Intent, root.payment_intent_id)
        assert intent.payee_id == 'fixture-rental-merchant-v1'
        assert intent.amount_minor != session.get(Order, 'deposit-order').total_amount_minor
        assert session.scalar(select(func.count()).select_from(Ledger)) == 0
    assert service.authorize(CHECKER, *args(obligation)) == result


@pytest.mark.parametrize('award', [0, 4000, 10000])
def test_award_capture_and_remainder_release_are_atomic_idempotent(obligation, award):
    service.authorize(CHECKER, *args(obligation))
    decision = decide(obligation, award)
    result = settle(obligation, decision)
    assert result['state'] == 'SETTLED'
    assert result['captured_minor'] == award and result['released_minor'] == 200000 - award
    assert result['remaining_minor'] == 0
    assert settle(obligation, decision) == result
    with SessionLocal() as session:
        debit = session.scalar(select(func.sum(Ledger.amount_minor)).where(Ledger.direction == 'DEBIT')) or 0
        credit = session.scalar(select(func.sum(Ledger.amount_minor)).where(Ledger.direction == 'CREDIT')) or 0
        assert debit == credit == award
        assert session.scalar(select(func.count()).select_from(Root)) == 1


def test_generic_movement_route_cannot_bypass_decision(obligation):
    authorized = service.authorize(CHECKER, *args(obligation))
    with pytest.raises(ValueError, match='VERIFIED_SOURCE_SCOPE_REQUIRED'):
        money.create(authorized['payment_intent_id'], {'movement_type': 'CAPTURE', 'amount_minor': 100,
            'parent_movement_id': authorized['movement_ids'][0], 'mode': 'CONTRACT_SIMULATOR',
            'evidence': ['caller://fake-decision']}, 'bypass', 'admin')
    assert service.status(OWNER, *args(obligation))['captured_minor'] == 0


@pytest.mark.parametrize('actor', [OWNER, principal('supplier', 'SUPPLIER_USER'), principal('readonly', permissions={'admin:read'})])
def test_only_authorized_admin_can_move_isolated_deposit(obligation, actor):
    with pytest.raises(PermissionError): service.authorize(actor, *args(obligation))


def test_wrong_owner_cannot_read_balance(obligation):
    service.authorize(CHECKER, *args(obligation))
    with pytest.raises(ValueError, match='NOT_FOUND'):
        service.status(principal('other', 'CONSUMER'), *args(obligation))


@pytest.mark.parametrize('target', ['intent', 'movement', 'missing_receipt', 'binding', 'missing_root'])
def test_unknown_or_corrupt_money_never_reauthorizes_or_claims_success(obligation, target):
    authorized = service.authorize(CHECKER, *args(obligation))
    with SessionLocal.begin() as session:
        intent = session.get(Intent, authorized['payment_intent_id'])
        row = session.get(Movement, authorized['movement_ids'][0])
        if target == 'intent': intent.state = 'UNKNOWN_EXTERNAL_STATE'
        elif target == 'movement': row.state = 'UNKNOWN_EXTERNAL_STATE'
        elif target == 'missing_receipt': session.delete(row)
        elif target == 'missing_root': session.delete(session.scalar(select(Root).where(Root.payment_intent_id == intent.payment_intent_id)))
        else: session.scalar(select(Binding).where(Binding.payment_intent_id == intent.payment_intent_id)).payee_id = 'foreign'
    with pytest.raises(ValueError): service.authorize(CHECKER, *args(obligation))
    status = service.status(OWNER, *args(obligation))
    assert status['state'] == 'RECONCILIATION_REQUIRED' and status['authorized_minor'] is None


def test_wrong_source_or_decision_revision_never_moves_money(obligation):
    with pytest.raises(ValueError, match='VERSION_CONFLICT'):
        service.authorize(CHECKER, 'deposit-order', obligation['obligation_id'], 1, obligation['source_hash'])
    service.authorize(CHECKER, *args(obligation))
    decision = decide(obligation)
    with pytest.raises(ValueError, match='VERSION_CONFLICT'):
        service.settle(CHECKER, *args(obligation), decision['case_id'], decision['case_version'], '0' * 64)
    assert service.status(OWNER, *args(obligation))['captured_minor'] == 0


def test_failure_between_capture_and_release_rolls_back_both_and_retry_once(obligation, monkeypatch):
    service.authorize(CHECKER, *args(obligation))
    decision = decide(obligation)
    original = money.create_in_session
    def failure(session, iid, body, key, actor):
        if body['movement_type'] == 'RELEASE': raise RuntimeError('isolated-crash-before-release')
        return original(session, iid, body, key, actor)
    with monkeypatch.context() as patch:
        patch.setattr(money, 'create_in_session', failure)
        with pytest.raises(RuntimeError): settle(obligation, decision)
    assert service.status(OWNER, *args(obligation))['captured_minor'] == 0
    assert settle(obligation, decision)['captured_minor'] == 4000


def test_concurrent_authorization_and_settlement_retries_share_one_graph(obligation):
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: service.authorize(CHECKER, *args(obligation)), range(3)))
    assert len({item['payment_intent_id'] for item in results}) == 1
    decision = decide(obligation)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: settle(obligation, decision), range(3)))
    assert all(item == results[0] for item in results)
    assert results[0]['captured_minor'] == 4000 and results[0]['released_minor'] == 196000


def test_expiry_allows_only_release_of_existing_authorization(obligation, monkeypatch):
    service.authorize(CHECKER, *args(obligation))
    decision = decide(obligation, 0)
    future = authority.now() + timedelta(days=2)
    monkeypatch.setattr(authority, 'now', lambda: future)
    with pytest.raises(ValueError, match='EXPIRED'): service.authorize(CHECKER, *args(obligation))
    assert settle(obligation, decision)['released_minor'] == 200000


def test_production_cannot_use_simulated_money(obligation, monkeypatch):
    monkeypatch.setattr(settings, 'app_env', 'production')
    with pytest.raises(ValueError, match='FORBIDDEN'): service.authorize(CHECKER, *args(obligation))


def test_missing_capture_ledger_cannot_claim_settled_or_repeat_money(obligation):
    service.authorize(CHECKER, *args(obligation))
    decision = decide(obligation)
    settle(obligation, decision)
    with SessionLocal.begin() as session:
        session.delete(session.scalar(select(Ledger)))
    with pytest.raises(ValueError, match='LEDGER_INVALID'): settle(obligation, decision)
    assert service.status(OWNER, *args(obligation))['state'] == 'RECONCILIATION_REQUIRED'


def test_expired_source_cannot_capture_existing_authorization(obligation, monkeypatch):
    service.authorize(CHECKER, *args(obligation))
    decision = decide(obligation)
    future = authority.now() + timedelta(days=2)
    monkeypatch.setattr(authority, 'now', lambda: future)
    with pytest.raises(ValueError, match='EXPIRED'): settle(obligation, decision)
    assert service.status(OWNER, *args(obligation))['captured_minor'] == 0


def test_money_http_owner_read_and_amount_override_denial(obligation):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from go_hotel.api.routes.rental_deposit_money import router
    from go_hotel.security.deps import current_principal
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_principal] = lambda: CHECKER
    body = {'expected_revision': obligation['revision'], 'expected_source_hash': obligation['source_hash']}
    path = '/v1/mobility/rentals/orders/deposit-order/deposit-money/' + obligation['obligation_id']
    with TestClient(app) as client:
        assert client.post('/internal' + path + '/authorize', json={**body, 'amount_minor': 1}).status_code == 422
        assert client.post('/internal' + path + '/authorize', json=body).status_code == 200
        app.dependency_overrides[current_principal] = lambda: OWNER
        assert client.get(path, params=body).json()['data']['state'] == 'AUTHORIZED'
        assert client.post('/internal' + path + '/authorize', json=body).status_code == 403
        app.dependency_overrides[current_principal] = lambda: principal('supplier', 'SUPPLIER_USER')
        assert client.get(path, params=body).status_code == 409


def close_return(obligation):
    with SessionLocal.begin() as session:
        session.get(Order, 'deposit-order').status = 'COMPLETED'
    return authority.close_return(CHECKER, 'deposit-order', obligation['obligation_id'], 'return',
        obligation['revision'], obligation['source_hash'], ev('e'))


def release(obligation, closure):
    return service.release(CHECKER, *args(obligation), closure['release_revision'], closure['release_hash'])


def test_no_damage_release_is_independent_of_damage_claim_and_idempotent(obligation):
    service.authorize(CHECKER, *args(obligation))
    closure = close_return(obligation)
    result = release(obligation, closure)
    assert result['state'] == 'SETTLED' and result['released_minor'] == 200000 and result['captured_minor'] == 0
    assert release(obligation, closure) == result
    with SessionLocal() as session:
        assert damage._history(session, 'deposit-order') == []
        assert session.scalar(select(func.count()).select_from(Ledger)) == 0


def test_expired_authorization_no_damage_release_and_concurrent_retries(obligation, monkeypatch):
    service.authorize(CHECKER, *args(obligation))
    closure = close_return(obligation)
    future = authority.now() + timedelta(days=2)
    monkeypatch.setattr(authority, 'now', lambda: future)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: release(obligation, closure), range(3)))
    assert all(item == results[0] for item in results)
    assert results[0]['released_minor'] == 200000


def test_ordinary_release_cannot_bypass_open_dispute(obligation):
    service.authorize(CHECKER, *args(obligation))
    with SessionLocal.begin() as session:
        session.get(Order, 'deposit-order').status = 'COMPLETED'
    damage.open_case(MAKER, 'deposit-order', 'open', 10000, 'CNY', ev('a'), ev('b'))
    with pytest.raises(ValueError, match='DAMAGE_CASE_REQUIRES_SETTLEMENT'): close_return(obligation)
    with pytest.raises(ValueError, match='RELEASE_FACT_REQUIRED'):
        service.release(CHECKER, *args(obligation), 1, '0' * 64)


def test_release_without_authorization_does_not_manufacture_funds(obligation):
    closure = close_return(obligation)
    with pytest.raises(ValueError, match='AUTHORIZATION_REQUIRED'): release(obligation, closure)
    with pytest.raises(ValueError, match='NEW_AUTHORIZATION_NOT_ALLOWED'): service.authorize(CHECKER, *args(obligation))


def test_appeal_holds_old_decision_without_money_and_cannot_plain_release(obligation):
    service.authorize(CHECKER, *args(obligation))
    decision = decide(obligation)
    damage.appeal(OWNER, 'deposit-order', decision['case_id'], 'appeal', decision['case_version'],
                  'Disputed isolated decision', ev('f'))
    with pytest.raises(ValueError, match='DECISION_HELD'): settle(obligation, decision)
    with pytest.raises(ValueError, match='DAMAGE_CASE_REQUIRES_SETTLEMENT'): close_return(obligation)
    assert service.status(OWNER, *args(obligation))['captured_minor'] == 0


def test_original_rent_refund_and_deposit_release_remain_separate_roots(client):
    from tests.test_depth06_rental_settlement import paid
    from go_hotel.mobility.rental.service import rental_service
    account, oid, _ = paid(client)
    owner = principal(account, 'CONSUMER', set())
    proposed = authority.propose(owner, oid, 'propose')
    accepted = authority.accept(owner, oid, proposed['obligation_id'], 'accept',
                                proposed['revision'], proposed['source_hash'], True)
    source_args = (oid, accepted['obligation_id'], accepted['revision'], accepted['source_hash'])
    authorized = service.authorize(CHECKER, *source_args)
    assert rental_service.cancel(account, oid)['status'] == 'REFUND_COMPLETED'
    closure = authority.close_return(CHECKER, oid, accepted['obligation_id'], 'cancel-review',
        accepted['revision'], accepted['source_hash'], ev('e'))
    result = service.release(CHECKER, *source_args, closure['release_revision'], closure['release_hash'])
    assert result['released_minor'] == 200000 and result['captured_minor'] == 0
    with SessionLocal() as session:
        roots = list(session.scalars(select(Root)))
        deposit_root = next(root for root in roots if root.business_type == 'RENTAL_DEPOSIT')
        rental_root = next(root for root in roots if root.business_type == 'RENTAL_ORDER')
        assert deposit_root.payment_intent_id == authorized['payment_intent_id']
        assert rental_root.payment_intent_id != deposit_root.payment_intent_id
        original_refunds = list(session.scalars(select(Movement).where(Movement.root_payment_intent_id == rental_root.payment_intent_id,
            Movement.movement_type == 'REFUND')))
        assert original_refunds and all(row.state == 'CONFIRMED' for row in original_refunds)
