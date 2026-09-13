from __future__ import annotations
from dataclasses import asdict
from typing import Protocol
from .contracts import (AgentContext,AgentEnvelope,CommitRequest,OfferRequest,PaymentRequest,ReserveRequest,
    LifecycleQuoteRequest,LifecycleExecuteRequest,ExpireRequest)

class TransactionCore(Protocol):
    async def find_offers(self,ctx,req): ...
    async def reserve(self,ctx,req): ...
    async def prepare_payment(self,ctx,req): ...
    async def commit(self,ctx,req): ...
    async def release(self,ctx,reserve_id,idempotency_key): ...
    async def expire(self,ctx,req): ...
    async def lifecycle_quote(self,ctx,req): ...
    async def lifecycle_execute(self,ctx,req): ...
    async def get_order(self,ctx,order_id): ...

class AgentTransactionGateway:
    """Protocol-neutral authorization layer over GO deterministic transaction truth."""
    def __init__(self,core:TransactionCore): self.core=core
    async def offers(self,ctx:AgentContext,req:OfferRequest)->AgentEnvelope:
        ctx.require('offers:read'); result=await self.core.find_offers(ctx,req)
        return AgentEnvelope({'items':[asdict(x) for x in result]},ctx.request_id,ctx.trace_id)
    async def reserve(self,ctx:AgentContext,req:ReserveRequest)->AgentEnvelope:
        ctx.require('reserve:write');ctx.require_traveler()
        if not req.idempotency_key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
        if not req.quote_hash:raise ValueError('ACCEPTED_QUOTE_HASH_REQUIRED')
        x=await self.core.reserve(ctx,req);return AgentEnvelope(asdict(x),ctx.request_id,ctx.trace_id)
    async def payment(self,ctx:AgentContext,req:PaymentRequest)->AgentEnvelope:
        ctx.require('payments:write');ctx.require_traveler()
        if not req.idempotency_key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
        if not req.payment_method_id:raise ValueError('PAYMENT_METHOD_REQUIRED')
        x=await self.core.prepare_payment(ctx,req);return AgentEnvelope(asdict(x),ctx.request_id,ctx.trace_id)
    async def commit(self,ctx:AgentContext,req:CommitRequest)->AgentEnvelope:
        ctx.require('commit:write');ctx.require_traveler()
        if not req.idempotency_key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
        if not req.payment_truth_id:raise ValueError('PAYMENT_TRUTH_REQUIRED')
        x=await self.core.commit(ctx,req);return AgentEnvelope(asdict(x),ctx.request_id,ctx.trace_id)
    async def release(self,ctx:AgentContext,reserve_id:str,idempotency_key:str)->AgentEnvelope:
        ctx.require('reserve:write');ctx.require_traveler()
        if not idempotency_key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
        x=await self.core.release(ctx,reserve_id,idempotency_key);p=asdict(x) if hasattr(x,'__dataclass_fields__') else x
        return AgentEnvelope(p,ctx.request_id,ctx.trace_id)
    async def expire(self,ctx:AgentContext,req:ExpireRequest)->AgentEnvelope:
        ctx.require('reserve:write');ctx.require_traveler()
        if not req.idempotency_key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
        return AgentEnvelope(await self.core.expire(ctx,req),ctx.request_id,ctx.trace_id)
    async def lifecycle_quote(self,ctx:AgentContext,req:LifecycleQuoteRequest)->AgentEnvelope:
        ctx.require('aftersales:write');ctx.require_traveler()
        if not req.idempotency_key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
        return AgentEnvelope(await self.core.lifecycle_quote(ctx,req),ctx.request_id,ctx.trace_id)
    async def lifecycle_execute(self,ctx:AgentContext,req:LifecycleExecuteRequest)->AgentEnvelope:
        ctx.require('aftersales:write');ctx.require_traveler()
        if not req.idempotency_key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
        return AgentEnvelope(await self.core.lifecycle_execute(ctx,req),ctx.request_id,ctx.trace_id)
    async def order(self,ctx:AgentContext,order_id:str)->AgentEnvelope:
        ctx.require('orders:read');ctx.require_traveler();x=await self.core.get_order(ctx,order_id)
        p=asdict(x) if hasattr(x,'__dataclass_fields__') else x
        return AgentEnvelope(p,ctx.request_id,ctx.trace_id)
