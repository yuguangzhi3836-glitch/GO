"""Single production binding point for DEPTH10 hotel autonomous build.

New runtime code imports queue/media authorities from this module so production
cannot silently fall back to DEPTH09 Redis delivery or process-local media indexes.
"""
from __future__ import annotations

from .durable_media_harvester import durable_media_harvester_service
from .media_blob_recovery import media_blob_recovery_service
from .regional_build_cutover import enqueue as enqueue_regional_build, authority as regional_authority
from .regional_durable_worker import regional_durable_worker_service
from .chain_autonomous_build import chain_autonomous_build_service
from .chain_directory_controller import chain_directory_controller

media_harvester = durable_media_harvester_service
media_recovery = media_blob_recovery_service
regional_enqueue = enqueue_regional_build
regional_worker = regional_durable_worker_service
chain_builder = chain_autonomous_build_service
chain_directory = chain_directory_controller


def media_recovery_gate(*, orphan_grace_seconds: int = 3600, quarantine: bool = True) -> dict:
    result = media_recovery.reconcile(orphan_grace_seconds=orphan_grace_seconds, quarantine=quarantine)
    safe = media_recovery.release_safe(result)
    return {
        "status": "PASS" if safe else "HOLD",
        "referenced": result.referenced,
        "orphaned": result.orphaned,
        "quarantined": result.quarantined,
        "missing": result.missing,
        "corrupt": result.corrupt,
        "release_safe": safe,
        "actions": list(result.actions),
    }


def production_authorities() -> dict:
    regional = regional_authority()
    return {
        "regional_queue": regional["queue_authority"],
        "legacy_redis_default": regional["legacy_redis_default"],
        "legacy_redis_authority_removed": regional.get("legacy_redis_authority_removed") is True,
        "media_metadata": "POSTGRES_DURABLE_MEDIA_LEDGER",
        "media_blob_model": "IMMUTABLE_CONTENT_ADDRESSED_WITH_RECONCILIATION",
        "media_recovery_authority": "POSTGRES_LEDGER_TO_BLOB_RECONCILER",
        "media_local_json_authority": False,
        "chain_task_authority": "POSTGRES_DURABLE_LEASE_ACK",
        "release_safe": (
            regional.get("legacy_redis_break_glass_enabled") is False
            and regional.get("legacy_redis_authority_removed") is True
        ),
    }
