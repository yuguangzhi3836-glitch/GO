from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from go_hotel.domain.models import Offer

@dataclass
class NormalizedPolicy:
    refundable: bool
    cancellation_deadline: str | None
    fare_rule_id: str
    fingerprint: str

@dataclass
class MergeCandidate:
    offer: Offer
    canonical_room_id: str
    room_confidence_bps: int
    policy: NormalizedPolicy
    source_priority: int = 0

@dataclass
class MergeDecision:
    decision_id: str
    hotel_id: str
    canonical_room_id: str
    selected_offer_id: str
    selected_connector_id: str
    alternate_offer_ids: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
