"""DEPTH10 regional-build authority: PostgreSQL durable lease/ACK only."""
from __future__ import annotations

from .regional_durable_worker import regional_durable_worker_service


def enqueue(payload: dict, *, actor: str = "SYSTEM") -> dict:
    return regional_durable_worker_service.enqueue(payload, actor=actor)


def legacy_redis_enqueue(payload: dict):
    # DEPTH10 removes the rollback authority entirely. Historical code may remain
    # in an archived parent tree for lineage, but assembled production must never
    # import or execute Redis regional delivery.
    raise RuntimeError("LEGACY_REDIS_REGIONAL_AUTHORITY_REMOVED")


def authority() -> dict:
    return {
        "queue_authority": "POSTGRES_DURABLE_LEASE_ACK",
        "legacy_redis_default": False,
        "legacy_redis_break_glass_enabled": False,
        "legacy_redis_authority_removed": True,
    }
