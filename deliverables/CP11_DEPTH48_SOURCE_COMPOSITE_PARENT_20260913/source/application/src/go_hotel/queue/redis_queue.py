from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

try:
    from redis import Redis
except Exception:  # pragma: no cover
    Redis = None  # type: ignore


@dataclass(frozen=True)
class QueueMessage:
    message_id: str
    topic: str
    payload: dict[str, Any]
    enqueued_at: float


class RedisQueue:
    """Small production queue boundary used by staging workers.

    Uses Redis lists for durable-enough staging delivery semantics. Domain facts
    remain in PostgreSQL/outbox; Redis is a delivery accelerator, never a source
    of truth. Messages may be delivered more than once; consumers must remain
    idempotent.
    """

    def __init__(self, url: str | None = None, namespace: str = "go") -> None:
        if Redis is None:
            raise RuntimeError("redis package is required")
        self.url = url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.namespace = namespace
        self.client = Redis.from_url(self.url, decode_responses=True)

    def _key(self, topic: str) -> str:
        return f"{self.namespace}:queue:{topic}"

    def ping(self) -> bool:
        return bool(self.client.ping())

    def enqueue(self, topic: str, message_id: str, payload: dict[str, Any]) -> QueueMessage:
        msg = QueueMessage(message_id=message_id, topic=topic, payload=payload, enqueued_at=time.time())
        self.client.lpush(self._key(topic), json.dumps(msg.__dict__, separators=(",", ":"), sort_keys=True))
        return msg

    def dequeue(self, topic: str, timeout_seconds: int = 1) -> QueueMessage | None:
        item = self.client.brpop(self._key(topic), timeout=timeout_seconds)
        if not item:
            return None
        _, raw = item
        obj = json.loads(raw)
        return QueueMessage(**obj)

    def depth(self, topic: str) -> int:
        return int(self.client.llen(self._key(topic)))
