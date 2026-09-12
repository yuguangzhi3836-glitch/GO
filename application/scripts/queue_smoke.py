#!/usr/bin/env python3
import os
import uuid
from go_hotel.queue import RedisQueue

q = RedisQueue(os.getenv("REDIS_URL"))
assert q.ping()
mid = f"smoke-{uuid.uuid4()}"
q.enqueue("staging-smoke", mid, {"ok": True})
msg = q.dequeue("staging-smoke", timeout_seconds=2)
assert msg and msg.message_id == mid and msg.payload["ok"] is True
print("REDIS_QUEUE_SMOKE=PASS")
