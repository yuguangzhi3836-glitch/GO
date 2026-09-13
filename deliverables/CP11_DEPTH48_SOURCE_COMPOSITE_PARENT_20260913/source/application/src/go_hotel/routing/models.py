from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any
from go_hotel.domain.models import Offer

@dataclass(frozen=True)
class ConnectorSlaScore:
    connector_id: str
    success_rate_bps: int = 10000
    confirmation_latency_ms_p95: int = 0
    cancel_success_rate_bps: int = 10000
    inventory_accuracy_bps: int = 10000
    price_consistency_bps: int = 10000
    composite_score_bps: int = 10000
    sample_size: int = 0
    health_status: str = "HEALTHY"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class RouteCandidate:
    connector_id: str
    offer: Offer
    supplier_id: str | None
    official_authorized: bool
    rollout_percent: int
    sla: ConnectorSlaScore
    cancellation_flex_rank: int = 0

    def ranking_key(self) -> tuple:
        # Deliberately lexicographic: commercial price can never outrank official authorization
        # or reliability. Recommendation/GO score is intentionally absent.
        return (
            1 if self.official_authorized else 0,
            self.sla.composite_score_bps,
            self.sla.success_rate_bps,
            self.cancellation_flex_rank,
            -self.offer.total_amount_minor,
        )

@dataclass(frozen=True)
class RoutingDecision:
    decision_id: str
    operation: str
    hotel_id: str | None
    selected_connector_id: str | None
    candidate_connector_ids: list[str]
    reason_codes: list[str]
    fallback_connector_ids: list[str]
    request_key: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
