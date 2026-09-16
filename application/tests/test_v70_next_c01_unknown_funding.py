"""C01-02: ambiguous mixed cash/credit funds stop settlement; response loss replays once."""
import pytest
from sqlalchemy import select
from go_hotel.db.models import (AlipayAuthorizationRow as Authorization,
    HostedDirectReservationRow as Reservation,
    OmnichannelMoneyMovementRow as Movement, HostedStayCreditRow as Credit,
    HostedCreditAllocationRow as Allocation, HostedCreditValueEventRow as CreditEvent)
from go_hotel.db.session import SessionLocal
from tests.test_depth09_stay_credit import issued, redemption, redeem
from tests.test_depth48_hosted_forfeiture import checkin
from tests.test_depth07_hosted_money import summary, guest, payment, PROOF
from go_hotel.services import hosted_money


def ready(client, monkeypatch):
    original, owner, _, _, _, credit = issued(client, monkeypatch)
    quote = redemption(original, owner, credit, 100000)
    redeemed = redeem(original, owner, credit, quote)
    order = {**original, 'hosted_reservation_id': redeemed['reservation_id'],
        'check_in': quote['check_in'], 'check_out': quote['check_out']}
    sid = checkin(order)
    guest.checkout(sid, PROOF, 'hotel')
    with SessionLocal() as session:
        aid = session.scalar(select(Authorization).where(
            Authorization.hosted_reservation_id == order['hosted_reservation_id'])).authorization_id
    payment.fulfill(aid, PROOF, 'hotel')
    return order, aid, credit


def allocation_state(order):
    with SessionLocal() as session:
        allocation = session.get(Allocation, order['hosted_reservation_id'])
        events = list(session.scalars(select(CreditEvent).where(CreditEvent.reservation_id == order['hosted_reservation_id'])))
        return (allocation.state, allocation.fulfilled_minor, allocation.restored_minor,
                sorted((e.event_id, e.event_hash) for e in events))


def test_active_authorization_currency_mismatch_requires_reconciliation(client, monkeypatch):
    original, owner, _, _, _, credit = issued(client, monkeypatch)
    quote = redemption(original, owner, credit, 100000)
    redeemed = redeem(original, owner, credit, quote)
    reservation_id = redeemed['reservation_id']
    with SessionLocal.begin() as session:
        authorization = session.scalar(select(Authorization).where(
            Authorization.hosted_reservation_id == reservation_id))
        authorization.currency = 'USD'
    with pytest.raises(ValueError, match='PAYMENT_RECONCILIATION_REQUIRED'):
        payment.authorize(reservation_id, {'mode': 'CONTRACT_DRY_RUN'}, 'currency-mismatch-retry')
    with SessionLocal() as session:
        authorizations = list(session.scalars(select(Authorization).where(
            Authorization.hosted_reservation_id == reservation_id)))
        assert len(authorizations) == 1 and authorizations[0].currency == 'USD'


@pytest.mark.parametrize('mismatch', ['amount', 'currency'])
def test_final_capture_revalidates_authorization_terms(client, monkeypatch, mismatch):
    order, aid, _ = ready(client, monkeypatch)
    with SessionLocal.begin() as session:
        reservation = session.get(Reservation, order['hosted_reservation_id'])
        if mismatch == 'amount':
            reservation.amount_minor += 1
        else:
            reservation.currency = 'USD'
    before = summary(order)
    with pytest.raises(ValueError, match='PAYMENT_RECONCILIATION_REQUIRED'):
        payment.capture(aid, {'mode': 'CONTRACT_DRY_RUN'})
    with SessionLocal() as session:
        authorization = session.get(Authorization, aid)
        assert authorization.state == 'FULFILLED_ELIGIBLE_FOR_CONTRACT_CAPTURE'
        assert not [m for m in hosted_money.movements(session, authorization)
                    if m.movement_type == 'CAPTURE']
    assert summary(order) == before


@pytest.mark.parametrize('source', ['cash_authorization', 'credit_capture'])
def test_unknown_source_blocks_both_funding_legs_until_test_fixture_reconciles(client, monkeypatch, source):
    order, aid, credit = ready(client, monkeypatch)
    with SessionLocal.begin() as session:
        if source == 'cash_authorization':
            auth = session.get(Authorization, aid)
            movement = next(m for m in hosted_money.active_movements(session, auth) if m.movement_type == 'AUTHORIZATION')
        else:
            movement = session.get(Movement, session.get(Credit, credit['credit_id']).source_capture_id)
        mid = movement.money_movement_id
        movement.state = 'UNKNOWN_EXTERNAL_STATE'
    before = allocation_state(order)
    with pytest.raises(ValueError, match='RECONCILIATION_REQUIRED|FUNDING_FACT_MISMATCH'):
        payment.capture(aid, {'mode': 'CONTRACT_DRY_RUN'})
    assert allocation_state(order) == before
    with SessionLocal() as session:
        assert session.get(Authorization, aid).state == 'FULFILLED_ELIGIBLE_FOR_CONTRACT_CAPTURE'
        assert not [m for m in hosted_money.movements(session, session.get(Authorization, aid)) if m.movement_type == 'CAPTURE']
    # This restores a fault-injected local fixture; it is not a production reconciliation API.
    with SessionLocal.begin() as session:
        session.get(Movement, mid).state = 'CONFIRMED'
    payment.capture(aid, {'mode': 'CONTRACT_DRY_RUN'})
    funds = summary(order)
    assert funds['capture_minor'] == 38000 and funds['held_minor'] == 0
    assert allocation_state(order)[0:2] == ('SETTLED', 162000)


def test_lost_response_after_mixed_settlement_replays_without_second_charge(client, monkeypatch):
    order, aid, _ = ready(client, monkeypatch)
    real_capture = payment.capture
    def lose_response(*args, **kwargs):
        real_capture(*args, **kwargs)
        raise RuntimeError('RESPONSE_LOST_AFTER_COMMIT')
    monkeypatch.setattr(payment, 'capture', lose_response)
    with pytest.raises(RuntimeError, match='RESPONSE_LOST_AFTER_COMMIT'):
        payment.capture(aid, {'mode': 'CONTRACT_DRY_RUN'})
    funds = summary(order)
    allocated = allocation_state(order)
    monkeypatch.setattr(payment, 'capture', real_capture)
    payment.capture(aid, {'mode': 'CONTRACT_DRY_RUN'})
    assert summary(order) == funds and allocation_state(order) == allocated
    assert funds['capture_minor'] == 38000 and funds['held_minor'] == 0
    assert len([m for m in funds['movements'] if m['type'] == 'CAPTURE']) == 1
