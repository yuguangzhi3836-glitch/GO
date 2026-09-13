"""C10 current-status projections on an isolated nine-table SQLite database.

These tests exercise list/get and ownership checks, not booking/refund execution
or live provider acceptance. Historical attachment snapshots remain unchanged.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import (
    Base,
    ConsumerTripMemberRow,
    GoJourneyItemRow,
    GoJourneyRow,
)
from go_hotel.journey import service as journey_module


pytestmark = pytest.mark.no_db
OWNER = "c10_owner"
MEMBER = "c10_member"
OUTSIDER = "c10_outsider"
JOURNEY_ID = "c10_journey"
ORDER_ID = "c10_order"
ITEM_ID = "c10_item"
STAMP = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


@pytest.fixture
def isolated_session(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [
        GoJourneyRow.__table__,
        GoJourneyItemRow.__table__,
        ConsumerTripMemberRow.__table__,
        *(model.__table__ for model, _ in journey_module.VERTICALS.values()),
    ]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(journey_module, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed(factory, vertical, *, order_owner=OWNER):
    model, route = journey_module.VERTICALS[vertical]
    fields = {
        "order_id": ORDER_ID,
        "account_id": order_owner,
        "status": "CONFIRMED",
        "total_amount_minor": 50000,
        "currency": "CNY",
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    if vertical in {"HOTEL", "FLIGHT", "RAIL"}:
        fields["prebook_id"] = "c10_prebook"
    if vertical == "HOTEL":
        fields["hotel_id"] = "c10_hotel"
    elif vertical == "RIDE":
        fields.update(
            pickup="Airport", dropoff="Hotel", pickup_at="2026-10-01T12:00:00Z",
            vehicle_class="STANDARD", passengers=[],
        )
    elif vertical == "RENTAL":
        fields.update(
            pickup_location="Airport", return_location="Airport",
            pickup_at="2026-10-01T12:00:00Z", return_at="2026-10-02T12:00:00Z",
            vehicle_class="STANDARD", insurance={}, mileage={},
            deposit_minor=10000, drivers=[],
        )
    elif vertical == "ATTRACTION":
        fields.update(
            product_id="c10_attraction", product_name="Museum",
            product_type="TICKET", destination="City", visit_date="2026-10-01",
            ticket_type="ADULT", quantity=1, eligibility={},
            voucher_type="QR", attendees=[],
        )
    with factory.begin() as session:
        session.add(model(**fields))
        session.add(GoJourneyRow(
            journey_id=JOURNEY_ID, account_id=OWNER, title="C10 projection check",
            status="UPCOMING", created_at=STAMP, updated_at=STAMP,
        ))
        session.add(GoJourneyItemRow(
            item_id=ITEM_ID, journey_id=JOURNEY_ID, account_id=OWNER,
            vertical=vertical, order_id=ORDER_ID, title="Existing booked item",
            status_snapshot="CONFIRMED", facts_json={"source": "attachment"},
            detail_route=route, sort_key="2026-10-01", created_at=STAMP,
        ))
        session.add(ConsumerTripMemberRow(
            trip_member_id="c10_membership", journey_id=JOURNEY_ID,
            user_id=MEMBER, role="MEMBER", status="ACTIVE", joined_at=STAMP,
        ))
    return model


@pytest.mark.parametrize("vertical", sorted(journey_module.VERTICALS))
@pytest.mark.parametrize("viewer", [OWNER, MEMBER])
def test_list_reflects_same_canonical_status_as_detail_without_mutation(
    isolated_session, vertical, viewer,
):
    model = _seed(isolated_session, vertical)
    service = journey_module.journey_service
    assert service.list(viewer)[0]["timeline"][0]["status"] == "CONFIRMED"

    # Simulate a separately committed vertical state update, not a C10 write.
    with isolated_session.begin() as session:
        session.get(model, ORDER_ID).status = "CANCELLED"

    detail = service.get(viewer, JOURNEY_ID)
    listed = service.list(viewer)
    assert detail["timeline"][0]["status"] == "CANCELLED"
    assert listed[0]["timeline"][0]["status"] == detail["timeline"][0]["status"]
    assert listed[0]["timeline"][0]["facts"] == {"source": "attachment"}
    with isolated_session() as session:
        assert session.get(model, ORDER_ID).status == "CANCELLED"
        assert session.get(GoJourneyItemRow, ITEM_ID).status_snapshot == "CONFIRMED"
        assert session.get(GoJourneyRow, JOURNEY_ID).status == "UPCOMING"


def test_list_does_not_grant_access_to_nonmember_or_revoked_member(isolated_session):
    _seed(isolated_session, "HOTEL")
    service = journey_module.journey_service
    assert service.list(OUTSIDER) == []
    with pytest.raises(ValueError, match="^JOURNEY_NOT_FOUND$"):
        service.get(OUTSIDER, JOURNEY_ID)

    with isolated_session.begin() as session:
        membership = session.scalar(select(ConsumerTripMemberRow))
        membership.status = "REVOKED"
    assert service.list(MEMBER) == []
    with pytest.raises(ValueError, match="^JOURNEY_NOT_FOUND$"):
        service.get(MEMBER, JOURNEY_ID)


def test_refresh_does_not_expose_another_accounts_order_status(isolated_session):
    model = _seed(isolated_session, "HOTEL", order_owner=OUTSIDER)
    with isolated_session.begin() as session:
        session.get(model, ORDER_ID).status = "PRIVATE_OTHER_ACCOUNT_STATE"
    service = journey_module.journey_service
    for viewer in [OWNER, MEMBER]:
        # Preserve the existing get() missing/not-owned-order fallback.
        assert service.get(viewer, JOURNEY_ID)["timeline"][0]["status"] == "CONFIRMED"
        assert service.list(viewer)[0]["timeline"][0]["status"] == "CONFIRMED"


def test_list_preserves_existing_missing_order_fallback(isolated_session):
    model = _seed(isolated_session, "HOTEL")
    with isolated_session.begin() as session:
        session.delete(session.get(model, ORDER_ID))
    service = journey_module.journey_service
    assert service.list(OWNER)[0]["timeline"][0]["status"] == "CONFIRMED"
    assert service.get(OWNER, JOURNEY_ID)["timeline"][0]["status"] == "CONFIRMED"
