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
