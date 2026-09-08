"""PostgreSQL-authoritative regional worker; Redis is not a production path."""
from __future__ import annotations

import hashlib
import json

from .chain_task_lease import chain_task_lease_service
from .lease_heartbeat import LeaseHeartbeat
from .regional_candidate_runner import run_regional_candidate


def regional_task_id(payload: dict) -> str:
    if not isinstance(payload, dict): raise ValueError("REGIONAL_TASK_PAYLOAD_REQUIRED")
    explicit = str(payload.get("idempotency_key") or "").strip()
    if explicit: return "regional_" + hashlib.sha256(explicit.encode()).hexdigest()[:32]
    stable = {"country": payload.get("country"), "province": payload.get("province"), "city": payload.get("city"),
              "tier": payload.get("tier"), "provider": payload.get("provider"),
              "external_hotel_id": payload.get("external_hotel_id"), "external_ids": payload.get("external_ids") or {}}
    if not any(v for v in stable.values()): raise ValueError("REGIONAL_TASK_STABLE_IDENTITY_REQUIRED")
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "regional_" + hashlib.sha256(raw.encode()).hexdigest()[:32]


class RegionalDurableWorkerService:
    def enqueue(self, payload: dict, *, actor: str = "SYSTEM") -> dict:
        task_id = regional_task_id(payload)
        wrapped = {"task": "REGIONAL_HOTEL", "regional_payload": dict(payload), "idempotency_key": task_id}
        task = chain_task_lease_service.enqueue(task_id=task_id, payload=wrapped, actor=actor)
        return {"task_id": task.task_id, "state": task.state, "attempt": task.attempt}

    def process_one(self, *, worker_id: str, actor: str = "SYSTEM", lease_seconds: int = 180):
        task = chain_task_lease_service.claim(worker_id=worker_id, lease_seconds=lease_seconds, actor=actor, task_type="REGIONAL_HOTEL")
        if task is None: return None
        try:
            payload = task.payload.get("regional_payload")
            if not isinstance(payload, dict): raise ValueError("REGIONAL_TASK_PAYLOAD_REQUIRED")
            with LeaseHeartbeat(task_id=task.task_id, worker_id=worker_id, lease_seconds=lease_seconds, actor=actor) as heartbeat:
                result = run_regional_candidate(payload, actor=actor)
                heartbeat.assert_healthy()
            chain_task_lease_service.ack(task_id=task.task_id, worker_id=worker_id, result=result, actor=actor)
            return {"task_id": task.task_id, "state": "ACKED", "result": result}
        except Exception as exc:
            text = str(exc)
            deterministic = any(x in text for x in ("IDENTITY", "TYPE_INVALID", "PAYLOAD_REQUIRED", "NAME_REQUIRED"))
            failed = chain_task_lease_service.fail(task_id=task.task_id, worker_id=worker_id, error=text,
                                                   retryable=not deterministic, actor=actor)
            return {"task_id": task.task_id, "state": failed.state, "error": text}

    @staticmethod
    def legacy_redis_allowed() -> bool:
        return False


regional_durable_worker_service = RegionalDurableWorkerService()
