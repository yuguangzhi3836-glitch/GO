"""C11 regression coverage for hosted mixed-funding UNKNOWN recovery.

Adapted from the prior #531 candidate to keep the scenario inside the
payments-owned test surface for this builder run.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from go_hotel.db.models import (
    AlipayAuthorizationRow as Authorization,
    HostedCreditAllocationRow as Allocation,
    HostedCreditValueEventRow as CreditEvent,
    HostedStayCreditRow as Credit,
    OmnichannelMoneyMovementRow as Movement,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services import hosted_money
from tests.test_depth07_hosted_money import PROOF, guest, payment, summary
from tests.test_depth09_stay_credit import issued, redeem, redemption
from tests.test_depth48_hosted_forfeiture import checkin


def ready_order(client, monkeypatch):
    original, owner, _, _, _, credit = issued(client, monkeypatch)
    quote = redemption(original, owner, credit, 100000)
    redeemed = redeem(original, owner, credit, quote)
    order = {
        **original,
        "hosted_reservation_id": redeemed["reservation_id"],
        "check_in": quote["check_in"],
        "check_out": quote["check_out"],
    }
    stay_id = checkin(order)
    guest.checkout(stay_id, PROOF, "hotel")
    with SessionLocal() as session:
        authorization_id = session.scalar(
            select(Authorization).where(
                Authorization.hosted_reservation_id == order["hosted_reservation_id"]
            )
        ).authorization_id
    payment.fulfill(authorization_id, PROOF, "hotel")
    return order, authorization_id, credit


def allocation_state(order):
    with SessionLocal() as session:
        allocation = session.get(Allocation, order["hosted_reservation_id"])
        events = list(
            session.scalars(
                select(CreditEvent).where(
                    CreditEvent.reservation_id == order["hosted_reservation_id"]
                )
            )
        )
        return (
            allocation.state,
            allocation.fulfilled_minor,
            allocation.restored_minor,
            sorted((event.event_id, event.event_hash) for event in events),
        )


@pytest.mark.parametrize("source", ["cash_authorization", "credit_capture"])
def test_unknown_source_blocks_mixed_funding_settlement_until_reconciled(
    client, monkeypatch, source
):
    order, authorization_id, credit = ready_order(client, monkeypatch)
    with SessionLocal.begin() as session:
        if source == "cash_authorization":
            authorization = session.get(Authorization, authorization_id)
            movement = next(
                item
                for item in hosted_money.active_movements(session, authorization)
                if item.movement_type == "AUTHORIZATION"
            )
        else:
            movement = session.get(
                Movement,
                session.get(Credit, credit["credit_id"]).source_capture_id,
            )
        movement_id = movement.money_movement_id
        movement.state = "UNKNOWN_EXTERNAL_STATE"

    before = allocation_state(order)
    with pytest.raises(ValueError, match="RECONCILIATION_REQUIRED|FUNDING_FACT_MISMATCH"):
        payment.capture(authorization_id, {"mode": "CONTRACT_DRY_RUN"})

    assert allocation_state(order) == before
    with SessionLocal() as session:
        authorization = session.get(Authorization, authorization_id)
        assert authorization.state == "FULFILLED_ELIGIBLE_FOR_CONTRACT_CAPTURE"
        captures = [
            item
            for item in hosted_money.movements(session, authorization)
            if item.movement_type == "CAPTURE"
        ]
        assert not captures

    with SessionLocal.begin() as session:
        session.get(Movement, movement_id).state = "CONFIRMED"

    payment.capture(authorization_id, {"mode": "CONTRACT_DRY_RUN"})
    funds = summary(order)
    assert funds["capture_minor"] == 38000
    assert funds["held_minor"] == 0
    assert allocation_state(order)[0:2] == ("SETTLED", 162000)


def test_lost_response_after_mixed_settlement_replays_without_second_capture(
    client, monkeypatch
):
    order, authorization_id, _ = ready_order(client, monkeypatch)
    real_capture = payment.capture

    def lose_response(*args, **kwargs):
        real_capture(*args, **kwargs)
        raise RuntimeError("RESPONSE_LOST_AFTER_COMMIT")

    monkeypatch.setattr(payment, "capture", lose_response)
    with pytest.raises(RuntimeError, match="RESPONSE_LOST_AFTER_COMMIT"):
        payment.capture(authorization_id, {"mode": "CONTRACT_DRY_RUN"})

    funds = summary(order)
    allocation = allocation_state(order)

    monkeypatch.setattr(payment, "capture", real_capture)
    payment.capture(authorization_id, {"mode": "CONTRACT_DRY_RUN"})

    assert summary(order) == funds
    assert allocation_state(order) == allocation
    assert funds["capture_minor"] == 38000
    assert funds["held_minor"] == 0
    assert len([item for item in funds["movements"] if item["type"] == "CAPTURE"]) == 1
