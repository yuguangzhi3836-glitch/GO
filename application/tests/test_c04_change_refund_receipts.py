"""A rental shortening must be proven by its own durable refund allocation."""
import pytest

from go_hotel.db.models import RentalChangeQuoteRow as Quote
from go_hotel.db.session import SessionLocal
from go_hotel.mobility.rental import changes
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
from tests.test_depth33_mobility_refund_consent import booked
from test_depth21_refund_recovery import refunded_movements


def shorten(owner, order_id, day):
    return changes.quote(owner, order_id, '2026-10-10T10:00:00+08:00',
                         f'2026-10-{day:02d}T10:00:00+08:00')


def execute(owner, order_id, quote):
    return changes.execute(owner, order_id, quote['quote_id'],
                           quote['difference_minor'], quote['currency'])


@pytest.mark.parametrize('fault', ['absent', 'empty', 'capture', 'foreign', 'duplicate'])
def test_unproven_change_refund_preserves_dates_and_recovers_once(monkeypatch, fault):
    svc, owner, oid = booked('RENTAL')
    quote = shorten(owner, oid, 12)
    before = svc.get(owner, oid)
    receipt = {'state': 'CONFIRMED', 'money_movement_ids': ['absent']}
    if fault == 'empty':
        receipt['money_movement_ids'] = []
    elif fault == 'capture':
        receipt['money_movement_ids'] = [money.original('RENTAL', oid)[2].money_movement_id]
    elif fault in {'foreign', 'duplicate'}:
        _, other_owner, other_oid = booked('RENTAL')
        execute(other_owner, other_oid, shorten(other_owner, other_oid, 12))
        mid = refunded_movements()[0].money_movement_id
        receipt['money_movement_ids'] = [mid] * (2 if fault == 'duplicate' else 1)
    count = len(refunded_movements())
    original = money.execute_refund_plan
    monkeypatch.setattr(money, 'execute_refund_plan', lambda *a, **kw: receipt)

    with pytest.raises(ValueError, match='REFUND_MONEY_NOT_CONFIRMED'):
        execute(owner, oid, quote)

    pending = svc.get(owner, oid)
    assert pending['status'] == 'CHANGE_PENDING'
    assert (pending['pickup_at'], pending['return_at'], pending['total_amount_minor']) == (
        before['pickup_at'], before['return_at'], before['total_amount_minor'])
    assert not any(e['kind'] == 'CHANGE_EXECUTED' for e in pending['evidence'])
    with SessionLocal() as session:
        frozen = session.get(Quote, quote['quote_id'])
        assert frozen.status == 'MONEY_PENDING' and frozen.refund_plan_json
        plan = list(frozen.refund_plan_json)
    assert len(refunded_movements()) == count

    monkeypatch.setattr(money, 'execute_refund_plan', original)
    result = execute(owner, oid, quote)
    assert result['status'] == 'EXECUTED'
    assert execute(owner, oid, quote) == result
    assert svc.get(owner, oid)['return_at'] == quote['new_return_at']
    assert len(refunded_movements()) == count + 1
    with SessionLocal() as session:
        assert session.get(Quote, quote['quote_id']).refund_plan_json == plan


def test_same_order_equal_earlier_receipt_cannot_finalize_new_change(monkeypatch):
    svc, owner, oid = booked('RENTAL')
    execute(owner, oid, shorten(owner, oid, 12))
    old = refunded_movements()[0]
    quote = shorten(owner, oid, 11)
    assert old.amount_minor == -quote['difference_minor']
    original = money.execute_refund_plan
    monkeypatch.setattr(money, 'execute_refund_plan', lambda *a, **kw: {
        'state': 'CONFIRMED', 'money_movement_ids': [old.money_movement_id]})

    with pytest.raises(ValueError, match='REFUND_RECEIPT_PLAN_MISMATCH'):
        execute(owner, oid, quote)

    assert svc.get(owner, oid)['status'] == 'CHANGE_PENDING'
    assert svc.get(owner, oid)['return_at'] == '2026-10-12T10:00:00+08:00'
    assert len(refunded_movements()) == 1
    monkeypatch.setattr(money, 'execute_refund_plan', original)
    assert execute(owner, oid, quote)['status'] == 'EXECUTED'
    assert len(refunded_movements()) == 2
