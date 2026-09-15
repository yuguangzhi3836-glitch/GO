"""C03: real overlapping transactions at the checkout/root handoff."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import select

from go_hotel.autonomy.durable import transaction
from go_hotel.db.models import (
    OmnichannelMoneyMovementRow as Movement, OmnichannelPaymentIntentRow as Intent,
    RailChangeQuoteRow, VerticalCapacityClaimRow as Claim,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services import vertical_capacity as capacity
from go_hotel.services import vertical_reservation_expiry as expiry
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payments
from go_hotel.services.vertical_money_bridge import vertical_money_bridge
from test_depth24_expiry import pending, age, cancel, rail, bridge, ledger
from test_depth21_refund_recovery import booked


@pytest.mark.parametrize('winner', ['expiry', 'cancel'])
def test_closed_reservation_wins_after_checkout_guard_before_payment_root(monkeypatch, winner):
    oid = pending('RAIL')['order_id']
    entered, finish = Event(), Event()
    original = bridge.checkout_contract
    def paused(*args, **kwargs):
        entered.set()
        assert finish.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(bridge, 'checkout_contract', paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        payment = pool.submit(rail.checkout, 'owner', oid, 'isolated')
        try:
            assert entered.wait(10)
            if winner == 'expiry':
                age('RAIL', oid)
                assert expiry.expire_one('RAIL', oid) == 'EXPIRED'
            else:
                assert cancel('RAIL', oid)['status'] == 'CANCELLED'
        finally:
            finish.set()
        with pytest.raises(ValueError, match='NOT_PAYABLE'):
            payment.result(timeout=15)
    assert rail.order('owner', oid)['status'] == 'CANCELLED'
    assert ledger() == 0
    with SessionLocal() as session:
        assert not list(session.scalars(select(Intent)))
        assert not list(session.scalars(select(Movement)))


def test_committed_payment_root_blocks_cancel_and_expiry_during_capture_handoff(monkeypatch):
    oid = pending('RAIL')['order_id']
    entered, finish = Event(), Event()
    original = payments.select_channel
    def paused(*args, **kwargs):
        entered.set()
        assert finish.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(payments, 'select_channel', paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        payment = pool.submit(rail.checkout, 'owner', oid, 'isolated')
        try:
            assert entered.wait(10)
            age('RAIL', oid)
            with pytest.raises(ValueError, match='PAYMENT_ALREADY_STARTED'):
                cancel('RAIL', oid)
            assert expiry.expire_one('RAIL', oid) == 'UNCHANGED'
            assert ledger() == 2
        finally:
            finish.set()
        payment.result(timeout=15)
    with SessionLocal() as session:
        assert len(list(session.scalars(select(Intent)))) == 1
        assert len(list(session.scalars(select(Movement).where(Movement.movement_type == 'CAPTURE')))) == 1
    assert ledger() == 2


def test_full_target_capacity_rejects_before_supplemental_money_or_original_release(monkeypatch):
    svc, owner, oid = booked('RAIL')
    original = svc.order(owner, oid)
    q = svc.change_quote(owner, oid, '2026-09-16')
    with SessionLocal() as session:
        quote = session.get(RailChangeQuoteRow, q['quote_id'])
        seat = quote.new_seat_class
        target = capacity.rail_resource({'train_no': quote.new_train_no, 'travel_date': quote.new_travel_date, 'seat_class': seat})
        money_before = [x.money_movement_id for x in session.scalars(select(Movement))]
    with transaction(SessionLocal) as session:
        capacity.reserve_in(session, 'RAIL', 'other-fully-booked-order', 'ORIGINAL', target,
                            capacity.RAIL_LIMITS[seat], capacity.RAIL_LIMITS[seat])
    calls = []
    original_adjust = vertical_money_bridge.prepare_adjustment
    def observed_adjustment(*args, **kwargs):
        calls.append(args)
        return original_adjust(*args, **kwargs)
    monkeypatch.setattr(vertical_money_bridge, 'prepare_adjustment', observed_adjustment)
    with pytest.raises(ValueError, match='INVENTORY_CHANGED'):
        svc.execute_change(owner, oid, q['quote_id'])
    assert calls == []
    assert svc.order(owner, oid)['journey'] == original['journey']
    assert svc.order(owner, oid)['status'] == 'TICKETED'
    with SessionLocal() as session:
        assert session.get(RailChangeQuoteRow, q['quote_id']).status == 'QUOTED'
        claims = list(session.scalars(select(Claim).where(Claim.order_id == oid, Claim.state == 'ALLOCATED')))
        assert len(claims) == 1 and claims[0].slot == 'ORIGINAL'
        assert [x.money_movement_id for x in session.scalars(select(Movement))] == money_before
