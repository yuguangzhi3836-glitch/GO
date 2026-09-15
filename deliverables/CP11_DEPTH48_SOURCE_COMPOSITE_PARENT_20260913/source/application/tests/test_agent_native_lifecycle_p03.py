import asyncio

import pytest

from go_hotel.agent_gateway.contracts import AgentContext, AgentProtocol, ExpireRequest, OfferRequest, ReserveRequest
from go_hotel.agent_gateway.lifecycle_core import GoTransactionCore
from go_hotel.agent_gateway.service import AgentTransactionGateway
from go_hotel.connectors.mock_hotel import connector
from go_hotel.db.models import VerticalPaymentDeadlineRow
from go_hotel.db.session import SessionLocal
from go_hotel.autonomy.durable import db_now_ms, digest
from go_hotel.services import vertical_reservation_expiry as expiry

SCOPES = frozenset({'offers:read','reserve:write','payments:write','commit:write','orders:read','aftersales:write'})
TRAVELER = 'p03-owner'

def ctx():
    return AgentContext('p03-r','p03-t','p03-agent',AgentProtocol.REST,'manage-travel',SCOPES,TRAVELER)

def run(x): return asyncio.run(x)

def reserve(gw, vertical, search, booking, key):
    c=ctx(); offer=run(gw.offers(c,OfferRequest(vertical,search))).data['items'][0]
    return run(gw.reserve(c,ReserveRequest(offer['offer_id'],offer['quote_hash'],search,booking,key))).data

def force_due(vertical, reserve_id):
    oid=reserve_id.split(':',1)[1]
    with SessionLocal.begin() as s:
        d=s.get(VerticalPaymentDeadlineRow,(vertical,oid))
        assert d is not None and d.state=='OPEN'
        d.expires_ms=db_now_ms(s)-1
        d.created_ms=d.expires_ms-expiry.HOLD_MS
        d.terms_hash=digest(expiry.terms(d))
    return oid


def test_hotel_hard_hold_release_is_connector_native_and_idempotent():
    connector.reset(); connector.prebook_hold_type='HARD'
    gw=AgentTransactionGateway(GoTransactionCore())
    r=reserve(gw,'HOTEL',{'city_code':'TYO','check_in':'2026-11-11','check_out':'2026-11-12','currency':'CNY'},
              {'fare_confirmed':True,'simulation_fixture':True},'hard-release-reserve')
    assert connector.release_hold_calls==0
    first=run(gw.release(ctx(),r['reserve_id'],'hard-release-key')).data
    second=run(gw.release(ctx(),r['reserve_id'],'hard-release-key')).data
    assert first==second
    assert first['state']=='RELEASED'
    assert first['order_truth']['status']=='CANCELLED'
    assert connector.release_hold_calls==1
    connector.reset()


def test_hotel_hard_hold_ambiguous_release_fails_closed_without_local_cancel():
    connector.reset(); connector.prebook_hold_type='HARD'; connector.ambiguous_release_hold=True
    gw=AgentTransactionGateway(GoTransactionCore())
    r=reserve(gw,'HOTEL',{'city_code':'TYO','check_in':'2026-11-13','check_out':'2026-11-14','currency':'CNY'},
              {'fare_confirmed':True,'simulation_fixture':True},'hard-unknown-reserve')
    with pytest.raises(ValueError,match='RECONCILIATION_REQUIRED'):
        run(gw.release(ctx(),r['reserve_id'],'hard-unknown-key'))
    truth=run(gw.order(ctx(),r['reserve_id'])).data
    assert truth['status']=='PAYMENT_PENDING'
    connector.reset()


@pytest.mark.parametrize('vertical,search,booking',[
    ('RIDE',{'pickup':'PVG','dropoff':'Hotel','pickup_at':'2026-11-15T10:00:00','currency':'CNY'}, {'passengers':[{'full_name':'A'}]}),
    ('RENTAL',{'pickup_location':'PVG','return_location':'PVG','pickup_at':'2026-11-16T10:00:00','return_at':'2026-11-18T10:00:00','currency':'CNY'}, {'drivers':[{'full_name':'A'}]}),
])
def test_mobility_unpaid_checkout_has_native_deadline_and_expires_without_fake_capacity(vertical,search,booking):
    gw=AgentTransactionGateway(GoTransactionCore())
    r=reserve(gw,vertical,search,booking,'mob-exp-'+vertical.lower())
    oid=r['reserve_id'].split(':',1)[1]
    with SessionLocal() as s:
        d=s.get(VerticalPaymentDeadlineRow,(vertical,oid))
        assert d is not None and d.state=='OPEN' and d.expires_ms>d.created_ms
    force_due(vertical,r['reserve_id'])
    out=run(gw.expire(ctx(),ExpireRequest(r['reserve_id'],'expire-'+vertical.lower()))).data
    assert out['state']=='EXPIRED'
    assert out['order_truth']['status']=='CANCELLED'
    evidence=out['order_truth']['evidence']['native'].get('evidence',[])
    event=next(x for x in reversed(evidence) if x.get('kind')=='UNPAID_RESERVATION_EXPIRED')
    assert event['payload']['capacity_released'] is False


def test_mobility_expiry_never_cancels_after_payment_intent_exists():
    gw=AgentTransactionGateway(GoTransactionCore())
    r=reserve(gw,'RIDE',{'pickup':'PVG','dropoff':'Hotel','pickup_at':'2026-11-19T10:00:00','currency':'CNY'},
              {'passengers':[{'full_name':'A'}]},'mob-race')
    oid=force_due('RIDE',r['reserve_id'])
    from go_hotel.services.omnichannel_payment import omnichannel_payment_service
    omnichannel_payment_service.create_intent({'business_type':'RIDE_ORDER','business_id':oid,'channel_priority':['LOCAL_MARKET']},'p03-race-intent',TRAVELER)
    out=run(gw.expire(ctx(),ExpireRequest(r['reserve_id'],'mob-race-expire'))).data
    assert out['state']=='UNCHANGED'
    assert out['order_truth']['status']=='PAYMENT_PENDING'
    with SessionLocal() as s:
        d=s.get(VerticalPaymentDeadlineRow,('RIDE',oid))
        assert d.state=='PAYMENT_STARTED'
