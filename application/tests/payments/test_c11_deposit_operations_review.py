"""Operations reads never replace source authority or repair a money record."""
import pytest
from sqlalchemy import func, select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Ledger
from go_hotel.services.rental_deposit_review import review
from go_hotel.services import rental_deposit_money as money
from go_hotel.mobility.rental import damage
from tests.payments.test_c11_rental_deposit_money import (
    obligation, args, decide, settle, close_return, OWNER, CHECKER, principal, ev)


def test_review_derives_authorize_then_decision_amounts_from_sources(obligation):
    before = review(CHECKER, 'deposit-order')
    assert before['can_authorize'] is True and before['money']['state'] == 'NOT_AUTHORIZED'
    assert before['source']['amount_minor'] == 200000
    money.authorize(CHECKER, *args(obligation))
    decision = decide(obligation, 4000)
    after = review(CHECKER, 'deposit-order')
    assert after['can_authorize'] is False
    assert after['decisions'][0]['can_settle'] is True
    assert after['decisions'][0]['decision']['decision_hash'] == decision['decision_hash']
    assert after['decisions'][0]['decision']['awarded_minor'] == 4000


def test_unknown_review_has_no_mutation_permission_and_preserves_records(obligation):
    authorization = money.authorize(CHECKER, *args(obligation))
    with SessionLocal.begin() as session:
        session.get(Movement, authorization['movement_ids'][0]).state = 'UNKNOWN_EXTERNAL_STATE'
    result = review(CHECKER, 'deposit-order')
    assert result['money']['state'] == 'RECONCILIATION_REQUIRED'
    assert result['money']['authorized_minor'] is None
    assert result['can_authorize'] is False and not any(item['can_settle'] for item in result['decisions'])
    assert result['movements'][0]['state'] == 'UNKNOWN_EXTERNAL_STATE'
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Movement)) == 1
        assert session.get(Movement, authorization['movement_ids'][0]).state == 'UNKNOWN_EXTERNAL_STATE'
        assert session.scalar(select(func.count()).select_from(Ledger)) == 0


def test_release_requires_independent_return_fact(obligation):
    money.authorize(CHECKER, *args(obligation))
    assert review(CHECKER, 'deposit-order')['release'] is None
    closure = close_return(obligation)
    result = review(CHECKER, 'deposit-order')
    assert result['release']['can_release'] is True
    assert result['release']['fact']['release_hash'] == closure['release_hash']
    assert result['decisions'] == []


def test_settled_money_does_not_license_new_appeal_payment(obligation):
    money.authorize(CHECKER, *args(obligation))
    decision = decide(obligation)
    settle(obligation, decision)
    result = review(CHECKER, 'deposit-order')
    assert result['money']['state'] == 'SETTLED' and not result['decisions'][0]['can_settle']
    assert result['decisions'][0]['blocker'] == 'SETTLED_MONEY_REQUIRES_SEPARATE_COMPENSATION_REVIEW'
    damage.appeal(OWNER, 'deposit-order', decision['case_id'], 'appeal', decision['case_version'], 'Review please', ev('f'))
    appealed = review(CHECKER, 'deposit-order')
    assert appealed['money']['state'] == 'SETTLED' and not appealed['decisions'][0]['can_settle']
    assert appealed['decisions'][0]['blocker'] == 'DEPOSIT_DECISION_HELD'


@pytest.mark.parametrize('actor', [OWNER, principal('supplier', 'SUPPLIER_USER'), principal('reader', permissions={'admin:read'})])
def test_review_requires_finance_admin_permission(obligation, actor):
    with pytest.raises(PermissionError): review(actor, 'deposit-order')


def test_http_review_requires_admin_role_and_permission(obligation):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from go_hotel.api.routes.rental_deposit_money import router
    from go_hotel.security.deps import current_principal
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[current_principal] = lambda: OWNER
    path = '/internal/v1/admin/mobility/rentals/orders/deposit-order/deposit-money-review'
    with TestClient(app) as client:
        assert client.get(path).status_code == 403
        app.dependency_overrides[current_principal] = lambda: CHECKER
        result = client.get(path)
        assert result.status_code == 200 and result.json()['data']['read_only'] is True
