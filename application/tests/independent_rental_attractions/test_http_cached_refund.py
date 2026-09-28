"""Independent real-auth HTTP cache tests; no dependency overrides."""
from copy import deepcopy
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import IdempotencyRow, OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Ledger
from test_attraction_independent import booked
from tests.test_depth06_rental_settlement import paid
from test_completed_ledger import money_snapshot

@pytest.mark.parametrize('vertical',['ATTRACTION','RENTAL'])
@pytest.mark.parametrize('confirmed',[False,True])
@pytest.mark.parametrize('fault',['movement','ledger','cached_receipt'])
def test_http_same_key_rechecks_money_and_exact_cached_receipt(client,vertical,confirmed,fault):
    if vertical=='ATTRACTION':
        headers,oid=booked(client);base=f'/v1/attractions/orders/{oid}';suffix='refund';operation='ATTRACTION_REFUND'
    else:
        _,oid,headers=paid(client);base=f'/v1/mobility/orders/{oid}';suffix='cancel';operation='MOBILITY_CANCEL'
    q=client.get(base+'/refund-quote',headers=headers).json()['data']
    if confirmed:
        suffix='refund-confirmed';operation='ATTRACTION_REFUND_CONFIRMED' if vertical=='ATTRACTION' else 'MOBILITY_REFUND_CONFIRMED'
    body={'quote_hash':q['quote_hash'],'confirmed':True} if confirmed else None
    key='independent-fixed-refund-key'
    def request():return client.post(base+'/'+suffix,headers={**headers,'Idempotency-Key':key},json=body)
    first=request();assert first.status_code==200,first.text
    first_money=money_snapshot();assert request().json()==first.json();assert money_snapshot()==first_money
    with SessionLocal.begin() as s:
        if fault=='cached_receipt':
            cache=s.get(IdempotencyRow,(key,operation));assert cache is not None
            bad=deepcopy(cache.response_body);bad['data']['refund_amount_minor']=1;cache.response_body=bad
        else:
            m=s.scalar(select(Movement).where(Movement.movement_type=='REFUND'))
            if fault=='movement':m.amount_minor=1
            else:s.scalar(select(Ledger).where(Ledger.transaction_id==m.money_movement_id)).amount_minor=1
    before=money_snapshot()
    with SessionLocal() as s:cached=deepcopy(s.get(IdempotencyRow,(key,operation)).response_body)
    response=request();assert response.status_code==409,response.text
    assert money_snapshot()==before
    with SessionLocal() as s:assert s.get(IdempotencyRow,(key,operation)).response_body==cached
