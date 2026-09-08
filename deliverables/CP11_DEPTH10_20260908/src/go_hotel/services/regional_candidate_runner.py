"""Durable regional candidate execution without Redis/legacy worker authority."""
from __future__ import annotations

from .hotel_discovery_orchestrator import hotel_discovery_orchestrator_service as discovery


def _seed_from_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("REGIONAL_TASK_PAYLOAD_REQUIRED")
    seed = payload.get("discovery_seed")
    if isinstance(seed, dict):
        return dict(seed)
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else payload
    name = str(candidate.get("name") or candidate.get("name_zh") or "").strip()
    if not name:
        raise ValueError("REGIONAL_CANDIDATE_NAME_REQUIRED")
    source_hints = candidate.get("source_hints") if isinstance(candidate.get("source_hints"), list) else []
    external_ids = candidate.get("external_ids") if isinstance(candidate.get("external_ids"), dict) else {}
    return {
        "name": name,
        "country": candidate.get("country") or payload.get("country"),
        "city": candidate.get("city") or payload.get("city"),
        "address": candidate.get("address"),
        "latitude": candidate.get("latitude"),
        "longitude": candidate.get("longitude"),
        "external_ids": external_ids,
        "source_hints": source_hints,
    }


def run_regional_candidate(payload: dict, *, actor: str = "SYSTEM") -> dict:
    seed = _seed_from_payload(payload)
    registration = discovery.register_seed(seed, actor)
    result = discovery.run_job(registration["job_id"], actor, max_retries=2)
    state = result.get("build_state")
    if state not in {"READY", "NEEDS_ENRICHMENT"}:
        raise ValueError("REGIONAL_DISCOVERY_TERMINAL_STATE_INVALID")
    return {
        "job_id": registration["job_id"],
        "hotel_id": result.get("hotel_id"),
        "build_state": state,
        "failure_count": result.get("failure_count"),
        "result": result,
    }
