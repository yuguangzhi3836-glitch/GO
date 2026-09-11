import asyncio
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import CatalogCashFareOperationRow as Operation, OrderRow
from go_hotel.services.booking import booking_service
from go_hotel.connectors.mock_hotel import connector
from test_sprint3a_flight import auth
from test_depth13_catalog_fare import prebook,data
from test_depth14_cash_fare import day

def signed_booking(client):
    h=auth(client,'cash-fare14-owner@example.com');_,pb=prebook(client)
    order=data(client.post('/v1/consumer/orders',headers=h,json={'prebook_id':pb['prebook_id'],
        'expected_fare_rule_hash':pb['fare_rule']['offer_rule_hash'],'fare_confirmed':True}))
    asyncio.run(booking_service.pay(order['order_id'],order['total_amount_minor'],'CNY','pm_success'))
    asyncio.run(booking_service.confirm(order['order_id']))
    return h,order['order_id']

def test_mobile_cash_cancel_requires_owned_quote_and_replays_same_web_request(client):
    h,oid=signed_booking(client)
    other=auth(client,'cash-fare14-other@example.com')
    q=data(client.post(f'/v1/mobile/orders/{oid}/cancellation-quote',headers=h))
    path=f'/v1/mobile/orders/{oid}/cancel'
    body={'cancellation_quote_id':q['quote_id'],'quote_hash':q['quote_hash'],'confirmed':True}
    assert client.post(path,headers=other,json=body).status_code==404
    assert client.post(path,headers=h,json={'cancellation_quote_id':q['quote_id']}).status_code==409
    assert client.post(path,headers=h,json={**body,'confirmed':1}).status_code==422
    assert client.post(path,headers=h,json={**body,'quote_hash':'0'*64}).status_code==409
    first=data(client.post(path,headers={**h,'Idempotency-Key':'cash-mobile-cancel'},json=body))
    same=data(client.post(f'/v1/orders/{oid}/cancel',headers={**h,'Idempotency-Key':'cash-mobile-cancel'},json=body))
    assert first==same and first['state']=='COMPLETED' and connector.cancel_calls==1
    with SessionLocal() as s:
        op=s.get(Operation,first['operation_id'])
        assert op.plan_json['actor_id']==s.get(OrderRow,oid).account_id
        assert op.plan_json['acceptance_kind']=='CUSTOMER_EXPLICIT'
    assert data(client.get(f'/v1/mobile/orders/{oid}/cash-after-sales',headers=h))['state']=='COMPLETED'
    assert client.get(f'/v1/mobile/orders/{oid}/cash-after-sales',headers=other).status_code==404

def test_native_and_web_change_share_operation_recovery_and_order_progress(client,monkeypatch):
    h,oid=signed_booking(client)
    connector.date_price_delta[day(50)]=80000
    q=data(client.post(f'/v1/mobile/orders/{oid}/change-quote',headers=h,json={'new_check_in':day(50),'new_check_out':day(54)}))
    original=connector.change
    async def lost(*args,**kwargs):
        await original(*args,**kwargs);raise TimeoutError('LOST_REPLY')
    monkeypatch.setattr(connector,'change',lost)
    body={'change_quote_id':q['change_quote_id'],'quote_hash':q['quote_hash'],'confirmed':True}
    path=f'/v1/mobile/orders/{oid}/change'
    assert client.post(path,headers=h,json={**body,'confirmed':False}).status_code==409
    first=data(client.post(path,headers={**h,'Idempotency-Key':'cash-mobile-change'},json=body))
    assert first['state']=='UNKNOWN_SUPPLIER'
    assert data(client.post(f'/v1/orders/{oid}/change',headers={**h,'Idempotency-Key':'cash-mobile-change'},json=body))==first
    done=data(client.post(f'/v1/mobile/orders/{oid}/cash-after-sales/{first["operation_id"]}/reconcile',headers=h))
    assert done['state']=='COMPLETED' and connector.change_calls==1
    detail=data(client.get(f'/v1/consumer/orders/{oid}/detail',headers=h))
    assert detail['stay']['check_in']==day(50) and detail['cash_after_sales']['gross_paid_minor']==1533200
    assert detail['cash_after_sales']['state']=='COMPLETED'

def test_status_and_resume_do_not_accept_another_order_operation_id(client):
    h,oid=signed_booking(client)
    other=auth(client,'cash-fare14-third@example.com')
    q=data(client.post(f'/v1/orders/{oid}/cancellation-quote',headers=h))
    result=data(client.post(f'/v1/orders/{oid}/cancel',headers=h,json={'cancellation_quote_id':q['quote_id'],'quote_hash':q['quote_hash'],'confirmed':True}))
    path=f'/v1/orders/{oid}/cash-after-sales/{result["operation_id"]}/reconcile'
    assert client.post(path,headers=other).status_code==404

def test_mobile_payment_retry_requires_boolean_confirmation_and_original_hash(client):
    h,oid=signed_booking(client)
    q=data(client.post(f'/v1/orders/{oid}/change-quote',headers=h,json={'new_check_in':day(50),'new_check_out':day(54)}))
    pending=data(client.post(f'/v1/orders/{oid}/change',headers=h,json={'change_quote_id':q['quote_id'],
        'quote_hash':q['quote_hash'],'confirmed':True,'payment_method_token':'pm_capture_fail'}))
    path=f'/v1/mobile/orders/{oid}/cash-after-sales/{pending["operation_id"]}/retry-payment'
    body={'quote_hash':q['quote_hash'],'confirmed':True,'payment_method_token':'pm_success'}
    assert client.post(path,headers=h,json={**body,'confirmed':1}).status_code==422
    assert client.post(path,headers=h,json={**body,'confirmed':False}).status_code==409
    assert client.post(path,headers=h,json={**body,'quote_hash':'0'*64}).status_code==409
    assert data(client.post(path,headers=h,json=body))['state']=='COMPLETED' and connector.change_calls==1
