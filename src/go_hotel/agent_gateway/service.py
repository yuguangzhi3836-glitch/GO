from __future__ import annotations

from dataclasses import asdict
from typing import Protocol

from .contracts import (
    AgentContext,
    AgentEnvelope,
    CommitRequest,
    OfferRequest,
    ReserveRequest,
)


class TransactionCore(Protocol):
    def find_offers(self, ctx: AgentContext, req: OfferRequest): ...
    def reserve(self, ctx: AgentContext, req: ReserveRequest): ...
    def commit(self, ctx: AgentContext, req: CommitRequest): ...
    def release(self, ctx: AgentContext, reserve_id: str, idempotency_key: str): ...
    def get_order(self, ctx: AgentContext, order_id: str): ...


class AgentTransactionGateway:
    """Single protocol-neutral gateway into GO's deterministic transaction core.

    This layer must never own inventory, payment, order truth, or supplier truth.
    It may authenticate/authorize, normalize protocol payloads, call the core,
    and serialize deterministic results only.
    """

    def __init__(self, core: TransactionCore):
        self.core = core

    def offers(self, ctx: AgentContext, req: OfferRequest) -> AgentEnvelope:
        ctx.require("offers:read")
        result = self.core.find_offers(ctx, req)
        return AgentEnvelope(
            data={"items": [asdict(x) for x in result]},
            request_id=ctx.request_id,
            trace_id=ctx.trace_id,
        )

    def reserve(self, ctx: AgentContext, req: ReserveRequest) -> AgentEnvelope:
        ctx.require("reserve:write")
        if not req.idempotency_key:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        reservation = self.core.reserve(ctx, req)
        return AgentEnvelope(
            data=asdict(reservation),
            request_id=ctx.request_id,
            trace_id=ctx.trace_id,
        )

    def commit(self, ctx: AgentContext, req: CommitRequest) -> AgentEnvelope:
        ctx.require("commit:write")
        if not req.idempotency_key:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        if not req.payment_intent_id:
            raise ValueError("PAYMENT_INTENT_REQUIRED")
        order = self.core.commit(ctx, req)
        return AgentEnvelope(
            data=asdict(order),
            request_id=ctx.request_id,
            trace_id=ctx.trace_id,
        )

    def release(self, ctx: AgentContext, reserve_id: str, idempotency_key: str) -> AgentEnvelope:
        ctx.require("reserve:write")
        if not idempotency_key:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        result = self.core.release(ctx, reserve_id, idempotency_key)
        payload = asdict(result) if hasattr(result, "__dataclass_fields__") else result
        return AgentEnvelope(data=payload, request_id=ctx.request_id, trace_id=ctx.trace_id)

    def order(self, ctx: AgentContext, order_id: str) -> AgentEnvelope:
        ctx.require("orders:read")
        result = self.core.get_order(ctx, order_id)
        payload = asdict(result) if hasattr(result, "__dataclass_fields__") else result
        return AgentEnvelope(data=payload, request_id=ctx.request_id, trace_id=ctx.trace_id)
