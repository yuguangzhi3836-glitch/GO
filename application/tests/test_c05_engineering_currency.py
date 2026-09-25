"""Fixed CNY engineering fares must never be relabelled as another currency."""
import pytest
from sqlalchemy import func, select

from go_hotel.db.models import MobilityRideOrderRow
from go_hotel.db.session import SessionLocal
from go_hotel.mobility.ride.service import ride_service


def booking_body(offer="ride_standard"):
    return {"offer_id": offer, "pickup": "PVG", "dropoff": "Bund",
            "pickup_at": "2026-10-10T10:00:00+08:00",
            "passengers": [{"full_name": "ISOLATED ADULT"}]}


@pytest.mark.parametrize("currency", ["USD", "JPY", "cny", "", None, "CNY "])
def test_unsupported_currency_rejected_before_ride_order_or_source_decision(currency, monkeypatch):
    calls = []
    from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service
    monkeypatch.setattr(vertical_source_runtime_service, "decide", lambda *a, **kw: calls.append(a))
    with pytest.raises(ValueError, match="^RIDE_ENGINEERING_CURRENCY_INVALID$"):
        ride_service.search("PVG", "Bund", "2026-10-10T10:00:00+08:00", currency)
    with pytest.raises(ValueError, match="^RIDE_ENGINEERING_CURRENCY_INVALID$"):
        ride_service.create("currency-owner", booking_body() | {"currency": currency})
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(MobilityRideOrderRow)) == 0
    assert calls == []


@pytest.mark.parametrize("offer,amount", [("ride_standard", 16800), ("ride_premium", 26800)])
@pytest.mark.parametrize("explicit_currency", [False, True])
def test_supported_or_default_currency_keeps_same_fare_from_search_to_order(offer, amount, explicit_currency):
    body = booking_body(offer)
    if explicit_currency:
        body["currency"] = "CNY"
    offers = ride_service.search(body["pickup"], body["dropoff"], body["pickup_at"])
    selected = next(item for item in offers if item["offer_id"] == offer)
    order = ride_service.create("currency-owner", body)
    assert (selected["total_amount_minor"], selected["currency"]) == (amount, "CNY")
    assert (order["total_amount_minor"], order["currency"]) == (amount, "CNY")
    assert order["status"] == "PAYMENT_PENDING"
    assert ride_service.get("currency-owner", order["order_id"])["currency"] == "CNY"


@pytest.mark.parametrize("currency", ["USD", "JPY"])
def test_ride_search_api_rejects_currency_instead_of_publishing_mislabeled_fare(client, currency):
    body = booking_body() | {"currency": currency}
    response = client.post("/v1/mobility/rides/search", json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == "RIDE_ENGINEERING_CURRENCY_INVALID"
