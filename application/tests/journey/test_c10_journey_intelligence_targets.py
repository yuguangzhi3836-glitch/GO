"""C10 advisory targets stay bound to one concrete journey item/order."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import (
    Base,
    ConsumerTripMemberRow,
    GoJourneyItemRow,
    GoJourneyRow,
    JourneyAdviceRow,
    JourneyDisruptionSignalRow,
    JourneyImpactRow,
)
from go_hotel.journey import intelligence as intelligence_module


pytestmark = pytest.mark.no_db
OWNER = "c10_intel_owner"
MEMBER = "c10_intel_member"
OUTSIDER = "c10_intel_outsider"
JOURNEY_ID = "c10_intel_journey"
STAMP = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)


@pytest.fixture
def isolated_session(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [
        GoJourneyRow.__table__,
        GoJourneyItemRow.__table__,
        JourneyDisruptionSignalRow.__table__,
        JourneyImpactRow.__table__,
        JourneyAdviceRow.__table__,
        ConsumerTripMemberRow.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(intelligence_module, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed(factory):
    with factory.begin() as session:
        session.add(GoJourneyRow(
            journey_id=JOURNEY_ID, account_id=OWNER, title="C10 disruption target check",
            status="UPCOMING", created_at=STAMP, updated_at=STAMP,
        ))
        session.add_all([
            GoJourneyItemRow(
                item_id="flight_source", journey_id=JOURNEY_ID, account_id=OWNER,
                vertical="FLIGHT", order_id="flight_order", title="Inbound flight",
                starts_at="2026-10-02T08:00:00+08:00", ends_at="2026-10-02T13:00:00+09:00",
                status_snapshot="CONFIRMED", facts_json={"flight_number": "MU523"},
                detail_route="FlightTripDetail", sort_key="2026-10-02T08:00:00+08:00", created_at=STAMP,
            ),
            GoJourneyItemRow(
                item_id="ride_one", journey_id=JOURNEY_ID, account_id=OWNER,
                vertical="RIDE", order_id="ride_order_1", title="Airport pickup A",
                starts_at="2026-10-02T14:10:00+09:00", ends_at=None,
                status_snapshot="CONFIRMED", facts_json={"flight_no": "MU523"},
                detail_route="MobilityTripDetail", sort_key="2026-10-02T14:10:00+09:00", created_at=STAMP,
            ),
            GoJourneyItemRow(
                item_id="ride_two", journey_id=JOURNEY_ID, account_id=OWNER,
                vertical="RIDE", order_id="ride_order_2", title="Airport pickup B",
                starts_at="2026-10-02T14:40:00+09:00", ends_at=None,
                status_snapshot="CONFIRMED", facts_json={"flight_no": "MU523"},
                detail_route="MobilityTripDetail", sort_key="2026-10-02T14:40:00+09:00", created_at=STAMP,
            ),
        ])
        session.add(ConsumerTripMemberRow(
            trip_member_id="c10_intel_member_row", journey_id=JOURNEY_ID,
            user_id=MEMBER, role="MEMBER", status="ACTIVE", joined_at=STAMP,
        ))


def test_same_vertical_advice_actions_bind_concrete_items_and_orders(isolated_session):
    _seed(isolated_session)

    result = intelligence_module.journey_intelligence_service.evaluate(OWNER, JOURNEY_ID, {
        "source_item_id": "flight_source",
        "event_type": "FLIGHT_DELAY",
        "severity": "HIGH",
        "facts": {
            "original_arrival_at": "2026-10-02T13:00:00+09:00",
            "estimated_arrival_at": "2026-10-02T15:05:00+09:00",
            "delay_minutes": 125,
        },
    })

    ride_impacts = sorted(
        [impact for impact in result["impacts"] if impact["vertical"] == "RIDE"],
        key=lambda impact: impact["order_id"],
    )
    assert [impact["order_id"] for impact in ride_impacts] == ["ride_order_1", "ride_order_2"]
    assert [impact["affected_item_id"] for impact in ride_impacts] == ["ride_one", "ride_two"]
    assert all(impact["recommended_action"]["execution_route"] == "MobilityTripDetail" for impact in ride_impacts)
    assert [impact["recommended_action"]["target"] for impact in ride_impacts] == [
        {
            "entity_type": "JOURNEY_ITEM_ORDER",
            "item_id": "ride_one",
            "vertical": "RIDE",
            "order_id": "ride_order_1",
        },
        {
            "entity_type": "JOURNEY_ITEM_ORDER",
            "item_id": "ride_two",
            "vertical": "RIDE",
            "order_id": "ride_order_2",
        },
    ]
    assert result["advice"]["actions"] == [impact["recommended_action"] for impact in result["impacts"]]
    assert result["auto_mutation_performed"] is False


def test_owner_only_access_keeps_advice_targets_private(isolated_session):
    _seed(isolated_session)
    owner_result = intelligence_module.journey_intelligence_service.evaluate(OWNER, JOURNEY_ID, {
        "source_item_id": "flight_source",
        "event_type": "FLIGHT_DELAY",
        "facts": {"estimated_arrival_at": "2026-10-02T15:05:00+09:00", "delay_minutes": 95},
    })

    for viewer in [MEMBER, OUTSIDER]:
        with pytest.raises(ValueError, match="^JOURNEY_NOT_FOUND$"):
            intelligence_module.journey_intelligence_service.latest(viewer, JOURNEY_ID)
        with pytest.raises(ValueError, match="^JOURNEY_NOT_FOUND$"):
            intelligence_module.journey_intelligence_service.evaluate(viewer, JOURNEY_ID, {
                "source_item_id": "flight_source",
                "event_type": "FLIGHT_DELAY",
                "facts": {"estimated_arrival_at": "2026-10-02T15:05:00+09:00", "delay_minutes": 95},
            })
        with pytest.raises(ValueError, match="^JOURNEY_NOT_FOUND$"):
            intelligence_module.journey_intelligence_service.acknowledge(
                viewer, JOURNEY_ID, owner_result["advice"]["advice_id"],
            )

    latest = intelligence_module.journey_intelligence_service.latest(OWNER, JOURNEY_ID)
    assert latest["advice"]["advice_id"] == owner_result["advice"]["advice_id"]
    assert intelligence_module.journey_intelligence_service.acknowledge(
        OWNER, JOURNEY_ID, owner_result["advice"]["advice_id"],
    )["status"] == "ACKNOWLEDGED"
