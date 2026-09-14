"""C04: rental refund completion requires the frozen plan's actual ledger receipts."""
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import MobilityRentalOrderRow, MobilityRefundRow
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
from tests.test_depth33_mobility_refund_consent import booked
from test_depth21_refund_recovery import refunded_movements


@pytest.mark.parametrize('fault', ['absent', 'empty', 'capture', 'foreign'])
def test_unverified_confirmed_receipt_keeps_rental_pending_and_resumes_once(monkeypatch, fault):
    svc, owner, oid = booked('RENTAL')
    quote = svc.refund_quote(owner, oid)
    receipt = {'state': 'CONFIRMED', 'money_movement_ids': ['absent']}
    if fault == 'empty':
        receipt['money_movement_ids'] = []
    elif fault == 'capture':
        receipt['money_movement_ids'] = [money.original('RENTAL', oid)[2].money_movement_id]
    elif fault == 'foreign':
        other_svc, other_owner, other_oid = booked('RENTAL')
        other_quote = other_svc.refund_quote(other_owner, other_oid)
        other_svc.cancel(other_owner, other_oid, other_quote['quote_hash'])
        receipt['money_movement_ids'] = [refunded_movements()[0].money_movement_id]
    before = len(refunded_movements())
    original = money.execute_refund_plan
    monkeypatch.setattr(money, 'execute_refund_plan', lambda *a, **kw: receipt)
    with pytest.raises(ValueError, match='MONEY_NOT_CONFIRMED'):
        svc.cancel(owner, oid, quote['quote_hash'])
    assert svc.get(owner, oid)['status'] == 'REFUND_PENDING'
    with SessionLocal() as session:
        row = session.scalar(select(MobilityRefundRow).where(MobilityRefundRow.order_id == oid))
        assert row.status == 'REFUND_PENDING'
        assert row.settlement_plan_json
    assert len(refunded_movements()) == before
    monkeypatch.setattr(money, 'execute_refund_plan', original)
    result = svc.cancel(owner, oid, quote['quote_hash'])
    assert result['status'] == 'REFUND_COMPLETED'
    assert svc.cancel(owner, oid, quote['quote_hash']) == result
    assert len(refunded_movements()) == before + 1


def test_completed_refund_cannot_claim_success_with_contradictory_order_state():
    svc, owner, oid = booked('RENTAL')
    quote = svc.refund_quote(owner, oid)
    svc.cancel(owner, oid, quote['quote_hash'])
    with SessionLocal.begin() as session:
        session.get(MobilityRentalOrderRow, oid).status = 'CONFIRMED'
    with pytest.raises(ValueError, match='RECONCILIATION_REQUIRED'):
        svc.cancel(owner, oid, quote['quote_hash'])
    assert len(refunded_movements()) == 1


def test_same_order_earlier_equal_refund_cannot_complete_current_cancellation(client, monkeypatch):
    from tests.test_depth06_rental_settlement import paid, move, balances
    from go_hotel.mobility.rental.service import rental_service as svc
    owner, oid, _ = paid(client)
    move(owner, oid, 2)
    move(owner, oid, 1)
    quote = svc.refund_quote(owner, oid)
    assert quote['refund_amount_minor'] == 42000
    previous = refunded_movements()[0]
    assert previous.amount_minor == quote['refund_amount_minor']
    original = money.execute_refund_plan
    monkeypatch.setattr(money, 'execute_refund_plan', lambda *a, **kw: {
        'state': 'CONFIRMED', 'money_movement_ids': [previous.money_movement_id]})
    with pytest.raises(ValueError, match='REFUND_RECEIPT_PLAN_MISMATCH'):
        svc.cancel(owner, oid, quote['quote_hash'])
    assert svc.get(owner, oid)['status'] == 'REFUND_PENDING'
    assert balances() == {'CAPTURE': 126000, 'REFUND': 84000}
    with SessionLocal() as session:
        refund = session.scalar(select(MobilityRefundRow).where(MobilityRefundRow.order_id == oid))
        assert refund.status == 'REFUND_PENDING'
        assert refund.settlement_plan_json[0]['key'] != previous.idempotency_key
    monkeypatch.setattr(money, 'execute_refund_plan', original)
    result = svc.cancel(owner, oid, quote['quote_hash'])
    assert result['status'] == 'REFUND_COMPLETED'
    assert svc.cancel(owner, oid, quote['quote_hash']) == result
    assert balances() == {'CAPTURE': 126000, 'REFUND': 126000}
    assert len(refunded_movements()) == 3
