from dataclasses import replace

import pytest

from go_hotel.agent_gateway.a2a import A2AAdapter
from go_hotel.agent_gateway.contracts import AgentContext, AgentProtocol, CommitRequest, Offer, OfferRequest, Order, Reservation, ReserveRequest, SupplyRoute
from go_hotel.agent_gateway.mcp import MCPAdapter
from go_hotel.agent_gateway.service import AgentTransactionGateway


class FakeCore:
    def __init__(self): self.calls=[]
    def find_offers(self, ctx, req):
        self.calls.append(('offers', req))
        return [Offer('off_1','hotel_1','room_1',SupplyRoute.OFFICIAL_DIRECT,103600,'CNY','2026-09-11T08:00:00+08:00','AVAILABLE','183992',True,{'refundable':True},{'source':'OFFICIAL_DIRECT'})]
    def reserve(self, ctx, req):
        self.calls.append(('reserve', req))
        return Reservation('res_1',req.offer_id,'RESERVED','2026-09-11T08:00:00+08:00','183993',103600,'CNY')
    def commit(self, ctx, req):
        self.calls.append(('commit', req))
        return Order('ord_1',req.reserve_id,'CONFIRMED','H123','SUCCEEDED','184000')
    def release(self, ctx, reserve_id, idempotency_key):
        self.calls.append(('release', reserve_id, idempotency_key)); return {'reserve_id':reserve_id,'status':'RELEASED'}
    def get_order(self, ctx, order_id):
        self.calls.append(('order', order_id)); return {'order_id':order_id,'status':'CONFIRMED'}


def ctx(scopes):
    return AgentContext('req_1','trace_1','agent_test',AgentProtocol.REST,'book-travel',frozenset(scopes),'trav_1')


def test_offer_reserve_commit_closed_loop_uses_one_core():
    core=FakeCore(); gw=AgentTransactionGateway(core)
    c=ctx({'offers:read','reserve:write','commit:write','orders:read'})
    offers=gw.offers(c,OfferRequest('HOTEL',{'destination':'Fuzhou'}))
    assert offers.authority=='GO_DETERMINISTIC_CORE'
    assert offers.data['items'][0]['supply_route']==SupplyRoute.OFFICIAL_DIRECT
    reservation=gw.reserve(c,ReserveRequest('off_1','idem-r-1'))
    assert reservation.data['status']=='RESERVED'
    order=gw.commit(c,CommitRequest('res_1','pi_1','idem-c-1'))
    assert order.data['status']=='CONFIRMED'
    assert [x[0] for x in core.calls]==['offers','reserve','commit']


def test_mutations_fail_closed_without_scope_or_idempotency():
    gw=AgentTransactionGateway(FakeCore())
    with pytest.raises(PermissionError): gw.reserve(ctx(set()),ReserveRequest('off_1','idem'))
    with pytest.raises(ValueError,match='IDEMPOTENCY_KEY_REQUIRED'): gw.reserve(ctx({'reserve:write'}),ReserveRequest('off_1',''))
    with pytest.raises(ValueError,match='PAYMENT_INTENT_REQUIRED'): gw.commit(ctx({'commit:write'}),CommitRequest('res_1','','idem'))


def test_mcp_and_a2a_expose_same_transaction_surface():
    gw=AgentTransactionGateway(FakeCore())
    mcp=MCPAdapter(gw); a2a=A2AAdapter(gw)
    assert {x['name'] for x in mcp.list_tools()['tools']}=={'go.travel.offer.search','go.travel.reserve','go.travel.commit','go.travel.reserve.release','go.travel.order.get'}
    assert {x['id'] for x in a2a.agent_card()['skills']}=={'offer.search','reserve','commit','reserve.release','order.get'}
