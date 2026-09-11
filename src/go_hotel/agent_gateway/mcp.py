from __future__ import annotations
from dataclasses import asdict
from .contracts import (CommitRequest,OfferRequest,PaymentRequest,ReserveRequest,LifecycleQuoteRequest,LifecycleExecuteRequest,ExpireRequest)
MCP_PROTOCOL_VERSION='2026-07-28'
def _schema(properties,required):return {'type':'object','properties':properties,'required':required,'additionalProperties':False}
TOOLS=(
 {'name':'go.travel.offer.search','description':'Search machine-executable GO travel offers.','inputSchema':_schema({'product_type':{'type':'string'},'search':{'type':'object'}},['product_type','search'])},
 {'name':'go.travel.reserve','description':'Reserve an accepted quote through GO native transaction core.','inputSchema':_schema({'offer_id':{'type':'string'},'quote_hash':{'type':'string'},'search':{'type':'object'},'booking':{'type':'object'},'idempotency_key':{'type':'string'}},['offer_id','quote_hash','search','booking','idempotency_key'])},
 {'name':'go.travel.payment.prepare','description':'Create authoritative GO payment truth.','inputSchema':_schema({'reserve_id':{'type':'string'},'expected_total_minor':{'type':'integer','minimum':1},'currency':{'type':'string'},'payment_method_id':{'type':'string'},'idempotency_key':{'type':'string'}},['reserve_id','expected_total_minor','currency','payment_method_id','idempotency_key'])},
 {'name':'go.travel.commit','description':'Commit only against matching payment truth.','inputSchema':_schema({'reserve_id':{'type':'string'},'payment_truth_id':{'type':'string'},'idempotency_key':{'type':'string'}},['reserve_id','payment_truth_id','idempotency_key'])},
 {'name':'go.travel.reserve.release','description':'Release an unpaid reservation through its native path.','inputSchema':_schema({'reserve_id':{'type':'string'},'idempotency_key':{'type':'string'}},['reserve_id','idempotency_key'])},
 {'name':'go.travel.reserve.expire','description':'Apply native unpaid expiry; never force an early expiry.','inputSchema':_schema({'reserve_id':{'type':'string'},'idempotency_key':{'type':'string'}},['reserve_id','idempotency_key'])},
 {'name':'go.travel.lifecycle.quote','description':'Quote CANCEL, CHANGE or REFUND from current order truth.','inputSchema':_schema({'order_id':{'type':'string'},'action':{'type':'string'},'changes':{'type':'object'},'idempotency_key':{'type':'string'}},['order_id','action','changes','idempotency_key'])},
 {'name':'go.travel.lifecycle.execute','description':'Execute an accepted lifecycle quote through native after-sales truth.','inputSchema':_schema({'order_id':{'type':'string'},'action':{'type':'string'},'quote_id':{'type':['string','null']},'quote_hash':{'type':'string'},'changes':{'type':'object'},'payment_method_id':{'type':['string','null']},'idempotency_key':{'type':'string'}},['order_id','action','quote_hash','changes','idempotency_key'])},
 {'name':'go.travel.order.get','description':'Read deterministic GO order truth.','inputSchema':_schema({'order_id':{'type':'string'}},['order_id'])},
)
class MCPAdapter:
 def __init__(self,gateway):self.gateway=gateway
 def list_tools(self):return {'protocolVersion':MCP_PROTOCOL_VERSION,'tools':list(TOOLS)}
 async def call_tool(self,ctx,name,a):
  if name=='go.travel.offer.search':return await self.gateway.offers(ctx,OfferRequest(a['product_type'],a['search']))
  if name=='go.travel.reserve':return await self.gateway.reserve(ctx,ReserveRequest(a['offer_id'],a['quote_hash'],a.get('search') or {},a.get('booking') or {},a['idempotency_key']))
  if name=='go.travel.payment.prepare':return await self.gateway.payment(ctx,PaymentRequest(a['reserve_id'],int(a['expected_total_minor']),a['currency'].upper(),a['payment_method_id'],a['idempotency_key']))
  if name=='go.travel.commit':return await self.gateway.commit(ctx,CommitRequest(a['reserve_id'],a['payment_truth_id'],a['idempotency_key']))
  if name=='go.travel.reserve.release':return await self.gateway.release(ctx,a['reserve_id'],a['idempotency_key'])
  if name=='go.travel.reserve.expire':return await self.gateway.expire(ctx,ExpireRequest(a['reserve_id'],a['idempotency_key']))
  if name=='go.travel.lifecycle.quote':return await self.gateway.lifecycle_quote(ctx,LifecycleQuoteRequest(a['order_id'],a['action'],a.get('changes') or {},a['idempotency_key']))
  if name=='go.travel.lifecycle.execute':return await self.gateway.lifecycle_execute(ctx,LifecycleExecuteRequest(a['order_id'],a['action'],a.get('quote_id'),a['quote_hash'],a.get('changes') or {},a.get('payment_method_id'),a['idempotency_key']))
  if name=='go.travel.order.get':return await self.gateway.order(ctx,a['order_id'])
  raise ValueError('MCP_TOOL_NOT_ALLOWED')
 async def structured_call(self,ctx,name,a):return asdict(await self.call_tool(ctx,name,a))
