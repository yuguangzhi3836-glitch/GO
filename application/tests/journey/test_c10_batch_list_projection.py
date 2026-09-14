"""Actual SQL counts for owner/member Journey list on isolated SQLite."""
from datetime import timedelta

import pytest
from sqlalchemy import event, select

from go_hotel.db.models import ConsumerTripMemberRow, GoJourneyItemRow, GoJourneyRow
from go_hotel.journey import service as journey_module
from test_c10_current_status_projection import isolated_session, _seed, OWNER, MEMBER, OUTSIDER, STAMP, JOURNEY_ID, ORDER_ID

pytestmark = pytest.mark.no_db


def grow(factory, vertical, count):
    model = journey_module.VERTICALS[vertical][0]
    with factory.begin() as session:
        original = session.get(model, ORDER_ID)
        fields = {column.name: getattr(original, column.name) for column in model.__table__.columns}
        for index in range(1, count):
            jid, oid = f"c10_batch_j{index:04}", f"c10_batch_o{index:04}"
            order_fields = {**fields, "order_id": oid, "account_id": OWNER, "status": "CANCELLED"}
            if "prebook_id" in order_fields:
                order_fields["prebook_id"] = f"c10_batch_p{index:04}"
            session.add(GoJourneyRow(journey_id=jid, account_id=OWNER, title=jid, status="UPCOMING", created_at=STAMP + timedelta(seconds=index), updated_at=STAMP))
            session.add(ConsumerTripMemberRow(trip_member_id=f"c10_batch_m{index}", journey_id=jid, user_id=MEMBER, role="MEMBER", status="ACTIVE", joined_at=STAMP))
            for item_index in range(2):
                item_oid = f"{oid}_{item_index}"
                item_fields = {**order_fields, "order_id": item_oid}
                if "prebook_id" in item_fields:
                    item_fields["prebook_id"] += f"_{item_index}"
                session.add(model(**item_fields))
                session.add(GoJourneyItemRow(item_id=f"{jid}_i{item_index}", journey_id=jid, account_id=OWNER, vertical=vertical, order_id=item_oid, title="Batch item", status_snapshot="CONFIRMED", facts_json={"historical": True}, detail_route="OrderDetail", sort_key=str(2-item_index), created_at=STAMP + timedelta(seconds=item_index)))


def counted_list(factory, viewer):
    statements = []
    engine = factory.kw["bind"]
    def count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(engine, "before_cursor_execute", count)
    try:
        output = journey_module.journey_service.list(viewer)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return output, statements


@pytest.mark.parametrize("vertical", sorted(journey_module.VERTICALS))
@pytest.mark.parametrize("viewer", [OWNER, MEMBER])
def test_list_queries_bounded_by_vertical_not_order_count(isolated_session, vertical, viewer):
    _seed(isolated_session, vertical)
    initial, small = counted_list(isolated_session, viewer)
    grow(isolated_session, vertical, 31)
    listed, large = counted_list(isolated_session, viewer)
    print(f"C10_SQL_COUNT vertical={vertical} viewer={viewer} journeys=1:{len(small)} journeys=31:{len(large)} items=61")
    assert len(large) == len(small), "Journey/vertical order N+1 query growth"
    assert len(large) <= 5
    assert len(listed) == 31
    assert listed[0] == initial[0]
    assert [row["journey_id"] for row in listed[1:]] == [f"c10_batch_j{i:04}" for i in range(1,31)]
    for row in listed[1:]:
        assert [item["item_id"] for item in row["timeline"]] == [row["journey_id"] + "_i1", row["journey_id"] + "_i0"]
        assert all(item["status"] == "CANCELLED" and item["facts"] == {"historical": True} for item in row["timeline"])
    with isolated_session() as session:
        assert all(row.status_snapshot == "CONFIRMED" for row in session.scalars(select(GoJourneyItemRow)))


def test_batch_projection_keeps_owner_boundary_missing_and_unsupported_fallback(isolated_session):
    model = _seed(isolated_session, "HOTEL")
    grow(isolated_session, "HOTEL", 5)
    with isolated_session.begin() as session:
        for item_index in range(2):
            session.get(model, f"c10_batch_o0001_{item_index}").account_id = OUTSIDER
            session.get(model, f"c10_batch_o0001_{item_index}").status = "PRIVATE_OTHER_ACCOUNT_STATE"
            session.delete(session.get(model, f"c10_batch_o0002_{item_index}"))
        session.get(GoJourneyItemRow, "c10_batch_j0003_i0").vertical = "EXTERNAL"
        session.scalar(select(ConsumerTripMemberRow).where(ConsumerTripMemberRow.journey_id == "c10_batch_j0004")).status = "REVOKED"
    listed, statements = counted_list(isolated_session, MEMBER)
    assert len(listed) == 4
    by_id = {row["journey_id"]: row for row in listed}
    for index in (1,2):
        assert all(item["status"] == "CONFIRMED" for item in by_id[f"c10_batch_j{index:04}"]["timeline"])
    assert by_id["c10_batch_j0003"]["timeline"][1]["status"] == "CONFIRMED"
    assert journey_module.journey_service.list(OUTSIDER) == []


def test_order_batch_chunk_boundary_does_not_fall_back_to_n_plus_one(isolated_session):
    _seed(isolated_session, "HOTEL")
    grow(isolated_session, "HOTEL", 405)
    listed, statements = counted_list(isolated_session, OWNER)
    print(f"C10_SQL_COUNT chunk_boundary journeys=405 items=809 SELECTs={len(statements)}")
    assert len(listed) == 405
    # Two access queries, two 400-journey item batches and three 400-key
    # order batches: chunk growth, rather than one query per item/journey.
    assert len(statements) == 2 + 2 + 3
