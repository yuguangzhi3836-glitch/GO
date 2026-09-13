import asyncio
import pytest
from go_hotel.agent_gateway.a2a import A2AAdapter,build_agent_card
from go_hotel.agent_gateway.contracts import AgentContext,AgentProtocol,CommitRequest,Offer,OfferRequest,Order,PaymentRequest,PaymentTruth,Reservation,ReserveRequest,SupplyRoute
from go_hotel.agent_gateway.mcp import MCPAdapter,MCP_PROTOCOL_VERSION
from go_hotel.agent_gateway.service import AgentTransactionGateway

class FakeCore:
 def __init__(self):self.calls=[]
 async def find_offers(self,ctx,req):self.calls.append(('offers',req));return [Offer('FLIGHT:off_1','FLIGHT','airline_1','MU5101',SupplyRoute.OFFICIAL_DIRECT,103600,'CNY',None,'AVAILABLE','quote-1',True,{},'quote-1',{'origin':'SHA'},{'source':'OFFICIAL_DIRECT'})]
 async def reserve(self,ctx,req):self.calls.append(('reserve',req));return Reservation('FLIGHT:ord_1',req.offer_id,'FLIGHT','PAYMENT_PENDING',None,req.quote_hash,103600,'CNY','FLIGHT:ord_1',{})
 async def prepare_payment(self,ctx,req):self.calls.append(('payment',req));return PaymentTruth('pi_1',req.reserve_id,'FLIGHT','SUCCEEDED',103600,'CNY',True,False,{})
 async def commit(self,ctx,req):self.calls.append(('commit',req));return Order(req.reserve_id,req.reserve_id,'FLIGHT','TICKETED','PNR1','SUCCEEDED','v1',103600,'CNY',{})
 async def release(self,ctx,reserve_id,idempotency_key):self.calls.append(('release',reserve_id,idempotency_key));return {'reserve_id':reserve_id,'status':'RELEASED'}
 async def get_order(self,ctx,order_id):self.calls.append(('order',order_id));return Order(order_id,order_id,'FLIGHT','TICKETED','PNR1','SUCCEEDED','v1',103600,'CNY',{})

def ctx(scopes):return AgentContext('req_1','trace_1','agent_test',AgentProtocol.MCP,'book-travel',frozenset(scopes),'trav_1')
def run(coro):return asyncio.run(coro)

def test_offer_reserve_payment_commit_closed_loop_uses_one_core():
 core=FakeCore();gw=AgentTransactionGateway(core);c=ctx({'offers:read','reserve:write','payments:write','commit:write','orders:read'})
 offers=run(gw.offers(c,OfferRequest('FLIGHT',{'origin':'SHA'})));assert offers.authority=='GO_DETERMINISTIC_CORE'
 reservation=run(gw.reserve(c,ReserveRequest('FLIGHT:off_1','quote-1',{'origin':'SHA'},{},'idem-r-1')))
 payment=run(gw.payment(c,PaymentRequest(reservation.data['reserve_id'],103600,'CNY','pm_1','idem-p-1')))
 order=run(gw.commit(c,CommitRequest(reservation.data['reserve_id'],payment.data['payment_truth_id'],'idem-c-1')))
 assert order.data['status']=='TICKETED';assert [x[0] for x in core.calls]==['offers','reserve','payment','commit']

def test_mutations_fail_closed_without_scope_traveler_or_idempotency():
 gw=AgentTransactionGateway(FakeCore())
 with pytest.raises(PermissionError):run(gw.reserve(ctx(set()),ReserveRequest('FLIGHT:o','q',{}, {},'idem')))
 no=AgentContext('r','t','a',AgentProtocol.MCP,'book',frozenset({'reserve:write'}),None)
 with pytest.raises(PermissionError,match='AGENT_TRAVELER_CONTEXT_REQUIRED'):run(gw.reserve(no,ReserveRequest('FLIGHT:o','q',{}, {},'idem')))
 with pytest.raises(ValueError,match='IDEMPOTENCY_KEY_REQUIRED'):run(gw.reserve(ctx({'reserve:write'}),ReserveRequest('FLIGHT:o','q',{}, {},'')))
 with pytest.raises(ValueError,match='PAYMENT_TRUTH_REQUIRED'):run(gw.commit(ctx({'commit:write'}),CommitRequest('FLIGHT:ord','','idem')))

def test_mcp_and_a2a_expose_same_transaction_lifecycle_surface():
 gw=AgentTransactionGateway(FakeCore());mcp=MCPAdapter(gw);a2a=A2AAdapter(gw)
 assert MCP_PROTOCOL_VERSION=='2026-07-28'
 assert {x['name'] for x in mcp.list_tools()['tools']}=={'go.travel.offer.search','go.travel.reserve','go.travel.payment.prepare','go.travel.commit','go.travel.reserve.release','go.travel.reserve.expire','go.travel.lifecycle.quote','go.travel.lifecycle.execute','go.travel.order.get'}
 card=build_agent_card('https://go.example/a2a/v1')
 assert card['supportedInterfaces']==[{'url':'https://go.example/a2a/v1','protocolBinding':'JSONRPC','protocolVersion':'1.0'}]
 assert {x['id'] for x in card['skills']}=={'offer.search','reserve','payment.prepare','commit','reserve.release','reserve.expire','lifecycle.quote','lifecycle.execute','order.get'}
