from sqlalchemy import func, select
import pytest

from go_hotel.db.models import MobilityRideOrderRow, OrderSupplierFulfillmentEventRow, OrderSupplierFulfillmentRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service
from tests.test_sprint3c_mobility import auth as mobility_auth
from tests.vertical_transaction_helpers import pay_and_confirm


def _ride_offer(client):
    response = client.post(
        "/v1/mobility/rides/search",
        json={
            "pickup": "PVG",
            "dropoff": "Shanghai Bund",
            "pickup_at": "2026-09-01T10:00:00",
            "currency": "CNY",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["items"][0]


def _ride_body(offer_id: str) -> dict:
    return {
        "offer_id": offer_id,
        "pickup": "PVG",
        "dropoff": "Shanghai Bund",
        "pickup_at": "2026-09-01T10:00:00",
        "currency": "CNY",
        "flight_no": "MU510",
    }


def test_ride_create_order_replays_same_idempotency_key_without_second_order(client):
    headers = mobility_auth(client)
    body = _ride_body(_ride_offer(client)["offer_id"])
    first = client.post(
        "/v1/mobility/rides/orders",
        headers=headers | {"Idempotency-Key": "ride-create-same"},
        json=body,
    )
    second = client.post(
        "/v1/mobility/rides/orders",
        headers=headers | {"Idempotency-Key": "ride-create-same"},
        json=body,
    )
    conflict = client.post(
        "/v1/mobility/rides/orders",
        headers=headers | {"Idempotency-Key": "ride-create-same"},
        json=body | {"dropoff": "Pudong Airport T2"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert conflict.status_code == 409

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(MobilityRideOrderRow)) == 1


def test_refunded_ride_rejects_late_supplier_callback_without_state_change(client):
    headers = mobility_auth(client)
    ride = client.post("/v1/mobility/rides/orders", headers=headers, json=_ride_body(_ride_offer(client)["offer_id"]))
    assert ride.status_code == 200
    order_id = ride.json()["data"]["order_id"]
    pay_and_confirm(client, headers, "RIDE_ORDER", order_id, "RIDE-" + order_id[-6:])

    quote = client.get(f"/v1/mobility/orders/{order_id}/refund-quote", headers=headers)
    assert quote.status_code == 200
    refunded = client.post(
        f"/v1/mobility/orders/{order_id}/refund-confirmed",
        headers=headers | {"Idempotency-Key": "ride-refund-confirmed"},
        json={"quote_hash": quote.json()["data"]["quote_hash"], "confirmed": True},
    )
    assert refunded.status_code == 200
    assert refunded.json()["data"]["status"] == "REFUND_COMPLETED"

    before = client.get(f"/v1/mobility/orders/{order_id}", headers=headers).json()["data"]
    assert before["status"] == "REFUNDED"

    with SessionLocal() as session:
        fulfillment = session.scalar(
            select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.business_id == order_id)
        )
        assert fulfillment is not None
        before_events = session.scalar(
            select(func.count()).select_from(OrderSupplierFulfillmentEventRow).where(
                OrderSupplierFulfillmentEventRow.order_supplier_fulfillment_id == fulfillment.order_supplier_fulfillment_id
            )
        )
        confirmation = fulfillment.supplier_confirmation_reference

    with pytest.raises(ValueError, match="TERMINAL_ORDER_SUPPLIER_FACT_REJECTED"):
        order_supplier_fulfillment_service.record_supplier_fact(
            fulfillment.order_supplier_fulfillment_id,
            {
                "state": "SUPPLIER_CONFIRMED",
                "supplier_confirmation_reference": confirmation,
                "evidence_reference": "supplier://late-callback/" + order_id,
            },
        )

    after = client.get(f"/v1/mobility/orders/{order_id}", headers=headers).json()["data"]
    assert after == before
    with SessionLocal() as session:
        after_events = session.scalar(
            select(func.count()).select_from(OrderSupplierFulfillmentEventRow).where(
                OrderSupplierFulfillmentEventRow.order_supplier_fulfillment_id == fulfillment.order_supplier_fulfillment_id
            )
        )
    assert after_events == before_events
