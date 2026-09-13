from __future__ import annotations
from dataclasses import asdict
from typing import Callable
from fastapi import APIRouter,Depends,Header,HTTPException
from pydantic import BaseModel,Field
from .contracts import (AgentContext,CommitRequest,OfferRequest,PaymentRequest,ReserveRequest,LifecycleQuoteRequest,LifecycleExecuteRequest,ExpireRequest)
from .service import AgentTransactionGateway

class OfferBody(BaseModel): product_type:str=Field(min_length=1);search:dict
class ReserveBody(BaseModel): offer_id:str=Field(min_length=1);quote_hash:str=Field(min_length=1);search:dict=Field(default_factory=dict);booking:dict=Field(default_factory=dict);idempotency_key:str=Field(min_length=1)
class PaymentBody(BaseModel): reserve_id:str=Field(min_length=1);expected_total_minor:int=Field(gt=0);currency:str=Field(min_length=3,max_length=3);payment_method_id:str=Field(min_length=1);idempotency_key:str=Field(min_length=1)
class CommitBody(BaseModel): reserve_id:str=Field(min_length=1);payment_truth_id:str=Field(min_length=1);idempotency_key:str=Field(min_length=1)
class ReleaseBody(BaseModel): idempotency_key:str=Field(min_length=1)
class ExpireBody(BaseModel): idempotency_key:str=Field(min_length=1)
class LifecycleQuoteBody(BaseModel): action:str=Field(min_length=1);changes:dict=Field(default_factory=dict);idempotency_key:str=Field(min_length=1)
class LifecycleExecuteBody(BaseModel): action:str=Field(min_length=1);quote_id:str|None=None;quote_hash:str=Field(min_length=1);changes:dict=Field(default_factory=dict);payment_method_id:str|None=None;idempotency_key:str=Field(min_length=1)
AgentAuthorizer=Callable[[str,str,str,str,str],AgentContext]

def build_agent_router(gateway:AgentTransactionGateway,authorize:AgentAuthorizer)->APIRouter:
    router=APIRouter(prefix='/v1/agent',tags=['agent-transaction-gateway'])
    def principal(authorization:str=Header(...,alias='Authorization'),x_go_agent_id:str=Header(...,alias='X-GO-Agent-ID'),x_go_request_id:str=Header(...,alias='X-GO-Request-ID'),x_go_trace_id:str=Header(...,alias='X-GO-Trace-ID'),x_go_purpose:str=Header(...,alias='X-GO-Purpose')):
        try:return authorize(authorization,x_go_agent_id,x_go_request_id,x_go_trace_id,x_go_purpose)
        except PermissionError as exc:raise HTTPException(status_code=403,detail=str(exc)) from exc
        except ValueError as exc:raise HTTPException(status_code=401,detail=str(exc)) from exc
    async def invoke(fn):
        try:return asdict(await fn())
        except PermissionError as exc:raise HTTPException(status_code=403,detail=str(exc)) from exc
        except ValueError as exc:raise HTTPException(status_code=409,detail=str(exc)) from exc
    @router.post('/offers')
    async def offers(body:OfferBody,ctx:AgentContext=Depends(principal)):return await invoke(lambda:gateway.offers(ctx,OfferRequest(body.product_type,body.search)))
    @router.post('/reserves')
    async def reserve(body:ReserveBody,ctx:AgentContext=Depends(principal)):return await invoke(lambda:gateway.reserve(ctx,ReserveRequest(body.offer_id,body.quote_hash,body.search,body.booking,body.idempotency_key)))
    @router.post('/payments')
    async def payment(body:PaymentBody,ctx:AgentContext=Depends(principal)):return await invoke(lambda:gateway.payment(ctx,PaymentRequest(body.reserve_id,body.expected_total_minor,body.currency.upper(),body.payment_method_id,body.idempotency_key)))
    @router.post('/commits')
    async def commit(body:CommitBody,ctx:AgentContext=Depends(principal)):return await invoke(lambda:gateway.commit(ctx,CommitRequest(body.reserve_id,body.payment_truth_id,body.idempotency_key)))
    @router.post('/reserves/{reserve_id}/release')
    async def release(reserve_id:str,body:ReleaseBody,ctx:AgentContext=Depends(principal)):return await invoke(lambda:gateway.release(ctx,reserve_id,body.idempotency_key))
    @router.post('/reserves/{reserve_id}/expire')
    async def expire(reserve_id:str,body:ExpireBody,ctx:AgentContext=Depends(principal)):return await invoke(lambda:gateway.expire(ctx,ExpireRequest(reserve_id,body.idempotency_key)))
    @router.post('/orders/{order_id}/lifecycle/quote')
    async def lifecycle_quote(order_id:str,body:LifecycleQuoteBody,ctx:AgentContext=Depends(principal)):return await invoke(lambda:gateway.lifecycle_quote(ctx,LifecycleQuoteRequest(order_id,body.action,body.changes,body.idempotency_key)))
    @router.post('/orders/{order_id}/lifecycle/execute')
    async def lifecycle_execute(order_id:str,body:LifecycleExecuteBody,ctx:AgentContext=Depends(principal)):return await invoke(lambda:gateway.lifecycle_execute(ctx,LifecycleExecuteRequest(order_id,body.action,body.quote_id,body.quote_hash,body.changes,body.payment_method_id,body.idempotency_key)))
    @router.get('/orders/{order_id}')
    async def order(order_id:str,ctx:AgentContext=Depends(principal)):return await invoke(lambda:gateway.order(ctx,order_id))
    return router
