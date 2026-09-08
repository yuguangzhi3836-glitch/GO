"""Media Harvester -> durable media index publication bridge.

The harvester may still download/cache bytes, but a downloaded file is not eligible
for C-end use until this bridge has transactionally registered metadata and rights
evidence in PostgreSQL. This module is deliberately fail-closed.
"""
from __future__ import annotations

from .durable_media_index import durable_media_index_service


class DurableHarvesterBridge:
    def persist_harvest(self, harvested: dict, *, actor: str = "SYSTEM") -> dict:
        if not isinstance(harvested, dict):
            raise ValueError("MEDIA_HARVEST_RESULT_REQUIRED")
        record = {
            "asset_id": harvested.get("media_asset_id") or harvested.get("asset_id"),
            "hotel_id": harvested.get("hotel_id"),
            "room_type_id": harvested.get("room_type_id"),
            "role": harvested.get("role") or "HOTEL",
            "sha256": harvested.get("sha256"),
            "cache_file": harvested.get("cache_file") or harvested.get("local_path"),
            "cache_state": harvested.get("cache_state") or "VALIDATED",
            "source_url": harvested.get("source_url") or harvested.get("url"),
            "source_kind": harvested.get("source_kind"),
            "width": harvested.get("width"), "height": harvested.get("height"),
            "mime_type": harvested.get("mime_type"),
        }
        current = durable_media_index_service.register(record, actor=actor)
        rights_state = harvested.get("rights_state") or harvested.get("rights_status")
        if rights_state:
            current = durable_media_index_service.decide_rights(
                current["asset_id"], rights_state=str(rights_state), actor=actor,
                rights_owner=harvested.get("rights_owner"),
                evidence_reference=harvested.get("rights_evidence_reference") or harvested.get("evidence_reference"),
                rights_basis=harvested.get("rights_basis"),
            )
        return current

    def publish_if_eligible(self, asset_id: str, *, actor: str = "SYSTEM") -> dict:
        current = durable_media_index_service.get(asset_id)
        if not current.get("publishable"):
            raise ValueError("MEDIA_HARVEST_DURABLE_RIGHTS_GATE_HOLD")
        return durable_media_index_service.set_publication(asset_id, publish=True, actor=actor)


media_harvester_durable_bridge = DurableHarvesterBridge()
