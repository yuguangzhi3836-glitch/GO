from __future__ import annotations

from .contracts import AgentContext, CommitRequest, OfferRequest, ReserveRequest
from .service import AgentTransactionGateway

MCP_PROTOCOL_VERSION = "2026-07-28"

TOOLS = (
    {"name": "go.travel.offer.search", "description": "Search machine-executable GO travel offers."},
    {"name": "go.travel.reserve", "description": "Atomically reserve a selected GO offer."},
    {"name": "go.travel.commit", "description": "Commit a valid reservation after payment success."},
    {"name": "go.travel.reserve.release", "description": "Release a reservation idempotently."},
    {"name": "go.travel.order.get", "description": "Read deterministic GO order truth."},
)


class MCPAdapter:
    def __init__(self, gateway: AgentTransactionGateway):
        self.gateway = gateway

    def list_tools(self):
        return {"protocolVersion": MCP_PROTOCOL_VERSION, "tools": list(TOOLS)}

    def call_tool(self, ctx: AgentContext, name: str, arguments: dict):
        if name == "go.travel.offer.search":
            return self.gateway.offers(ctx, OfferRequest(product_type=arguments["product_type"], search=arguments["search"]))
        if name == "go.travel.reserve":
            return self.gateway.reserve(ctx, ReserveRequest(offer_id=arguments["offer_id"], idempotency_key=arguments["idempotency_key"]))
        if name == "go.travel.commit":
            return self.gateway.commit(ctx, CommitRequest(reserve_id=arguments["reserve_id"], payment_intent_id=arguments["payment_intent_id"], idempotency_key=arguments["idempotency_key"]))
        if name == "go.travel.reserve.release":
            return self.gateway.release(ctx, arguments["reserve_id"], arguments["idempotency_key"])
        if name == "go.travel.order.get":
            return self.gateway.order(ctx, arguments["order_id"])
        raise ValueError("MCP_TOOL_NOT_ALLOWED")
