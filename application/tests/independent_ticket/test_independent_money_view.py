"""Independent money projection checks; no implementation modifications."""
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import PaymentOrderRootRow as Root
from go_hotel.flight.service import flight_service as flights
from go_hotel.flight import coupon_refunds as refunds
from tests.test_depth48_flight_changes import booked,consent
from tests.test_depth05_flight_parties import auth,create,pay
from tests.test_flight_journey_depth import day

def test_unpaid_and_change_authorization_do_not_invent_captured_money(client):
    headers=auth(client);order,_=create(client,headers)
    assert order['money_summary']=={'verified':True,'currency':'CNY','captured_minor':0,'refunded_minor':0,'net_minor':0,'has_pending':False}
    order=pay(client,headers,order);oid=order['order_id'];owner=order['account_id']
    quote=flights.change_quote(owner,oid,changes=[{'leg_index':0,'coupon_ids':[order['coupons'][0]['coupon_id']],'new_departure_date':day(12)}])
    flights.execute_change(owner,oid,quote['quote_id'],consent(quote))
    summary=flights.order(owner,oid)['money_summary']
    assert summary['verified'] and summary['captured_minor']==order['total_amount_minor']
    assert summary['net_minor']==order['total_amount_minor'] and summary['refunded_minor']==0

def test_money_summary_reads_committed_refund_before_coupon_finalize(client,monkeypatch):
    owner,order,_=booked(client);oid=order['order_id']
    quote=refunds.quote(owner,oid,[order['coupons'][0]['coupon_id']])
    confirmation={'quote_hash':quote['quote_hash'],'currency':quote['currency'],'expected_refund_amount_minor':quote['refund_amount_minor'],'confirmed':True}
    real=refunds.money.execute_refund_plan
    def crash(*a,**kw):real(*a,**kw);raise RuntimeError('INDEPENDENT_MONEY_COMMITTED')
    monkeypatch.setattr(refunds.money,'execute_refund_plan',crash)
    with pytest.raises(RuntimeError,match='INDEPENDENT_MONEY_COMMITTED'):refunds.execute(owner,oid,quote['refund_id'],confirmation)
    pending=flights.order(owner,oid)
    assert pending['status']=='REFUND_PENDING' and pending['refunded_amount_minor']==0
    assert pending['money_summary']['verified']
    assert pending['money_summary']['refunded_minor']==quote['refund_amount_minor']
    assert pending['money_summary']['net_minor']==order['total_amount_minor']-quote['refund_amount_minor']

def test_foreign_root_pointer_fails_closed(client):
    owner,order,_=booked(client)
    foreign_headers=auth(client,'independent-money-other@example.test')
    other,_=create(client,foreign_headers)
    response=client.post('/v1/consumer/checkout/FLIGHT/'+other['order_id'],headers={**foreign_headers,'Idempotency-Key':'independent-other-money'},json={'mode':'CONTRACT_SIMULATOR','currency':other['currency'],'expected_amount_minor':other['total_amount_minor']})
    assert response.status_code==200,response.text
    with SessionLocal.begin() as s:
        own=s.scalar(select(Root).where(Root.business_type=='FLIGHT_ORDER',Root.business_id==order['order_id']))
        foreign=s.scalar(select(Root).where(Root.business_type=='FLIGHT_ORDER',Root.business_id==other['order_id']))
        foreign_intent=foreign.payment_intent_id
        s.delete(foreign);s.flush()  # Remove unique root edge before replacing it with a corrupt foreign edge.
        own.payment_intent_id=foreign_intent
    summary=flights.order(owner,order['order_id'])['money_summary']
    assert not summary['verified'] and summary['net_minor'] is None

@pytest.mark.parametrize('missing_kind',['FLIGHT_ORDER','FLIGHT_CHANGE'])
def test_missing_payment_root_does_not_certify_partial_money_graph(client,missing_kind):
    owner,order,_=booked(client);oid=order['order_id']
    quote=flights.change_quote(owner,oid,changes=[{'leg_index':0,'coupon_ids':[order['coupons'][0]['coupon_id']],'new_departure_date':day(12)}])
    flights.execute_change(owner,oid,quote['quote_id'],consent(quote))
    flights.admin_external_state(oid,'TICKETED','isolated://review-adjustment','review-ops','READPNR',['READTICKET'],quote['quote_id'])
    with SessionLocal.begin() as s:
        original=s.scalar(select(Root).where(Root.business_type==missing_kind,Root.business_id== (oid if missing_kind=='FLIGHT_ORDER' else quote['quote_id'])))
        s.delete(original)
    summary=flights.order(owner,oid)['money_summary']
    assert not summary['verified'],summary
    assert summary['net_minor'] is None
