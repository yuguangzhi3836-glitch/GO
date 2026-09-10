from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .contracts import AgentContext, CommitRequest, OfferRequest, ReserveRequest
from .service import AgentTransactionGateway


class OfferBody(BaseModel):
    product_type: str = Field(min_length=1)
    search: dict


class ReserveBody(BaseModel):
    offer_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class ReleaseBody(BaseModel):
    idempotency_key: str = Field(min_length=1)


class CommitBody(BaseModel):
    reserve_id: str = Field(min_length=1)
    payment_intent_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


AgentAuthorizer = Callable[[str, str, str, str, str], AgentContext]


def build_agent_router(gateway: AgentTransactionGateway, authorize: AgentAuthorizer) -> APIRouter:
    router = APIRouter(prefix="/v1/agent", tags=["agent-transaction-gateway"])

    def principal(
        authorization: str = Header(..., alias="Authorization"),
        x_go_agent_id: str = Header(..., alias="X-GO-Agent-ID"),
        x_go_request_id: str = Header(..., alias="X-GO-Request-ID"),
        x_go_trace_id: str = Header(..., alias="X-GO-Trace-ID"),
        x_go_purpose: str = Header(..., alias="X-GO-Purpose"),
    ) -> AgentContext:
        try:
            return authorize(authorization, x_go_agent_id, x_go_request_id, x_go_trace_id, x_go_purpose)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def invoke(fn):
        try:
            envelope = fn()
            return asdict(envelope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/offers")
    def offers(body: OfferBody, ctx: AgentContext = Depends(principal)):
        return invoke(lambda: gateway.offers(ctx, OfferRequest(body.product_type, body.search)))

    @router.post("/reserves")
    def reserve(body: ReserveBody, ctx: AgentContext = Depends(principal)):
        return invoke(lambda: gateway.reserve(ctx, ReserveRequest(body.offer_id, body.idempotency_key)))

    @router.post("/commits")
    def commit(body: CommitBody, ctx: AgentContext = Depends(principal)):
        return invoke(lambda: gateway.commit(ctx, CommitRequest(body.reserve_id, body.payment_intent_id, body.idempotency_key)))

    @router.post("/reserves/{reserve_id}/release")
    def release(reserve_id: str, body: ReleaseBody, ctx: AgentContext = Depends(principal)):
        return invoke(lambda: gateway.release(ctx, reserve_id, body.idempotency_key))

    @router.get("/orders/{order_id}")
    def order(order_id: str, ctx: AgentContext = Depends(principal)):
        return invoke(lambda: gateway.order(ctx, order_id))

    return router
