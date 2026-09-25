import pytest
from sqlalchemy import select

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (OrderSupplierFulfillmentRow as Fulfillment,
    OmnichannelMoneyMovementRow as Movement, PaymentOrderFactBindingRow as Binding)
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as svc
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from tests.test_depth20_api_fulfillment import captured


@pytest.mark.parametrize('state', ['UNKNOWN_EXTERNAL_STATE', 'SUPPLIER_FAILED'])
@pytest.mark.parametrize('corruption', ['missing_capture', 'wrong_currency', 'wrong_binding', 'foreign_parent', 'unknown_movement_type'])
def test_supplier_outcome_without_bound_capture_cannot_assert_paid(client, state, corruption):
    _, order, _, fid, _ = captured(client)
    with SessionLocal() as session:
        fulfillment = session.get(Fulfillment, fid)
        cap = session.scalar(select(Movement).where(Movement.root_payment_intent_id == fulfillment.payment_intent_id,
            Movement.movement_type == 'CAPTURE'))
        if corruption == 'missing_capture': session.delete(cap)
        elif corruption == 'wrong_currency': cap.currency = 'USD'
        elif corruption == 'foreign_parent': cap.parent_movement_id = 'foreign-authorization'
        elif corruption == 'unknown_movement_type': cap.movement_type = 'UNVERIFIED_CAPTURE'
        else:
            binding = session.scalar(select(Binding).where(Binding.payment_intent_id == fulfillment.payment_intent_id))
            binding.payee_id = 'another-supplier'
        session.commit()
    result = svc.record_supplier_fact(fid, {'state': state, 'evidence_reference': 'supplier://unknown'})
    assert result['unified_lifecycle']['payment_state'] == 'UNKNOWN_EXTERNAL_STATE'


@pytest.mark.parametrize('refund_fraction,expected', [(0, 'PAID'), (2, 'PARTIALLY_REFUNDED'), (1, 'REFUNDED')])
def test_supplier_unknown_preserves_independent_bound_money_fact(client, refund_fraction, expected):
    _, order, _, fid, _ = captured(client)
    with SessionLocal() as session:
        fulfillment = session.get(Fulfillment, fid)
        iid = fulfillment.payment_intent_id
        cap = session.scalar(select(Movement).where(Movement.root_payment_intent_id == iid, Movement.movement_type == 'CAPTURE'))
        cap_id, amount = cap.money_movement_id, cap.amount_minor
    if refund_fraction:
        money.create(iid, {'movement_type': 'REFUND', 'parent_movement_id': cap_id,
            'amount_minor': amount // refund_fraction, 'mode': 'CONTRACT_SIMULATOR',
            'evidence': ['isolated://refund']}, 'bound-refund', 'test')
    result = svc.record_supplier_fact(fid, {'state': 'UNKNOWN_EXTERNAL_STATE', 'evidence_reference': 'supplier://unknown'})
    assert result['unified_lifecycle']['payment_state'] == expected


@pytest.mark.parametrize('change', ['missing_capture', 'refund'])
def test_same_supplier_event_refreshes_money_without_repeating_supplier_effect(client, change):
    from go_hotel.db.models import OrderSupplierFulfillmentEventRow as Event
    _, _, _, fid, _ = captured(client)
    fact = {'state': 'UNKNOWN_EXTERNAL_STATE', 'evidence_reference': 'supplier://same'}
    first = svc.record_supplier_fact(fid, fact)
    assert first['unified_lifecycle']['payment_state'] == 'PAID'
    with SessionLocal() as session:
        f = session.get(Fulfillment, fid)
        iid, updated_at = f.payment_intent_id, f.updated_at
        events = list(session.scalars(select(Event.order_supplier_fulfillment_event_id).where(Event.order_supplier_fulfillment_id == fid)))
        cap = session.scalar(select(Movement).where(Movement.root_payment_intent_id == iid, Movement.movement_type == 'CAPTURE'))
        cap_id, amount = cap.money_movement_id, cap.amount_minor
        if change == 'missing_capture':
            session.delete(cap)
            session.commit()
    if change == 'refund':
        money.create(iid, {'movement_type': 'REFUND', 'parent_movement_id': cap_id,
            'amount_minor': amount, 'mode': 'CONTRACT_SIMULATOR', 'evidence': ['isolated://refund']}, 'late-refund', 'test')
    replay = svc.record_supplier_fact(fid, fact)
    assert replay['replayed'] is True
    assert replay['unified_lifecycle']['payment_state'] == ('REFUNDED' if change == 'refund' else 'UNKNOWN_EXTERNAL_STATE')
    with SessionLocal() as session:
        assert session.get(Fulfillment, fid).updated_at == updated_at
        assert list(session.scalars(select(Event.order_supplier_fulfillment_event_id).where(Event.order_supplier_fulfillment_id == fid))) == events


@pytest.mark.parametrize('fault', ['wrong_binding', 'refund'])
def test_late_supplier_confirmation_requires_bound_unrefunded_money(client, fault):
    _, _, _, fid, confirmation = captured(client)
    with SessionLocal() as session:
        f = session.get(Fulfillment, fid)
        iid = f.payment_intent_id
        cap = session.scalar(select(Movement).where(Movement.root_payment_intent_id == iid, Movement.movement_type == 'CAPTURE'))
        cap_id, amount = cap.money_movement_id, cap.amount_minor
        if fault == 'wrong_binding':
            binding = session.scalar(select(Binding).where(Binding.payment_intent_id == iid))
            binding.payee_id = 'another-payee'
            session.commit()
    if fault == 'refund':
        money.create(iid, {'movement_type': 'REFUND', 'parent_movement_id': cap_id,
            'amount_minor': amount, 'mode': 'CONTRACT_SIMULATOR', 'evidence': ['isolated://refund']}, 'before-confirm-refund', 'test')
    with pytest.raises(ValueError, match='FULL_CAPTURED_MONEY_GRAPH_REQUIRED'):
        svc.record_supplier_fact(fid, confirmation)
