import pytest
from sqlalchemy import select

from go_hotel.db.models import (
    OmnichannelMoneyMovementRow as Movement,
    PaymentOrderRootRow as Root,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.hotel_money_bridge import hotel_money_bridge
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from tests.test_sprint1n_supplier_compensation import booked_order


def captured_root(order_id: str) -> tuple[str, str, int]:
    intent_id = hotel_money_bridge.ensure_original_root(order_id)
    with SessionLocal() as s:
        capture = s.scalar(
            select(Movement).where(
                Movement.root_payment_intent_id == intent_id,
                Movement.movement_type == "CAPTURE",
                Movement.state == "CONFIRMED",
            )
        )
    assert capture is not None
    return intent_id, capture.money_movement_id, capture.amount_minor


def money_rows(order_id: str) -> list[Movement]:
    with SessionLocal() as s:
        root = s.scalar(
            select(Root).where(
                Root.business_type == "HOTEL_ORDER",
                Root.business_id == order_id,
            )
        )
        assert root is not None
        return list(
            s.scalars(
                select(Movement)
                .where(Movement.root_payment_intent_id == root.payment_intent_id)
                .order_by(Movement.created_at, Movement.money_movement_id)
            )
        )


def movement_body(capture_id: str, amount_minor: int, evidence: str, kind: str) -> dict:
    return {
        "movement_type": kind,
        "parent_movement_id": capture_id,
        "amount_minor": amount_minor,
        "evidence": [evidence],
        "mode": "CONTRACT_SIMULATOR",
    }


def assert_same_movement(left: dict, right: dict) -> None:
    for field in (
        "money_movement_id",
        "root_payment_intent_id",
        "parent_movement_id",
        "movement_type",
        "amount_minor",
        "currency",
        "state",
        "idempotency_key",
    ):
        assert left[field] == right[field]


def test_refund_and_compensation_share_one_capture_budget(client):
    order_id, paid = booked_order(client, "c11-budget-a")
    intent_id, capture_id, captured = captured_root(order_id)
    assert captured == paid

    refund = money.create(
        intent_id,
        movement_body(capture_id, 10_000, "test://c11/refund-partial", "REFUND"),
        "c11-budget-a-refund",
        "c11-test",
    )
    compensation = money.create(
        intent_id,
        movement_body(capture_id, paid - 10_000, "test://c11/comp-full", "COMPENSATION"),
        "c11-budget-a-comp",
        "c11-test",
    )

    replay = money.create(
        intent_id,
        movement_body(capture_id, paid - 10_000, "test://c11/comp-full", "COMPENSATION"),
        "c11-budget-a-comp",
        "c11-test",
    )
    assert_same_movement(replay, compensation)

    before = [(row.movement_type, row.amount_minor) for row in money_rows(order_id)]
    with pytest.raises(ValueError, match="CUMULATIVE_REFUND_COMPENSATION_EXCEEDS_CAPTURE"):
        money.create(
            intent_id,
            movement_body(capture_id, 1, "test://c11/refund-over", "REFUND"),
            "c11-budget-a-over",
            "c11-test",
        )
    after = [(row.movement_type, row.amount_minor) for row in money_rows(order_id)]

    assert refund["state"] == compensation["state"] == "CONFIRMED"
    assert before == after
    assert sum(
        row.amount_minor
        for row in money_rows(order_id)
        if row.movement_type in {"REFUND", "COMPENSATION"}
    ) == paid


def test_over_budget_failure_does_not_block_exact_remaining_refund(client):
    order_id, paid = booked_order(client, "c11-budget-b")
    intent_id, capture_id, captured = captured_root(order_id)
    assert captured == paid

    compensation = money.create(
        intent_id,
        movement_body(capture_id, paid - 20_000, "test://c11/comp-partial", "COMPENSATION"),
        "c11-budget-b-comp",
        "c11-test",
    )
    before = [(row.movement_type, row.amount_minor) for row in money_rows(order_id)]

    with pytest.raises(ValueError, match="CUMULATIVE_REFUND_COMPENSATION_EXCEEDS_CAPTURE"):
        money.create(
            intent_id,
            movement_body(capture_id, 20_001, "test://c11/refund-too-much", "REFUND"),
            "c11-budget-b-over",
            "c11-test",
        )

    refund = money.create(
        intent_id,
        movement_body(capture_id, 20_000, "test://c11/refund-rest", "REFUND"),
        "c11-budget-b-refund",
        "c11-test",
    )

    replay = money.create(
        intent_id,
        movement_body(capture_id, 20_000, "test://c11/refund-rest", "REFUND"),
        "c11-budget-b-refund",
        "c11-test",
    )
    assert_same_movement(replay, refund)

    after = [(row.movement_type, row.amount_minor) for row in money_rows(order_id)]
    assert before != after
    assert compensation["state"] == refund["state"] == "CONFIRMED"
    assert sum(
        row.amount_minor
        for row in money_rows(order_id)
        if row.movement_type in {"REFUND", "COMPENSATION"}
    ) == paid
