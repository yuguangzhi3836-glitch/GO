"""Chain directory -> durable task -> existing official discovery pipeline bridge."""
from __future__ import annotations

from .chain_hotel_registry import ChainCode, OfficialPropertySeed
from .chain_task_lease import chain_task_lease_service
from .hyatt_directory_adapter import HyattDirectoryAdapter
from .standard_chain_directory_adapters import (
    MarriottDirectoryAdapter, ShangriLaDirectoryAdapter, HiltonDirectoryAdapter,
    IHGDirectoryAdapter, HWorldDirectoryAdapter, AtourDirectoryAdapter,
)


ADAPTERS = {
    ChainCode.HYATT: HyattDirectoryAdapter,
    ChainCode.MARRIOTT: MarriottDirectoryAdapter,
    ChainCode.SHANGRI_LA: ShangriLaDirectoryAdapter,
    ChainCode.HILTON: HiltonDirectoryAdapter,
    ChainCode.IHG: IHGDirectoryAdapter,
    ChainCode.H_WORLD: HWorldDirectoryAdapter,
    ChainCode.ATOUR: AtourDirectoryAdapter,
}


def discovery_seed(seed: OfficialPropertySeed) -> dict:
    return {
        "name": seed.name,
        "country": seed.country_code,
        "city": seed.city,
        "external_ids": {f"chain:{seed.chain.value.lower()}": seed.official_property_id},
        "source_hints": [{
            "kind": "GROUP_OFFICIAL",
            "source_key": f"chain:{seed.chain.value.lower()}",
            "external_hotel_id": seed.official_property_id,
            "url": seed.property_url,
            "rights_status": "PUBLIC_BUSINESS_FACT",
            "confidence_bps": 9900,
        }],
    }


class ChainAutonomousBuildService:
    def enumerate_and_enqueue(self, *, chain: ChainCode, fetch_page, cursor: str | None = None,
                              actor: str = "SYSTEM") -> dict:
        adapter_cls = ADAPTERS.get(chain)
        if adapter_cls is None:
            raise ValueError("CHAIN_DIRECTORY_ADAPTER_NOT_IMPLEMENTED")
        adapter = adapter_cls()
        seeds, next_cursor = adapter.enumerate_page(fetch_page, cursor)
        queued = []
        for seed in seeds:
            payload = {
                "task": "CHAIN_HOTEL", "chain": seed.chain.value,
                "official_property_id": seed.official_property_id,
                "idempotency_key": seed.idempotency_key,
                "directory_url": seed.directory_url,
                "discovery_seed": discovery_seed(seed),
            }
            task = chain_task_lease_service.enqueue(task_id=seed.idempotency_key, payload=payload, actor=actor)
            queued.append({"task_id": task.task_id, "state": task.state, "attempt": task.attempt})
        return {
            "chain": chain.value, "enumerated": len(seeds), "tasks": queued,
            "next_cursor": next_cursor, "directory_complete": next_cursor is None,
        }

    def process_one(self, *, worker_id: str, actor: str = "SYSTEM", lease_seconds: int = 180) -> dict | None:
        task = chain_task_lease_service.claim(worker_id=worker_id, lease_seconds=lease_seconds, actor=actor)
        if task is None:
            return None
        try:
            payload = task.payload
            if payload.get("task") != "CHAIN_HOTEL":
                raise ValueError("CHAIN_TASK_TYPE_INVALID")
            from .hotel_discovery_orchestrator import hotel_discovery_orchestrator_service as discovery
            seed = payload.get("discovery_seed")
            if not isinstance(seed, dict):
                raise ValueError("CHAIN_DISCOVERY_SEED_REQUIRED")
            registration = discovery.register_seed(seed, actor)
            result = discovery.run_job(registration["job_id"], actor, max_retries=2)
            build_state = result.get("build_state")
            if build_state not in {"READY", "NEEDS_ENRICHMENT"}:
                raise ValueError("CHAIN_DISCOVERY_TERMINAL_STATE_INVALID")
            chain_task_lease_service.ack(
                task_id=task.task_id, worker_id=worker_id,
                result={"job_id": registration["job_id"], "hotel_id": result.get("hotel_id"),
                        "build_state": build_state, "failure_count": result.get("failure_count")},
                actor=actor,
            )
            return {"task_id": task.task_id, "state": "ACKED", "result": result}
        except Exception as exc:
            text = str(exc)
            deterministic = any(token in text for token in (
                "IDENTITY", "SOURCE_HOST_NOT_ALLOWED", "OFFICIAL_HTTPS", "DIRECTORY_",
                "CATALOG_TOO_LARGE", "BELONGS_TO_ANOTHER_HOTEL", "TYPE_INVALID",
            ))
            failed = chain_task_lease_service.fail(
                task_id=task.task_id, worker_id=worker_id, error=text,
                retryable=not deterministic, actor=actor,
            )
            return {"task_id": task.task_id, "state": failed.state, "error": text}


chain_autonomous_build_service = ChainAutonomousBuildService()
