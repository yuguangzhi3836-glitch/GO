from __future__ import annotations
import json
import logging
import time
from datetime import timedelta
from typing import Protocol
from uuid import uuid4
import httpx
from sqlalchemy import select, or_
from go_hotel.core.config import settings
from go_hotel.db.models import OutboxRow, OutboxDeadLetterRow
from go_hotel.db.session import SessionLocal
from go_hotel.domain.models import now_utc

log = logging.getLogger("go_hotel.outbox")

class EventTransport(Protocol):
    def publish(self, topic: str, event: dict) -> None: ...

class LoggingTransport:
    def publish(self, topic: str, event: dict) -> None:
        log.info("publish topic=%s event=%s", topic, json.dumps(event, separators=(",", ":"), default=str))

class RedisTransport:
    def __init__(self, url: str):
        from go_hotel.queue import RedisQueue
        self.queue = RedisQueue(url)
    def publish(self, topic: str, event: dict) -> None:
        event_id = str(event.get("event_id") or event.get("id") or uuid4())
        self.queue.enqueue(topic, event_id, event)

class HttpTransport:
    def __init__(self, url: str): self.url = url
    def publish(self, topic: str, event: dict) -> None:
        r = httpx.post(self.url, json={"topic": topic, "event": event}, timeout=5.0)
        r.raise_for_status()

def build_transport() -> EventTransport:
    if settings.outbox_transport.lower() == "redis":
        return RedisTransport(settings.redis_url)
    if settings.outbox_transport.lower() == "http":
        if not settings.outbox_http_url:
            raise RuntimeError("OUTBOX_HTTP_URL is required when OUTBOX_TRANSPORT=http")
        return HttpTransport(settings.outbox_http_url)
    return LoggingTransport()

class OutboxWorker:
    """Durable polling publisher using row claims, retry/backoff and a dead-letter table."""
    def __init__(self, transport: EventTransport | None = None, worker_id: str | None = None):
        self.transport = transport or build_transport()
        self.worker_id = worker_id or f"outbox-{uuid4().hex[:8]}"

    def claim(self, limit: int | None = None) -> list[dict]:
        limit = limit or settings.outbox_batch_size
        now = now_utc(); stale_before = now - timedelta(seconds=settings.outbox_lock_timeout_seconds)
        token = uuid4().hex
        with SessionLocal.begin() as s:
            stmt = (select(OutboxRow)
                .where(
                    OutboxRow.available_at <= now,
                    or_(
                        OutboxRow.status.in_(["PENDING", "RETRY"]),
                        (OutboxRow.status == "PROCESSING") & (OutboxRow.locked_at < stale_before),
                    ),
                )
                .order_by(OutboxRow.outbox_id)
                .limit(limit)
                .with_for_update(skip_locked=True))
            rows = s.scalars(stmt).all()
            result = []
            for row in rows:
                row.status = "PROCESSING"; row.locked_at = now; row.lock_token = token; row.worker_id = self.worker_id
                result.append({"outbox_id": row.outbox_id, "topic": row.topic, "payload": row.payload, "attempt_count": row.attempt_count, "lock_token": token})
            return result

    def _success(self, item: dict) -> None:
        with SessionLocal.begin() as s:
            row = s.execute(select(OutboxRow).where(OutboxRow.outbox_id == item["outbox_id"], OutboxRow.lock_token == item["lock_token"]).with_for_update()).scalar_one_or_none()
            if row is None: return
            row.status = "PUBLISHED"; row.attempt_count += 1; row.published_at = now_utc(); row.last_error = None; row.locked_at = None; row.lock_token = None; row.worker_id = None

    def _failure(self, item: dict, exc: Exception) -> None:
        with SessionLocal.begin() as s:
            row = s.execute(select(OutboxRow).where(OutboxRow.outbox_id == item["outbox_id"], OutboxRow.lock_token == item["lock_token"]).with_for_update()).scalar_one_or_none()
            if row is None: return
            row.attempt_count += 1; row.last_error = str(exc); row.locked_at = None; row.lock_token = None; row.worker_id = None
            if row.attempt_count >= settings.outbox_max_attempts:
                row.status = "DEAD_LETTERED"; row.dead_lettered_at = now_utc()
                s.add(OutboxDeadLetterRow(outbox_id=row.outbox_id, event_id=row.event_id, event_type=row.event_type, aggregate_id=row.aggregate_id, payload=row.payload, attempt_count=row.attempt_count, last_error=row.last_error, dead_lettered_at=row.dead_lettered_at))
            else:
                delay = min(300, 2 ** max(0, row.attempt_count - 1))
                row.status = "RETRY"; row.available_at = now_utc() + timedelta(seconds=delay)

    def run_once(self, limit: int | None = None) -> dict:
        claimed = self.claim(limit)
        published = failed = 0
        for item in claimed:
            try:
                self.transport.publish(item["topic"], item["payload"])
                self._success(item); published += 1
            except Exception as exc:
                self._failure(item, exc); failed += 1
        return {"claimed": len(claimed), "published": published, "failed": failed}

    def run_forever(self) -> None:
        while True:
            result = self.run_once()
            if result["claimed"] == 0:
                time.sleep(settings.outbox_poll_seconds)

# Backwards-compatible alias used by Sprint 1D endpoint/tests.
outbox_publisher = OutboxWorker()
