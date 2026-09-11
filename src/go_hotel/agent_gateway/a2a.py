from __future__ import annotations

from dataclasses import asdict

from .contracts import AgentContext, CommitRequest, OfferRequest, PaymentRequest, ReserveRequest
from .service import AgentTransactionGateway

A2A_PROTOCOL_VERSION = "1.0"
GO_TRANSACTION_EXTENSION = "urn:go:a2a:transaction-skill:v1"

SKILLS = [
    {"id": "offer.search", "name": "Search Offers", "description": "Search GO machine-executable travel offers.", "tags": ["travel", "offer", "official-direct"]},
    {"id": "reserve", "name": "Reserve Offer", "description": "Reserve an accepted GO quote using native transaction truth.", "tags": ["travel", "inventory", "transaction"]},
    {"id": "payment.prepare", "name": "Prepare Payment Truth", "description": "Establish authoritative payment truth for a GO reservation.", "tags": ["travel", "payment", "truth"]},
    {"id": "commit", "name": "Commit Reservation", "description": "Commit a reservation only against matching payment truth.", "tags": ["travel", "payment", "order"]},
    {"id": "reserve.release", "name": "Release Reservation", "description": "Release a GO reservation through its native vertical cancellation path.", "tags": ["travel", "inventory"]},
    {"id": "order.get", "name": "Get Order Truth", "description": "Read deterministic GO order truth.", "tags": ["travel", "order", "truth"]},
]


def build_agent_card(interface_url: str) -> dict:
    return {
        "name": "GO Travel Transaction Agent",
        "description": "Deterministic GO offer, reserve, payment-truth, commit and order capabilities.",
        "supportedInterfaces": [
            {"url": interface_url, "protocolBinding": "JSONRPC", "protocolVersion": A2A_PROTOCOL_VERSION}
        ],
        "version": "1.1.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extendedAgentCard": False,
            "extensions": [{
                "uri": GO_TRANSACTION_EXTENSION,
                "description": "Carries a GO transaction skill id and structured payload in SendMessage metadata.",
                "required": True,
            }],
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": SKILLS,
    }


class A2AAdapter:
    def __init__(self, gateway: AgentTransactionGateway):
        self.gateway = gateway

    def agent_card(self, interface_url: str = "https://agent.invalid/a2a/v1"):
        return build_agent_card(interface_url)

    async def execute(self, ctx: AgentContext, skill_id: str, payload: dict):
        if skill_id == "offer.search":
            return await self.gateway.offers(ctx, OfferRequest(payload["product_type"], payload["search"]))
        if skill_id == "reserve":
            return await self.gateway.reserve(ctx, ReserveRequest(payload["offer_id"], payload["quote_hash"], payload.get("search") or {}, payload.get("booking") or {}, payload["idempotency_key"]))
        if skill_id == "payment.prepare":
            return await self.gateway.payment(ctx, PaymentRequest(payload["reserve_id"], int(payload["expected_total_minor"]), payload["currency"].upper(), payload["payment_method_id"], payload["idempotency_key"]))
        if skill_id == "commit":
            return await self.gateway.commit(ctx, CommitRequest(payload["reserve_id"], payload["payment_truth_id"], payload["idempotency_key"]))
        if skill_id == "reserve.release":
            return await self.gateway.release(ctx, payload["reserve_id"], payload["idempotency_key"])
        if skill_id == "order.get":
            return await self.gateway.order(ctx, payload["order_id"])
        raise ValueError("A2A_SKILL_NOT_ALLOWED")

    async def structured_execute(self, ctx: AgentContext, skill_id: str, payload: dict) -> dict:
        return asdict(await self.execute(ctx, skill_id, payload))
