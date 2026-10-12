"""Independent HTTP acceptance for C10's owner-only advice boundary.

Uses pre-existing mainline API helpers, not the candidate's service-test fixtures.
No authorization monkeypatching; every request carries a real consumer session.
"""
from datetime import datetime, timezone
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    ConsumerTripMemberRow, GoJourneyRow, GoJourneyItemRow,
    JourneyDisruptionSignalRow, JourneyImpactRow, JourneyAdviceRow,
    FlightOrderRow, RailOrderRow, MobilityRideOrderRow, OrderRow,
)
from tests.test_sprint3f_journey_intelligence import auth, seed, make_journey

TABLES = (
    GoJourneyRow, GoJourneyItemRow, JourneyDisruptionSignalRow,
    JourneyImpactRow, JourneyAdviceRow, FlightOrderRow, RailOrderRow,
    MobilityRideOrderRow, OrderRow, ConsumerTripMemberRow,
)

def snapshot():
    with SessionLocal() as session:
        return {
            model.__tablename__: sorted(
                [dict(row) for row in session.execute(model.__table__.select()).mappings()],
                key=repr,
            )
            for model in TABLES
        }

@pytest.mark.parametrize("viewer_role", ["MEMBER", "OUTSIDER"])
@pytest.mark.parametrize("operation", ["latest", "evaluate", "acknowledge"])
def test_non_owner_http_refused_without_disclosure_or_mutation(client, viewer_role, operation):
    owner_headers, owner_id = auth(client, "independent-owner@example.com")
    viewer_headers, viewer_id = auth(client, "independent-viewer@example.com")
    seed(owner_id)
    journey = make_journey(client, owner_headers)
    journey_id = journey["journey_id"]
    if viewer_role == "MEMBER":
        with SessionLocal() as session:
            session.add(ConsumerTripMemberRow(
                trip_member_id="independent-active-member",
                journey_id=journey_id, user_id=viewer_id,
                role="MEMBER", status="ACTIVE",
                joined_at=datetime.now(timezone.utc),
            ))
            session.commit()
    payload = {
        "source_item_id": journey["timeline"][0]["item_id"],
        "event_type": "FLIGHT_DELAY",
        "facts": {"estimated_arrival_at": "2026-09-01T15:05:00+09:00", "delay_minutes": 95},
    }
    root = f"/v1/trips/journeys/{journey_id}"
    accepted = client.post(root + "/disruptions/evaluate", headers=owner_headers, json=payload)
    assert accepted.status_code == 200, accepted.text
    advice_id = accepted.json()["data"]["advice"]["advice_id"]
    before = snapshot()
    if operation == "latest":
        denied = client.get(root + "/disruptions/latest", headers=viewer_headers)
    elif operation == "evaluate":
        denied = client.post(root + "/disruptions/evaluate", headers=viewer_headers, json=payload)
    else:
        denied = client.post(root + f"/advice/{advice_id}/acknowledge", headers=viewer_headers)
    assert denied.status_code == 404, denied.text
    assert "JOURNEY_NOT_FOUND" in denied.text
    for private_value in (advice_id, journey_id, "f_dis", "r_dis", "h_dis", "t_dis"):
        assert private_value not in denied.text
    assert snapshot() == before
    visible = client.get(root + "/disruptions/latest", headers=owner_headers)
    assert visible.status_code == 200, visible.text
    assert visible.json()["data"]["advice"]["advice_id"] == advice_id
    assert visible.json()["data"]["advice"]["status"] == "OPEN"
    acknowledged = client.post(root + f"/advice/{advice_id}/acknowledge", headers=owner_headers)
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["data"]["status"] == "ACKNOWLEDGED"
