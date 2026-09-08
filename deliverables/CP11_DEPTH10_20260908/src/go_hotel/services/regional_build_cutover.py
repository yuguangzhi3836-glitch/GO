"""DEPTH10 regional-build queue authority.

New production callers import `enqueue` from here. PostgreSQL durable lease/ACK is
the default and only supported authority. Legacy Redis enqueue requires an explicit
break-glass compatibility flag and is intentionally isolated.
"""
from __future__ import annotations

import os

from .regional_durable_worker import regional_durable_worker_service


def enqueue(payload: dict, *, actor: str = "SYSTEM") -> dict:
    return regional_durable_worker_service.enqueue(payload, actor=actor)


def legacy_redis_enqueue(payload: dict):
    allowed = str(os.getenv("GO_HOTEL_ALLOW_LEGACY_REDIS_REGIONAL_WORKER") or "").strip().lower() in {"1", "true", "yes"}
    if not allowed:
        raise ValueError("LEGACY_REDIS_REGIONAL_WORKER_DISABLED")
    # Delayed import prevents Redis from becoming an implicit dependency of the
    # durable path. This exists only for staged rollback before the runtime gate.
    from .regional_hotel_build import enqueue as legacy_enqueue
    return legacy_enqueue(payload)


def authority() -> dict:
    return {
        "queue_authority": "POSTGRES_DURABLE_LEASE_ACK",
        "legacy_redis_default": False,
        "legacy_redis_break_glass_enabled": str(os.getenv("GO_HOTEL_ALLOW_LEGACY_REDIS_REGIONAL_WORKER") or "").strip().lower() in {"1", "true", "yes"},
    }
