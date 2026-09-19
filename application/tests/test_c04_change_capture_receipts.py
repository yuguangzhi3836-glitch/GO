"""Rental extensions require the quote's actual captured adjustment, not an ID."""
import pytest
from sqlalchemy import select

from go_hotel.db.models import (OmnichannelMoneyMovementRow as Movement,
    PaymentOrderRootRow as Root, RentalChangeQuoteRow as Quote)
from go_hotel.db.session import SessionLocal
from go_hotel.mobility.rental import changes
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
from tests.test_depth33_mobility_refund_consent import booked


def extension(owner, oid):
    return changes.quote(owner, oid, '2026-10-10T10:00:00+08:00', '2026-10-14T10:00:00+08:00')


def execute(owner, oid, quote):
    return changes.execute(owner, oid, quote['quote_id'], quote['difference_minor'], 'CNY')


def assert_pending(svc, owner, oid, quote):
    order = svc.get(owner, oid)
    assert order['status'] == 'CHANGE_PENDING'
    assert order['return_at'] == '2026-10-13T10:00:00+08:00'
    assert order['total_amount_minor'] == 126000
    assert not any(e['kind'] == 'CHANGE_EXECUTED' for e in order['evidence'])
    with SessionLocal() as session:
        assert session.get(Quote, quote['quote_id']).status == 'MONEY_PENDING'


@pytest.mark.parametrize('fault', ['absent', 'original', 'authorization', 'foreign'])
def test_wrong_capture_cannot_extend_rental_and_valid_retry_recovers(monkeypatch, fault):
    svc, owner, oid = booked('RENTAL')
    quote = extension(owner, oid)
    capture_id = 'absent'
    if fault == 'original':
        capture_id = money.original('RENTAL', oid)[2].money_movement_id
    elif fault == 'foreign':
        _, other_owner, other_oid = booked('RENTAL')
        other = extension(other_owner, other_oid)
        execute(other_owner, other_oid, other)
        with SessionLocal() as session:
            root = session.scalar(select(Root).where(Root.business_type == 'RENTAL_CHANGE',
                                                    Root.business_id == other['quote_id']))
            capture_id = session.scalar(select(Movement.money_movement_id).where(
                Movement.root_payment_intent_id == root.payment_intent_id,
                Movement.movement_type == 'CAPTURE'))
    original = money.capture_adjustment

    def wrong_capture(*args):
        nonlocal capture_id
        if fault == 'authorization':
            with SessionLocal() as session:
                root = session.scalar(select(Root).where(Root.business_type == 'RENTAL_CHANGE',
                                                        Root.business_id == quote['quote_id']))
                capture_id = session.scalar(select(Movement.money_movement_id).where(
                    Movement.root_payment_intent_id == root.payment_intent_id,
                    Movement.movement_type == 'AUTHORIZATION'))
        return {'capture_id': capture_id}

    monkeypatch.setattr(money, 'capture_adjustment', wrong_capture)
    with pytest.raises(ValueError, match='RENTAL_CHANGE_CAPTURE_NOT_CONFIRMED'):
        execute(owner, oid, quote)
    assert_pending(svc, owner, oid, quote)
    monkeypatch.setattr(money, 'capture_adjustment', original)
    result = execute(owner, oid, quote)
    assert result['status'] == 'EXECUTED'
    assert execute(owner, oid, quote) == result
    assert svc.get(owner, oid)['total_amount_minor'] == 168000


@pytest.mark.parametrize('field,value', [
    ('state', 'UNKNOWN'), ('currency', 'USD'), ('amount_minor', 42001),
    ('parent_movement_id', 'absent'),
])
def test_divergent_durable_capture_keeps_rental_pending_for_reconciliation(monkeypatch, field, value):
    svc, owner, oid = booked('RENTAL')
    quote = extension(owner, oid)
    original = money.capture_adjustment
    observed = {}

    def damaged_capture(*args):
        result = original(*args)
        with SessionLocal.begin() as session:
            row = session.get(Movement, result['capture_id'])
            observed.update(id=row.money_movement_id, original=getattr(row, field))
            setattr(row, field, value)
        return result

    monkeypatch.setattr(money, 'capture_adjustment', damaged_capture)
    with pytest.raises(ValueError, match='RENTAL_CHANGE_CAPTURE_NOT_CONFIRMED'):
        execute(owner, oid, quote)
    assert_pending(svc, owner, oid, quote)

    # Model independently reconciled ledger evidence, not automatic repair.
    with SessionLocal.begin() as session:
        setattr(session.get(Movement, observed['id']), field, observed['original'])
    monkeypatch.setattr(money, 'capture_adjustment', original)
    assert execute(owner, oid, quote)['status'] == 'EXECUTED'
    with SessionLocal() as session:
        row = session.get(Movement, observed['id'])
        captures = list(session.scalars(select(Movement).where(
            Movement.root_payment_intent_id == row.root_payment_intent_id,
            Movement.movement_type == 'CAPTURE')))
        assert [r.money_movement_id for r in captures] == [observed['id']]
