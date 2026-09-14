"""Measure existing N+1 behavior, not a load/performance acceptance claim."""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from go_hotel.db.models import Base, GoJourneyRow, GoJourneyItemRow, ConsumerTripMemberRow, OrderRow
from go_hotel.journey import service as journey_module

@pytest.mark.parametrize("journey_count,items_per_journey", [(1,1),(1,25),(25,1)])
def test_quantify_current_select_growth(monkeypatch, journey_count, items_per_journey):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[GoJourneyRow.__table__,GoJourneyItemRow.__table__,ConsumerTripMemberRow.__table__,OrderRow.__table__])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(journey_module,"SessionLocal",sessions)
    stamp=datetime(2026,9,14,tzinfo=timezone.utc)
    with sessions.begin() as session:
        for j in range(journey_count):
            session.add(GoJourneyRow(journey_id=f"j{j}", account_id="owner", title="trip",status="UPCOMING",created_at=stamp,updated_at=stamp))
            for i in range(items_per_journey):
                order_id=f"o{j}_{i}"
                session.add(OrderRow(order_id=order_id,account_id="owner",prebook_id="prebook",hotel_id="hotel",status="CONFIRMED",total_amount_minor=50000,currency="CNY",created_at=stamp,updated_at=stamp))
                session.add(GoJourneyItemRow(item_id=f"i{j}_{i}",journey_id=f"j{j}",account_id="owner",vertical="HOTEL",order_id=order_id,title="stay",status_snapshot="CONFIRMED",facts_json={},detail_route="OrderDetail",sort_key=str(i),created_at=stamp))
    selects=[]
    def record(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)
    event.listen(engine,"before_cursor_execute",record)
    try:
        result=journey_module.journey_service.list("owner")
        assert len(result)==journey_count
        assert sum(row["item_count"] for row in result)==journey_count*items_per_journey
        print({"journeys":journey_count,"items":journey_count*items_per_journey,"select_count":len(selects),"acceptance":"MEASUREMENT_ONLY"})
    finally:
        event.remove(engine,"before_cursor_execute",record)
        engine.dispose()
