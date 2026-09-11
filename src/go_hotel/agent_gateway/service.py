from __future__ import annotations

from dataclasses import asdict
from typing import Protocol

from .contracts import (
    AgentContext,
    AgentEnvelope,
    CommitRequest,
    OfferRequest,
    PaymentRequest,
    ReserveRequest,
)


class TransactionCore(Protocol):
    async def find_offers(self, ctx: AgentContext, req: OfferRequest): ...
    async def reserve(self, ctx: AgentContext, req: ReserveRequest): ...
    async def prepare_payment(self, ctx: AgentContext, req: PaymentRequest): ...
    async def commit(self, ctx: AgentContext, req: CommitRequest): ...
    async def release(self, ctx: AgentContext, reserve_id: str, idempotency_key: str): ...
    async def get_order(self, ctx: AgentContext, order_id: str): ...


class AgentTransactionGateway:
    """One protocol-neutral entry to GO transaction truth.

    The gateway owns no inventory, payment, supplier or order truth. It only
    authorizes a purpose-bound agent request and delegates to the canonical core.
    """

    def __init__(self, core: TransactionCore):
        self.core = core

    async def offers(self, ctx: AgentContext, req: OfferRequest) -> AgentEnvelope:
        ctx.require("offers:read")
        result = await self.core.find_offers(ctx, req)
        return AgentEnvelope(
            data={"items": [asdict(x) for x in result]},
            request_id=ctx.request_id,
            trace_id=ctx.trace_id,
        )

    async def reserve(self, ctx: AgentContext, req: ReserveRequest) -> AgentEnvelope:
        ctx.require("reserve:write")
        ctx.require_traveler()
        if not req.idempotency_key:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        if not req.quote_hash:
            raise ValueError("ACCEPTED_QUOTE_HASH_REQUIRED")
        reservation = await self.core.reserve(ctx, req)
        return AgentEnvelope(data=asdict(reservation), request_id=ctx.request_id, trace_id=ctx.trace_id)

    async def payment(self, ctx: AgentContext, req: PaymentRequest) -> AgentEnvelope:
        ctx.require("payments:write")
        ctx.require_traveler()
        if not req.idempotency_key:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        if not req.payment_method_id:
            raise ValueError("PAYMENT_METHOD_REQUIRED")
        truth = await self.core.prepare_payment(ctx, req)
        return AgentEnvelope(data=asdict(truth), request_id=ctx.request_id, trace_id=ctx.trace_id)

    async def commit(self, ctx: AgentContext, req: CommitRequest) -> AgentEnvelope:
        ctx.require("commit:write")
        ctx.require_traveler()
        if not req.idempotency_key:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        if not req.payment_truth_id:
            raise ValueError("PAYMENT_TRUTH_REQUIRED")
        order = await self.core.commit(ctx, req)
        return AgentEnvelope(data=asdict(order), request_id=ctx.request_id, trace_id=ctx.trace_id)

    async def release(self, ctx: AgentContext, reserve_id: str, idempotency_key: str) -> AgentEnvelope:
        ctx.require("reserve:write")
        ctx.require_traveler()
        if not idempotency_key:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        result = await self.core.release(ctx, reserve_id, idempotency_key)
        payload = asdict(result) if hasattr(result, "__dataclass_fields__") else result
        return AgentEnvelope(data=payload, request_id=ctx.request_id, trace_id=ctx.trace_id)

    async def order(self, ctx: AgentContext, order_id: str) -> AgentEnvelope:
        ctx.require("orders:read")
        ctx.require_traveler()
        result = await self.core.get_order(ctx, order_id)
        payload = asdict(result) if hasattr(result, "__dataclass_fields__") else result
        return AgentEnvelope(data=payload, request_id=ctx.request_id, trace_id=ctx.trace_id)
