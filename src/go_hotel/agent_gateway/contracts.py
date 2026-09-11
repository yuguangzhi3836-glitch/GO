from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class AgentProtocol(str, Enum):
    REST = "REST"
    MCP = "MCP"
    A2A = "A2A"
    APPLE_APP_INTENTS = "APPLE_APP_INTENTS"


class SupplyRoute(str, Enum):
    OFFICIAL_DIRECT = "OFFICIAL_DIRECT"
    AUTHORIZED_FALLBACK = "AUTHORIZED_FALLBACK"


@dataclass(frozen=True)
class AgentContext:
    request_id: str
    trace_id: str
    agent_id: str
    protocol: AgentProtocol
    purpose: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    traveler_ref: str | None = None

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise PermissionError(f"AGENT_SCOPE_REQUIRED:{scope}")

    def require_traveler(self) -> str:
        if not self.traveler_ref:
            raise PermissionError("AGENT_TRAVELER_CONTEXT_REQUIRED")
        return self.traveler_ref


@dataclass(frozen=True)
class OfferRequest:
    product_type: str
    search: Mapping[str, Any]


@dataclass(frozen=True)
class Offer:
    offer_id: str
    product_type: str
    supplier_id: str
    product_id: str
    supply_route: SupplyRoute
    total_minor: int
    currency: str
    expires_at: str | None
    inventory_status: str
    inventory_version: str | None
    machine_bookable: bool
    cancellation: Mapping[str, Any]
    quote_hash: str
    reserve_context: Mapping[str, Any]
    evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.total_minor < 0:
            raise ValueError("OFFER_TOTAL_MINOR_INVALID")
        if len(self.currency) != 3 or self.currency.upper() != self.currency:
            raise ValueError("OFFER_CURRENCY_INVALID")
        if not self.offer_id or not self.product_type or not self.supplier_id or not self.product_id:
            raise ValueError("OFFER_IDENTITY_REQUIRED")
        if not self.quote_hash:
            raise ValueError("OFFER_QUOTE_HASH_REQUIRED")


@dataclass(frozen=True)
class ReserveRequest:
    offer_id: str
    quote_hash: str
    search: Mapping[str, Any]
    booking: Mapping[str, Any]
    idempotency_key: str


@dataclass(frozen=True)
class Reservation:
    reserve_id: str
    offer_id: str
    product_type: str
    status: str
    expires_at: str | None
    inventory_version: str | None
    total_minor: int
    currency: str
    order_id: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class PaymentRequest:
    reserve_id: str
    expected_total_minor: int
    currency: str
    payment_method_id: str
    idempotency_key: str


@dataclass(frozen=True)
class PaymentTruth:
    payment_truth_id: str
    reserve_id: str
    product_type: str
    state: str
    total_minor: int
    currency: str
    captured: bool
    external_live: bool
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class CommitRequest:
    reserve_id: str
    payment_truth_id: str
    idempotency_key: str


@dataclass(frozen=True)
class Order:
    order_id: str
    reserve_id: str
    product_type: str
    status: str
    supplier_confirmation: str | None
    payment_state: str
    transaction_version: str
    total_minor: int
    currency: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class AgentEnvelope:
    data: Mapping[str, Any]
    request_id: str
    trace_id: str
    authority: str = "GO_DETERMINISTIC_CORE"
