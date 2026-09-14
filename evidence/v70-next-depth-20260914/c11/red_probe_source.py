"""Bounded flight HTTP-claim recovery with real SQLite commits and money graphs."""
from datetime import date, timedelta
from types import SimpleNamespace
import json
import pytest
from sqlalchemy import select
from go_hotel.api.routes import flight as route
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightOrderRow, FlightChangeQuoteRow, IdempotencyRow, OmnichannelMoneyMovementRow as Movement
from go_hotel.flight.service import flight_service as flights
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as checkout_bridge
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as change_bridge
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier

OWNER = 'c11-flight-owner'
KEY = 'c11-flight-fixed-key'
PRINCIPAL = SimpleNamespace(user_id=OWNER)


def create_order():
    offer = flights.search('PVG','NRT',(date.today()+timedelta(days=10)).isoformat())[0]
    prebook = flights.prebook(offer['offer_id'])
    return flights.create_order(OWNER,prebook['prebook_id'],[{'full_name':'C11 TEST','type':'ADT'}])


def call_checkout(order_id,key=KEY,owner=OWNER):
    return route.checkout(order_id,route.CheckoutBody(payment_method_id='c11-test-method'),SimpleNamespace(user_id=owner),key)


def create_change():
    order = create_order()
    tx = checkout_bridge.checkout_contract('FLIGHT',order['order_id'],OWNER,'c11-source','isolated://c11')
    supplier.record_supplier_fact(tx['supplier_fulfillment_id'],{'state':'SUPPLIER_CONFIRMED',
        'external_operation_id':'c11-'+order['order_id'],'supplier_confirmation_reference':'C11PNR',
        'ticket_numbers':['C11TICKET'],'evidence_reference':'isolated://c11-ticket'})
    quote = flights.change_quote(OWNER,order['order_id'],(date.today()+timedelta(days=12)).isoformat())
    return order,quote


def call_change(order_id,quote_id,key=KEY,owner=OWNER):
    return route.execute_change(order_id,quote_id,SimpleNamespace(user_id=owner),key,None)


def observe(operation,resource_id,order_id):
    with SessionLocal() as session:
        claim=session.get(IdempotencyRow,{'operation':operation,'idempotency_key':KEY})
        order=session.get(FlightOrderRow,order_id)
        money=list(session.scalars(select(Movement).where(Movement.business_id.in_([order_id,resource_id]))))
        result={'operation':operation,'resource_id':resource_id,'order_id':order_id,'order_status':order.status,
            'claim':None if not claim else {'code':claim.response_code,'resource_id':claim.resource_id,'body':claim.response_body},
            'money':[{'id':m.money_movement_id,'root':m.root_payment_intent_id,'type':m.movement_type,'amount':m.amount_minor,'currency':m.currency,'state':m.state,'key':m.idempotency_key} for m in money]}
    print('C11_SQL '+json.dumps(result,sort_keys=True))
    return result


@pytest.mark.parametrize('operation',['FLIGHT_CHECKOUT','FLIGHT_EXECUTE_CHANGE'])
def test_after_committed_money_failure_retains_resource_and_recovers_same_root(monkeypatch,operation):
    if operation=='FLIGHT_CHECKOUT':
        order=create_order();resource=order['order_id'];bridge=checkout_bridge;name='checkout_contract'
        call=lambda:call_checkout(order['order_id'])
    else:
        order,quote=create_change();resource=quote['quote_id'];bridge=change_bridge;name='prepare_adjustment'
        call=lambda:call_change(order['order_id'],quote['quote_id'])
    original=getattr(bridge,name)
    def lost(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('C11_AFTER_COMMITTED_MONEY')
    monkeypatch.setattr(bridge,name,lost)
    with pytest.raises(RuntimeError,match='C11_AFTER_COMMITTED_MONEY'):call()
    before=observe(operation,resource,order['order_id'])
    assert before['claim'] is not None
    assert before['claim']['code']==102
    assert before['claim']['resource_id']==resource
    assert before['claim']['body']['status']=='RECOVERY_REQUIRED'
    before_money=before['money']
    monkeypatch.setattr(bridge,name,original)
    result=call()
    after=observe(operation,resource,order['order_id'])
    assert after['claim']['code']==200
    assert after['money']==before_money
    assert call()==result
    assert result['data']['status']==('PAYMENT_CONFIRMED_AWAITING_SUPPLIER' if operation=='FLIGHT_CHECKOUT' else 'UNKNOWN_EXTERNAL_STATE')
