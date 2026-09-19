"""User-import time cannot suppress genuine pre-existing provider evidence."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import Base, ConsumerUnifiedLifecycleRow, ConsumerUnifiedLifecycleEventRow
from go_hotel.services import consumer_unified_lifecycle as module

pytestmark = pytest.mark.no_db


@pytest.fixture
def service(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'c10-upgrade.sqlite'}")
    Base.metadata.create_all(engine, tables=[ConsumerUnifiedLifecycleRow.__table__, ConsumerUnifiedLifecycleEventRow.__table__])
    monkeypatch.setattr(module, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    fixed = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(module, "now", lambda: fixed)
    yield module.ConsumerUnifiedLifecycleService(), fixed
    engine.dispose()


def official(svc, at, **overrides):
    body = dict(provider="BOOKING", external_order_id="existing-order", vertical="HOTEL",
                title="Verified hotel booking", lifecycle_state="CONFIRMED", payment_state="PAID",
                refund_state="NOT_REQUESTED", source_event_id="official-event-1",
                evidence_reference="provider-adapter:evidence:1", source_updated_at=at.isoformat(),
                servicing_deep_link="booking://orders/existing-order", cancel_allowed=True)
    body.update(overrides)
    return svc.import_external_order("c10_owner", body, trusted_provider=True, adapter_id="booking-orders-v1")


def test_older_first_official_event_upgrades_manual_claim(service):
    svc, imported_at = service
    manual = svc.import_external_order("c10_owner", dict(provider="BOOKING", external_order_id="existing-order", vertical="HOTEL"))
    verified = official(svc, imported_at - timedelta(days=2))
    assert verified["consumer_unified_lifecycle_id"] == manual["consumer_unified_lifecycle_id"]
    assert verified["stale_ignored"] is False
    assert verified["lifecycle_state"] == "CONFIRMED"
    assert verified["payment_state"] == "PAID"
    assert verified["facts_json"]["source_verification"] == "OFFICIAL_PROVIDER"
    assert verified["source_updated_at"].startswith("2026-09-16T12:00:00")
    assert verified["cancel_allowed"] is True
    assert len(svc.detail("c10_owner", manual["consumer_unified_lifecycle_id"])["events"]) == 2

    stale = official(svc, imported_at - timedelta(days=3), source_event_id="older-provider-event", lifecycle_state="PENDING")
    assert stale["stale_ignored"] is True
    assert stale["lifecycle_state"] == "CONFIRMED"
    manual_replay = svc.import_external_order("c10_owner", dict(provider="BOOKING", external_order_id="existing-order", vertical="HOTEL"))
    assert manual_replay["facts_json"]["source_verification"] == "OFFICIAL_PROVIDER"


def test_equal_timestamp_official_event_also_upgrades_manual_claim(service):
    svc, imported_at = service
    svc.import_external_order("c10_owner", dict(provider="BOOKING", external_order_id="existing-order", vertical="HOTEL"))
    assert official(svc, imported_at)["facts_json"]["source_verification"] == "OFFICIAL_PROVIDER"


def test_concurrent_first_official_delivery_preserves_one_event(service):
    svc, source_at = service
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: official(svc, source_at), range(4)))
    assert len({result["consumer_unified_lifecycle_id"] for result in results}) == 1
    assert sum(not result["stale_ignored"] for result in results) == 1
    assert len(svc.detail("c10_owner", results[0]["consumer_unified_lifecycle_id"])["events"]) == 1


def test_projection_reloads_cached_state_before_terminal_transition_check(service):
    svc, source_at = service
    initial = official(svc, source_at - timedelta(minutes=2))
    with module.SessionLocal() as stale_session:
        cached = stale_session.get(ConsumerUnifiedLifecycleRow, initial["consumer_unified_lifecycle_id"])
        terminal = official(svc, source_at - timedelta(minutes=1), source_event_id="cancel-event", lifecycle_state="CANCELLED")
        assert cached.lifecycle_state == "CONFIRMED"  # Deliberately stale identity map.
        payload = dict(account_id="c10_owner", vertical="HOTEL", order_id=initial["order_id"],
                       title="Later provider observation", lifecycle_state="IN_PROGRESS", payment_state="PAID",
                       refund_state="NOT_REQUESTED", evidence_reference="provider-adapter:later-event",
                       source_updated_at=source_at.isoformat())
        with pytest.raises(ValueError, match="UNIFIED_LIFECYCLE_TERMINAL_STATE_IMMUTABLE"):
            svc.project_in_session(stale_session, payload)
    assert svc.detail("c10_owner", terminal["consumer_unified_lifecycle_id"])["item"]["lifecycle_state"] == "CANCELLED"
