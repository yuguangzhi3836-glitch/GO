from __future__ import annotations
from dataclasses import asdict
from .contracts import (CommitRequest,OfferRequest,PaymentRequest,ReserveRequest,LifecycleQuoteRequest,LifecycleExecuteRequest,ExpireRequest)
A2A_PROTOCOL_VERSION='1.0'
GO_TRANSACTION_EXTENSION='urn:go:a2a:transaction-skill:v1'
SKILLS=[
 {'id':'offer.search','name':'Search Offers','description':'Search GO machine-executable travel offers.','tags':['travel','offer','official-direct']},
 {'id':'reserve','name':'Reserve Offer','description':'Reserve an accepted GO quote using native transaction truth.','tags':['travel','inventory','transaction']},
 {'id':'payment.prepare','name':'Prepare Payment Truth','description':'Establish authoritative payment truth.','tags':['travel','payment','truth']},
 {'id':'commit','name':'Commit Reservation','description':'Commit only against matching payment truth.','tags':['travel','payment','order']},
 {'id':'reserve.release','name':'Release Reservation','description':'Release an unpaid reservation through its native path.','tags':['travel','inventory','lifecycle']},
 {'id':'reserve.expire','name':'Expire Reservation','description':'Apply native unpaid expiry without forcing it early.','tags':['travel','inventory','lifecycle']},
 {'id':'lifecycle.quote','name':'Quote After-sales','description':'Quote cancel, change or refund from current order truth.','tags':['travel','aftersales','quote']},
 {'id':'lifecycle.execute','name':'Execute After-sales','description':'Execute an accepted cancel, change or refund quote.','tags':['travel','aftersales','truth']},
 {'id':'order.get','name':'Get Order Truth','description':'Read deterministic GO order truth.','tags':['travel','order','truth']},
]
def build_agent_card(interface_url):
 return {'name':'GO Travel Transaction Agent','description':'Deterministic GO transaction and lifecycle capabilities.','supportedInterfaces':[{'url':interface_url,'protocolBinding':'JSONRPC','protocolVersion':A2A_PROTOCOL_VERSION}],'version':'1.2.0','capabilities':{'streaming':False,'pushNotifications':False,'extendedAgentCard':False,'extensions':[{'uri':GO_TRANSACTION_EXTENSION,'description':'Carries a GO transaction skill id and structured payload in SendMessage metadata.','required':True}]},'defaultInputModes':['application/json'],'defaultOutputModes':['application/json'],'skills':SKILLS}
class A2AAdapter:
 def __init__(self,gateway):self.gateway=gateway
 def agent_card(self,interface_url='https://agent.invalid/a2a/v1'):return build_agent_card(interface_url)
 async def execute(self,ctx,skill_id,p):
  if skill_id=='offer.search':return await self.gateway.offers(ctx,OfferRequest(p['product_type'],p['search']))
  if skill_id=='reserve':return await self.gateway.reserve(ctx,ReserveRequest(p['offer_id'],p['quote_hash'],p.get('search') or {},p.get('booking') or {},p['idempotency_key']))
  if skill_id=='payment.prepare':return await self.gateway.payment(ctx,PaymentRequest(p['reserve_id'],int(p['expected_total_minor']),p['currency'].upper(),p['payment_method_id'],p['idempotency_key']))
  if skill_id=='commit':return await self.gateway.commit(ctx,CommitRequest(p['reserve_id'],p['payment_truth_id'],p['idempotency_key']))
  if skill_id=='reserve.release':return await self.gateway.release(ctx,p['reserve_id'],p['idempotency_key'])
  if skill_id=='reserve.expire':return await self.gateway.expire(ctx,ExpireRequest(p['reserve_id'],p['idempotency_key']))
  if skill_id=='lifecycle.quote':return await self.gateway.lifecycle_quote(ctx,LifecycleQuoteRequest(p['order_id'],p['action'],p.get('changes') or {},p['idempotency_key']))
  if skill_id=='lifecycle.execute':return await self.gateway.lifecycle_execute(ctx,LifecycleExecuteRequest(p['order_id'],p['action'],p.get('quote_id'),p['quote_hash'],p.get('changes') or {},p.get('payment_method_id'),p['idempotency_key']))
  if skill_id=='order.get':return await self.gateway.order(ctx,p['order_id'])
  raise ValueError('A2A_SKILL_NOT_ALLOWED')
 async def structured_execute(self,ctx,skill_id,p):return asdict(await self.execute(ctx,skill_id,p))
