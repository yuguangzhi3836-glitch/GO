"""Single production binding point for DEPTH10 hotel autonomous build.

New runtime code must import queue/media authorities from this module. The purpose
is to prevent accidental fall-through to DEPTH09's Redis BRPOP queue or process-
local media index. Legacy modules remain readable for migration/rollback only.
"""
from __future__ import annotations

from .durable_media_harvester import durable_media_harvester_service
from .regional_build_cutover import enqueue as enqueue_regional_build, authority as regional_authority
from .regional_durable_worker import regional_durable_worker_service
from .chain_autonomous_build import chain_autonomous_build_service
from .chain_directory_controller import chain_directory_controller


media_harvester = durable_media_harvester_service
regional_enqueue = enqueue_regional_build
regional_worker = regional_durable_worker_service
chain_builder = chain_autonomous_build_service
chain_directory = chain_directory_controller


def production_authorities() -> dict:
    regional = regional_authority()
    return {
        "regional_queue": regional["queue_authority"],
        "legacy_redis_default": regional["legacy_redis_default"],
        "media_metadata": "POSTGRES_DURABLE_MEDIA_LEDGER",
        "media_local_json_authority": False,
        "chain_task_authority": "POSTGRES_DURABLE_LEASE_ACK",
        "release_safe": not regional["legacy_redis_break_glass_enabled"],
    }
