"""Exact customer cancellation quote reads, ownership and execution-time staleness."""
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import CatalogCashFareQuoteRow as Quote, CatalogCashFareOperationRow as Operation, OrderRow
from go_hotel.connectors.mock_hotel import connector
from test_depth14_cash_fare_api import signed_booking
from test_depth13_catalog_fare import data
from test_sprint3a_flight import auth


def quote(client,h,oid):
    return data(client.post(f'/v1/mobile/orders/{oid}/cancellation-quote',headers=h))


def test_exact_quote_read_is_immutable_and_does_not_create_new_quote_or_execute(client):
    h,oid=signed_booking(client);q=quote(client,h,oid)
    path=f'/v1/mobile/orders/{oid}/cancellation-quotes/{q["quote_id"]}'
    for _ in range(2):assert data(client.get(path,headers=h))==q
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(Quote))==1
        assert s.scalar(select(func.count()).select_from(Operation))==0
    assert connector.cancel_calls==0
    other=auth(client,'quote34-other@example.test')
    assert client.get(path,headers=other).status_code==404
    client.cookies.clear()
    assert client.get(path).status_code==401


def test_new_quote_does_not_replace_original_accepted_identity(client):
    h,oid=signed_booking(client);accepted=quote(client,h,oid);new=quote(client,h,oid)
    assert accepted['quote_hash']!=new['quote_hash']
    path=f'/v1/mobile/orders/{oid}/cancellation-quotes/{accepted["quote_id"]}'
    assert data(client.get(path,headers=h))==accepted
    result=data(client.post(f'/v1/mobile/orders/{oid}/cancel',headers=h,json={
        'cancellation_quote_id':accepted['quote_id'],'quote_hash':accepted['quote_hash'],'confirmed':True}))
    assert result['quote_id']==accepted['quote_id'] and connector.cancel_calls==1


def test_corrupted_stored_quote_cannot_be_read_as_customer_terms(client):
    h,oid=signed_booking(client);q=quote(client,h,oid)
    with SessionLocal.begin() as s:
        row=s.get(Quote,q['quote_id']);row.payload_json={**row.payload_json,'refund_amount_minor':1}
    r=client.get(f'/v1/mobile/orders/{oid}/cancellation-quotes/{q["quote_id"]}',headers=h)
    assert r.status_code==409 and 'INTEGRITY' in r.text
    assert connector.cancel_calls==0


def test_current_order_revision_still_rechecked_at_execution_with_same_amount(client):
    h,oid=signed_booking(client);q=quote(client,h,oid)
    with SessionLocal.begin() as s:s.get(OrderRow,oid).version+=1
    path=f'/v1/mobile/orders/{oid}/cancellation-quotes/{q["quote_id"]}'
    assert data(client.get(path,headers=h))==q
    r=client.post(f'/v1/mobile/orders/{oid}/cancel',headers=h,json={
        'cancellation_quote_id':q['quote_id'],'quote_hash':q['quote_hash'],'confirmed':True})
    assert r.status_code==409 and 'STALE' in r.text and connector.cancel_calls==0
