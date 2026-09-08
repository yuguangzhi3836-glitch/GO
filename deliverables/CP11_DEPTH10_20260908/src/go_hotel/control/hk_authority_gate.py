"""Explicit constitution/authority gate for HK Staging controlled execution."""
from __future__ import annotations

MUTATING = {"POSTGRES_CRASH_RECOVERY_GATE", "HYATT_10_REAL_E2E", "HOTEL_MASTERPIECE_BROWSER_GATE"}


def enforce_hk_authority(*, task_type: str, environment: str, authority: str, production_authorities: dict) -> None:
    if environment != "HK_STAGING": raise ValueError("AUTHORITY_ENVIRONMENT_DENIED")
    if production_authorities.get("release_safe") is not True: raise ValueError("AUTHORITY_PRODUCTION_BINDINGS_UNSAFE")
    if production_authorities.get("regional_queue") != "POSTGRES_DURABLE_LEASE_ACK": raise ValueError("AUTHORITY_DURABLE_QUEUE_REQUIRED")
    if production_authorities.get("media_metadata") != "POSTGRES_DURABLE_MEDIA_LEDGER": raise ValueError("AUTHORITY_DURABLE_MEDIA_REQUIRED")
    if production_authorities.get("media_local_json_authority") is not False: raise ValueError("AUTHORITY_LOCAL_MEDIA_INDEX_FORBIDDEN")
    if task_type in MUTATING and authority != "STAGING_CONTROLLED_EXECUTE":
        raise ValueError("AUTHORITY_CONTROLLED_EXECUTE_REQUIRED")
    if task_type not in MUTATING and authority not in {"STAGING_READONLY", "STAGING_CONTROLLED_EXECUTE"}:
        raise ValueError("AUTHORITY_SCOPE_INVALID")
