from __future__ import annotations

from .contracts import AgentContext, CommitRequest, OfferRequest, ReserveRequest
from .service import AgentTransactionGateway

A2A_PROTOCOL_VERSION = "1.0"

AGENT_CARD = {
    "name": "GO Travel Transaction Agent",
    "description": "Deterministic travel offer, reserve, commit, release and order-truth capabilities.",
    "version": "1.0.0",
    "protocolVersion": A2A_PROTOCOL_VERSION,
    "skills": [
        {"id": "offer.search", "name": "Search Offers", "tags": ["travel", "offer", "official-direct"]},
        {"id": "reserve", "name": "Reserve Offer", "tags": ["travel", "inventory", "transaction"]},
        {"id": "commit", "name": "Commit Reservation", "tags": ["travel", "payment", "order"]},
        {"id": "reserve.release", "name": "Release Reservation", "tags": ["travel", "inventory"]},
        {"id": "order.get", "name": "Get Order Truth", "tags": ["travel", "order", "truth"]},
    ],
}


class A2AAdapter:
    def __init__(self, gateway: AgentTransactionGateway):
        self.gateway = gateway

    def agent_card(self):
        return AGENT_CARD

    def execute(self, ctx: AgentContext, skill_id: str, payload: dict):
        if skill_id == "offer.search":
            return self.gateway.offers(ctx, OfferRequest(payload["product_type"], payload["search"]))
        if skill_id == "reserve":
            return self.gateway.reserve(ctx, ReserveRequest(payload["offer_id"], payload["idempotency_key"]))
        if skill_id == "commit":
            return self.gateway.commit(ctx, CommitRequest(payload["reserve_id"], payload["payment_intent_id"], payload["idempotency_key"]))
        if skill_id == "reserve.release":
            return self.gateway.release(ctx, payload["reserve_id"], payload["idempotency_key"])
        if skill_id == "order.get":
            return self.gateway.order(ctx, payload["order_id"])
        raise ValueError("A2A_SKILL_NOT_ALLOWED")
