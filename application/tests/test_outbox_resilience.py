from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import select, func, update
from go_hotel.core.config import settings
from go_hotel.db.models import OutboxRow, OutboxDeadLetterRow
from go_hotel.db.session import SessionLocal
from go_hotel.domain.models import now_utc
from go_hotel.services.outbox import OutboxWorker

class AlwaysFail:
    def publish(self, topic, event):
        raise RuntimeError("broker unavailable")

class Capture:
    def __init__(self): self.events=[]
    def publish(self, topic, event): self.events.append((topic,event))


def seed_event(client):
    search = client.post("/v1/search/hotels", json={"destination":{"city_code":"TYO"},"stay":{"check_in":"2026-09-01","check_out":"2026-09-05"},"currency":"CNY"})
    assert search.status_code == 200


def test_outbox_retry_then_publish(client):
    seed_event(client)
    old_max = settings.outbox_max_attempts; settings.outbox_max_attempts = 3
    try:
        first = OutboxWorker(AlwaysFail()).run_once()
        assert first["failed"] >= 1
        with SessionLocal.begin() as s:
            s.execute(update(OutboxRow).where(OutboxRow.status == "RETRY").values(available_at=now_utc()))
        sink = Capture(); second = OutboxWorker(sink).run_once()
        assert second["published"] >= 1
        assert len(sink.events) >= 1
    finally:
        settings.outbox_max_attempts = old_max


def test_outbox_dead_letters_after_max_attempts(client):
    seed_event(client)
    old_max = settings.outbox_max_attempts; settings.outbox_max_attempts = 1
    try:
        result = OutboxWorker(AlwaysFail()).run_once()
        assert result["failed"] >= 1
        with SessionLocal() as s:
            assert s.scalar(select(func.count()).select_from(OutboxRow).where(OutboxRow.status == "DEAD_LETTERED")) >= 1
            assert s.scalar(select(func.count()).select_from(OutboxDeadLetterRow)) >= 1
    finally:
        settings.outbox_max_attempts = old_max


def test_outbox_heartbeat_is_token_and_worker_fenced(client):
    seed_event(client)
    worker_a = OutboxWorker(Capture(), worker_id="outbox-a")
    claimed = worker_a.claim(limit=1)
    assert len(claimed) == 1
    item = claimed[0]
    assert worker_a.heartbeat(item) is True
    assert OutboxWorker(Capture(), worker_id="outbox-b").heartbeat(item) is False
    stale = dict(item, lock_token="stale-token")
    assert worker_a.heartbeat(stale) is False


def test_database_time_ignores_application_clock_skew(client, monkeypatch):
    seed_event(client)
    import go_hotel.services.outbox as outbox_module
    monkeypatch.setattr(outbox_module, "now_utc", lambda: now_utc() + timedelta(days=3650))
    claimed = OutboxWorker(Capture(), worker_id="db-time-worker").claim(limit=1)
    assert len(claimed) == 1
    with SessionLocal() as session:
        db_now = session.scalar(select(func.current_timestamp()))
        row = session.get(OutboxRow, claimed[0]["outbox_id"])
        locked = row.locked_at.replace(tzinfo=None) if row.locked_at.tzinfo else row.locked_at
        assert abs((locked - db_now).total_seconds()) < 10


def test_postgresql_two_workers_claim_one_row_once(client):
    with SessionLocal() as session:
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL row-lock semantics")
    seed_event(client)
    barrier = Barrier(2)
    def claim(worker_id):
        barrier.wait()
        return OutboxWorker(Capture(), worker_id=worker_id).claim(limit=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["pg-worker-a", "pg-worker-b"]))
    claimed = [item for batch in results for item in batch]
    assert len(claimed) == 1
    winner = "pg-worker-a" if results[0] else "pg-worker-b"
    assert OutboxWorker(Capture(), worker_id=winner).heartbeat(claimed[0]) is True
    loser = "pg-worker-b" if winner == "pg-worker-a" else "pg-worker-a"
    assert OutboxWorker(Capture(), worker_id=loser).heartbeat(claimed[0]) is False
