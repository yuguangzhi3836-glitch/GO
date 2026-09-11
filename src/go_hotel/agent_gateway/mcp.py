from __future__ import annotations

from dataclasses import asdict

from .contracts import AgentContext, CommitRequest, OfferRequest, PaymentRequest, ReserveRequest
from .service import AgentTransactionGateway

MCP_PROTOCOL_VERSION = "2026-07-28"


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


TOOLS = (
    {
        "name": "go.travel.offer.search",
        "description": "Search machine-executable GO travel offers.",
        "inputSchema": _schema(
            {"product_type": {"type": "string"}, "search": {"type": "object"}},
            ["product_type", "search"],
        ),
    },
    {
        "name": "go.travel.reserve",
        "description": "Reserve an accepted quote through GO's native transaction core.",
        "inputSchema": _schema(
            {
                "offer_id": {"type": "string"},
                "quote_hash": {"type": "string"},
                "search": {"type": "object"},
                "booking": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            ["offer_id", "quote_hash", "search", "booking", "idempotency_key"],
        ),
    },
    {
        "name": "go.travel.payment.prepare",
        "description": "Create authoritative GO payment truth for a reservation.",
        "inputSchema": _schema(
            {
                "reserve_id": {"type": "string"},
                "expected_total_minor": {"type": "integer", "minimum": 1},
                "currency": {"type": "string", "minLength": 3, "maxLength": 3},
                "payment_method_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            ["reserve_id", "expected_total_minor", "currency", "payment_method_id", "idempotency_key"],
        ),
    },
    {
        "name": "go.travel.commit",
        "description": "Commit a reservation only against matching payment truth.",
        "inputSchema": _schema(
            {
                "reserve_id": {"type": "string"},
                "payment_truth_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            ["reserve_id", "payment_truth_id", "idempotency_key"],
        ),
    },
    {
        "name": "go.travel.reserve.release",
        "description": "Release a reservation through its native vertical path.",
        "inputSchema": _schema(
            {"reserve_id": {"type": "string"}, "idempotency_key": {"type": "string"}},
            ["reserve_id", "idempotency_key"],
        ),
    },
    {
        "name": "go.travel.order.get",
        "description": "Read deterministic GO order truth.",
        "inputSchema": _schema({"order_id": {"type": "string"}}, ["order_id"]),
    },
)


class MCPAdapter:
    def __init__(self, gateway: AgentTransactionGateway):
        self.gateway = gateway

    def list_tools(self):
        return {"protocolVersion": MCP_PROTOCOL_VERSION, "tools": list(TOOLS)}

    async def call_tool(self, ctx: AgentContext, name: str, arguments: dict):
        if name == "go.travel.offer.search":
            return await self.gateway.offers(ctx, OfferRequest(arguments["product_type"], arguments["search"]))
        if name == "go.travel.reserve":
            return await self.gateway.reserve(ctx, ReserveRequest(arguments["offer_id"], arguments["quote_hash"], arguments.get("search") or {}, arguments.get("booking") or {}, arguments["idempotency_key"]))
        if name == "go.travel.payment.prepare":
            return await self.gateway.payment(ctx, PaymentRequest(arguments["reserve_id"], int(arguments["expected_total_minor"]), arguments["currency"].upper(), arguments["payment_method_id"], arguments["idempotency_key"]))
        if name == "go.travel.commit":
            return await self.gateway.commit(ctx, CommitRequest(arguments["reserve_id"], arguments["payment_truth_id"], arguments["idempotency_key"]))
        if name == "go.travel.reserve.release":
            return await self.gateway.release(ctx, arguments["reserve_id"], arguments["idempotency_key"])
        if name == "go.travel.order.get":
            return await self.gateway.order(ctx, arguments["order_id"])
        raise ValueError("MCP_TOOL_NOT_ALLOWED")

    async def structured_call(self, ctx: AgentContext, name: str, arguments: dict) -> dict:
        return asdict(await self.call_tool(ctx, name, arguments))
