from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from go_hotel.db.models import GoodHotelStandardGovernanceEventRow, GoodHotelStandardVersionRow
from go_hotel.db.session import SessionLocal
from go_hotel.judgment import good_hotel_standard as module


def payload(tag):
    return {
        "dimensions": ["CLEANLINESS", "SAFETY", "FULFILLMENT_TRUTH"],
        "thresholds": {"recommended_score_milli": 4200 + tag},
        "disqualifiers": ["UNRESOLVED_CONFIRMED_SERIOUS_RISK"],
        "evidence_requirements": {"required": [f"GO_TRUTH_{tag}"]},
    }


def install_clock(monkeypatch, start):
    ticks = [start + timedelta(minutes=index) for index in range(16)]
    cursor = iter(ticks)
    last = ticks[-1]

    def fake_now():
        nonlocal last
        try:
            last = next(cursor)
        except StopIteration:
            pass
        return last

    monkeypatch.setattr(module, "now", fake_now)
    return ticks


def parsed(value):
    stamp = datetime.fromisoformat(value)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def versions():
    with SessionLocal() as session:
        return list(session.scalars(select(GoodHotelStandardVersionRow).order_by(GoodHotelStandardVersionRow.version_no)))


def events():
    with SessionLocal() as session:
        return list(session.scalars(select(GoodHotelStandardGovernanceEventRow)))


def test_draft_independent_checker_activates_and_retains_maker_checker(monkeypatch):
    ticks = install_clock(monkeypatch, datetime(2026, 1, 1, tzinfo=timezone.utc))
    draft = module.good_hotel_standard_service.create(payload(1), "maker-a")
    approved = module.good_hotel_standard_service.approve(draft["good_hotel_standard_version_id"], "checker-a")

    assert approved["state"] == "ACTIVE"
    assert approved["approved_by"] == "checker-a"
    assert parsed(approved["effective_at"]) == ticks[2]

    current = versions()
    assert [row.state for row in current] == ["ACTIVE"]
    assert current[0].requested_by == "maker-a"

    with pytest.raises(ValueError, match="MAKER_CHECKER"):
        module.good_hotel_standard_service.approve(draft["good_hotel_standard_version_id"], "maker-a")


def test_active_approval_replay_is_idempotent_and_keeps_effective_at(monkeypatch):
    ticks = install_clock(monkeypatch, datetime(2026, 2, 1, tzinfo=timezone.utc))
    draft = module.good_hotel_standard_service.create(payload(2), "maker-b")
    approved = module.good_hotel_standard_service.approve(draft["good_hotel_standard_version_id"], "checker-b")
    before_events = Counter(event.event_type for event in events())

    replay = module.good_hotel_standard_service.approve(draft["good_hotel_standard_version_id"], "checker-b")

    assert replay["good_hotel_standard_version_id"] == approved["good_hotel_standard_version_id"]
    assert parsed(replay["effective_at"]) == parsed(approved["effective_at"]) == ticks[2]
    assert Counter(event.event_type for event in events()) == before_events

    current = versions()
    assert [row.state for row in current] == ["ACTIVE"]
    assert current[0].retired_at is None


def test_superseded_version_cannot_be_reactivated(monkeypatch):
    install_clock(monkeypatch, datetime(2026, 3, 1, tzinfo=timezone.utc))
    first = module.good_hotel_standard_service.create(payload(3), "maker-c")
    first_active = module.good_hotel_standard_service.approve(first["good_hotel_standard_version_id"], "checker-c")
    second = module.good_hotel_standard_service.create(payload(4), "maker-d")
    second_active = module.good_hotel_standard_service.approve(second["good_hotel_standard_version_id"], "checker-d")
    before_events = Counter(event.event_type for event in events())

    with pytest.raises(ValueError, match="SUPERSEDED_VERSION_REACTIVATION_FORBIDDEN"):
        module.good_hotel_standard_service.approve(first["good_hotel_standard_version_id"], "checker-c")

    assert Counter(event.event_type for event in events()) == before_events
    current = versions()
    assert [row.state for row in current] == ["SUPERSEDED", "ACTIVE"]
    assert current[0].effective_at == parsed(first_active["effective_at"]).replace(tzinfo=None)
    assert current[1].effective_at == parsed(second_active["effective_at"]).replace(tzinfo=None)
