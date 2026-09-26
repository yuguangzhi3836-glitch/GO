"""C04: a completed refund receipt cannot conceal a divergent order terminal state.

The rows below deliberately model reconciliation drift. Money is never sent;
only the existing rental cancellation replay/finalization path is exercised.
"""
import pytest

from go_hotel.db.models import MobilityRefundRow, MobilityRentalOrderRow
from go_hotel.db.session import SessionLocal
from go_hotel.domain.models import new_id
from go_hotel.mobility.rental.service import now, rental_service
from go_hotel.services import mobility_refund_consent as consent
from go_hotel.services.rc20_vertical_evidence import list_vertical_evidence
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money


OWNER = "c04-terminal-owner"


def seed_refund(order_status, refund_status="REFUND_COMPLETED"):
    order = rental_service.create(OWNER, {
        "offer_id": "rental_compact", "pickup_location": "SHA",
        "return_location": "SHA", "pickup_at": "2026-10-01T10:00:00",
        "return_at": "2026-10-04T10:00:00", "currency": "CNY",
        "drivers": [{"name": "C04 TEST DRIVER"}],
    })
    order_id = order["order_id"]
    with SessionLocal.begin() as s:
        s.get(MobilityRentalOrderRow, order_id).status = "CONFIRMED"
    quote = rental_service.refund_quote(OWNER, order_id)
    refund_id = new_id("c04_refund")
    with SessionLocal.begin() as s:
        row = s.get(MobilityRentalOrderRow, order_id)
        refund = MobilityRefundRow(
            refund_id=refund_id, order_id=order_id, vertical="RENTAL", fee_minor=0,
            refund_amount_minor=row.total_amount_minor, currency=row.currency,
            status=refund_status, settlement_plan_json=[], created_at=now(),
        )
        consent.freeze(s, row, refund, quote, quote["quote_hash"], "RENTAL")
        s.add(refund)
        row.status = order_status
        row.updated_at = now()
    return order_id, refund_id, quote["quote_hash"]


def snapshot(order_id, refund_id):
    with SessionLocal() as s:
        order = s.get(MobilityRentalOrderRow, order_id)
        refund = s.get(MobilityRefundRow, refund_id)
        evidence = list_vertical_evidence(s, "RENTAL", order_id)
        return (order.status, order.updated_at, refund.status,
                refund.refund_amount_minor, refund.settlement_plan_json,
                [(x["sequence_no"], x["entry_hash"]) for x in evidence])


def no_money(*args, **kwargs):
    pytest.fail("Completed-refund replay must not execute money again")


@pytest.mark.parametrize("order_status", [
    "CONFIRMED", "REFUND_PENDING", "IN_PROGRESS", "UNKNOWN_EXTERNAL_STATE",
])
def test_completed_rental_refund_rejects_nonrefunded_order(monkeypatch, order_status):
    order_id, refund_id, accepted_hash = seed_refund(order_status)
    before = snapshot(order_id, refund_id)
    monkeypatch.setattr(money, "execute_refund_plan", no_money)

    with pytest.raises(ValueError, match="^RENTAL_REFUND_RECONCILIATION_REQUIRED$"):
        rental_service.cancel(OWNER, order_id, accepted_hash)

    assert snapshot(order_id, refund_id) == before


def test_completed_rental_refund_without_money_evidence_is_rejected(monkeypatch):
    order_id, refund_id, accepted_hash = seed_refund("REFUNDED")
    before = snapshot(order_id, refund_id)
    monkeypatch.setattr(money, "execute_refund_plan", no_money)

    with pytest.raises(ValueError, match='^REFUND_COMPLETION_EVIDENCE_INVALID$'):
        rental_service.cancel(OWNER, order_id, accepted_hash)
    assert snapshot(order_id, refund_id) == before


@pytest.mark.parametrize("final_order_status", ["CONFIRMED", "REFUNDED"])
def test_rental_refund_rechecks_concurrent_completion_terminal_pair(monkeypatch, final_order_status):
    order_id, refund_id, accepted_hash = seed_refund("REFUND_PENDING", "REFUND_PENDING")
    calls = []
    after_concurrent = []

    def concurrent_completion(plan, evidence):
        calls.append((plan, evidence))
        with SessionLocal.begin() as s:
            s.get(MobilityRefundRow, refund_id).status = "REFUND_COMPLETED"
            s.get(MobilityRentalOrderRow, order_id).status = final_order_status
        after_concurrent.append(snapshot(order_id, refund_id))
        return {"state": "CONFIRMED", "money_movement_ids": []}

    monkeypatch.setattr(money, "execute_refund_plan", concurrent_completion)
    if final_order_status == "REFUNDED":
        with pytest.raises(ValueError, match='^REFUND_COMPLETION_EVIDENCE_INVALID$'):
            rental_service.cancel(OWNER, order_id, accepted_hash)
    else:
        with pytest.raises(ValueError, match="^RENTAL_REFUND_RECONCILIATION_REQUIRED$"):
            rental_service.cancel(OWNER, order_id, accepted_hash)

    assert len(calls) == 1
    assert snapshot(order_id, refund_id) == after_concurrent[0]


def test_rental_refund_terminal_guard_preserves_owner_check(monkeypatch):
    order_id, refund_id, accepted_hash = seed_refund("REFUNDED")
    before = snapshot(order_id, refund_id)
    monkeypatch.setattr(money, "execute_refund_plan", no_money)

    with pytest.raises(ValueError, match="^MOBILITY_ORDER_NOT_FOUND$"):
        rental_service.cancel("c04-other-owner", order_id, accepted_hash)

    assert snapshot(order_id, refund_id) == before
