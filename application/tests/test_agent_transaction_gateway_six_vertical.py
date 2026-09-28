from ride_cancellation_fixture import reserve_agent
import asyncio,time
import pytest
from fastapi.testclient import TestClient

from go_hotel.agent_gateway.canonical_core import GoTransactionCore
from go_hotel.agent_gateway.contracts import AgentContext,AgentProtocol,CommitRequest,OfferRequest,PaymentRequest,ReserveRequest
from go_hotel.agent_gateway.service import AgentTransactionGateway
from go_hotel.security.crypto import encode_jwt

SCOPES=frozenset({'offers:read','reserve:write','payments:write','commit:write','orders:read'})
def ctx():return AgentContext('r','t','agent',AgentProtocol.REST,'book-travel',SCOPES,'agent-traveler')
def run(x):return asyncio.run(x)

CASES=[
 ('FLIGHT',{'origin':'SHA','destination':'PEK','departure_date':'2026-10-03','currency':'CNY','adults':1},{'passengers':[{'full_name':'Agent Traveler','type':'ADT'}]}),
 ('RAIL',{'origin_station':'SHA','destination_station':'HGH','travel_date':'2026-10-03','currency':'CNY'},{'passengers':[{'full_name':'Agent Traveler','type':'ADT'}],'quantity':1}),
 ('RIDE',{'pickup':'PVG','dropoff':'Hotel','pickup_at':'2026-10-03T10:00:00','currency':'CNY'},{'passengers':[{'full_name':'Agent Traveler'}]}),
 ('RENTAL',{'pickup_location':'PVG','return_location':'PVG','pickup_at':'2026-10-03T10:00:00','return_at':'2026-10-04T10:00:00','currency':'CNY'},{'drivers':[{'full_name':'Agent Traveler'}]}),
 ('ATTRACTION',{'destination':'东京','visit_date':'2026-10-03','currency':'CNY'},{'attendees':[{'full_name':'Agent Traveler','type':'ADT'}],'quantity':1}),
]

@pytest.mark.parametrize('vertical,search,booking',CASES)
def test_non_hotel_verticals_reach_native_payment_and_order_truth(vertical,search,booking):
    gateway=AgentTransactionGateway(GoTransactionCore());c=ctx()
    if vertical=='RIDE':
        reservation=reserve_agent(gateway,c,vertical,search,booking,'reserve-'+vertical)
    else:
        offer=run(gateway.offers(c,OfferRequest(vertical,search))).data['items'][0]
        reservation=run(gateway.reserve(c,ReserveRequest(offer['offer_id'],offer['quote_hash'],search,booking,'reserve-'+vertical))).data
    payment=run(gateway.payment(c,PaymentRequest(reservation['reserve_id'],reservation['total_minor'],reservation['currency'],'pm-agent','payment-'+vertical))).data
    assert payment['state']=='SUCCEEDED' and payment['captured'] is True
    order=run(gateway.commit(c,CommitRequest(reservation['reserve_id'],payment['payment_truth_id'],'commit-'+vertical))).data
    assert order['status'] in {'TICKETED','CONFIRMED'}
    assert order['payment_state']=='SUCCEEDED'


def test_hotel_preserves_authorize_then_supplier_confirm_then_capture_semantics():
    gateway=AgentTransactionGateway(GoTransactionCore());c=ctx()
    search={'city_code':'TYO','check_in':'2026-10-03','check_out':'2026-10-04','currency':'CNY'}
    offer=run(gateway.offers(c,OfferRequest('HOTEL',search))).data['items'][0]
    reservation=run(gateway.reserve(c,ReserveRequest(offer['offer_id'],offer['quote_hash'],search,{'fare_confirmed':True,'simulation_fixture':True},'hotel-reserve'))).data
    payment=run(gateway.payment(c,PaymentRequest(reservation['reserve_id'],reservation['total_minor'],reservation['currency'],'pm-hotel','hotel-payment'))).data
    assert payment['state'] in {'AUTHORIZED','CAPTURED'}
    order=run(gateway.commit(c,CommitRequest(reservation['reserve_id'],payment['payment_truth_id'],'hotel-commit'))).data
    assert order['status']=='CONFIRMED'
    assert order['payment_state']=='CAPTURED'


def _token(protocol):
    now=int(time.time())
    return encode_jwt({'typ':'GO_AGENT_ACCESS','iss':'GO_COMMAND_CENTER','aud':'GO_AGENT_GATEWAY','sub':'agent1','agent_id':'agent1','protocol':protocol,'purposes':['book-travel','pay-travel'],'scopes':list(SCOPES),'traveler_ref':'agent-traveler','iat':now,'exp':now+600})

def _headers(protocol):
    return {'Authorization':'Bearer '+_token(protocol),'X-GO-Agent-ID':'agent1','X-GO-Request-ID':'runtime-r','X-GO-Trace-ID':'runtime-t','X-GO-Purpose':'book-travel'}

def test_full_go_app_installs_gateway_and_rejects_protocol_token_confusion():
    from go_hotel.main import app
    with TestClient(app) as client:
        assert client.get('/.well-known/agent-card.json').status_code==200
        body={'product_type':'FLIGHT','search':{'origin':'SHA','destination':'PEK','departure_date':'2026-10-05','currency':'CNY','adults':1}}
        ok=client.post('/v1/agent/offers',headers=_headers('REST'),json=body)
        assert ok.status_code==200 and ok.json()['authority']=='GO_DETERMINISTIC_CORE'
        bad=client.post('/v1/agent/offers',headers=_headers('A2A'),json=body)
        assert bad.status_code==403
