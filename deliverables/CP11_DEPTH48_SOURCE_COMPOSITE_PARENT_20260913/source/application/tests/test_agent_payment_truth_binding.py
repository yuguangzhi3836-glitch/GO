import asyncio
import pytest
from go_hotel.agent_gateway.canonical_core import GoTransactionCore
from go_hotel.agent_gateway.contracts import AgentContext,AgentProtocol,CommitRequest,OfferRequest,PaymentRequest,ReserveRequest
from go_hotel.agent_gateway.service import AgentTransactionGateway

def run(x):return asyncio.run(x)

def test_payment_truth_cannot_be_swapped_or_forged():
    ctx=AgentContext('r','t','agent',AgentProtocol.MCP,'book-travel',frozenset({'offers:read','reserve:write','payments:write','commit:write'}),'traveler')
    gateway=AgentTransactionGateway(GoTransactionCore())
    search={'origin':'SHA','destination':'PEK','departure_date':'2026-10-06','currency':'CNY','adults':1}
    offer=run(gateway.offers(ctx,OfferRequest('FLIGHT',search))).data['items'][0]
    reservation=run(gateway.reserve(ctx,ReserveRequest(offer['offer_id'],offer['quote_hash'],search,{'passengers':[{'full_name':'Agent Traveler','type':'ADT'}]},'bind-r'))).data
    payment=run(gateway.payment(ctx,PaymentRequest(reservation['reserve_id'],reservation['total_minor'],reservation['currency'],'pm-bind','bind-p'))).data
    with pytest.raises(ValueError,match='PAYMENT_TRUTH_ORDER_MISMATCH'):
        run(gateway.commit(ctx,CommitRequest(reservation['reserve_id'],payment['payment_truth_id']+'-forged','bind-c')))
