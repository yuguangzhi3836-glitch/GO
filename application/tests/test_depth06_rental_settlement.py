from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (RentalChangeQuoteRow as Quote, MobilityRentalOrderRow as Order,
    MobilityRefundRow, OmnichannelMoneyMovementRow as Movement)
from go_hotel.mobility.rental.service import rental_service as rental
from go_hotel.mobility.rental import changes
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as bridge
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from tests.test_sprint3a_flight import auth

START='2026-10-01T10:00:00'
def end(days):return (datetime.fromisoformat(START)+timedelta(days=days)).isoformat()

def paid(client):
    headers=auth(client)
    r=client.post('/v1/mobility/rentals/orders',headers=headers,json={'offer_id':'rental_compact',
        'pickup_location':'哈尔滨机场','return_location':'哈尔滨机场','pickup_at':START,'return_at':end(3),
        'drivers':[{'full_name':'TEST DRIVER','driver_license_number':'TEST123456'}]})
    assert r.status_code==200,r.text
    order=r.json()['data'];oid=order['order_id']
    r=client.post('/v1/consumer/checkout/RENTAL/'+oid,headers={**headers,'Idempotency-Key':'rental-pay'},
        json={'mode':'CONTRACT_SIMULATOR','expected_amount_minor':order['total_amount_minor'],'currency':'CNY'})
    assert r.status_code==200,r.text
    with SessionLocal() as s:account=s.get(Order,oid).account_id
    return account,oid,headers

def move(account,oid,days):
    q=changes.quote(account,oid,START,end(days))
    return changes.execute(account,oid,q['quote_id'],q['difference_minor'],'CNY')

def balances():
    with SessionLocal() as s:
        rows=s.scalars(select(Movement).where(Movement.state=='CONFIRMED')).all()
        return {kind:sum(r.amount_minor for r in rows if r.movement_type==kind) for kind in ['CAPTURE','REFUND']}


def test_longer_shorter_longer_then_cancel_returns_every_capture_once(client):
    account,oid,_=paid(client)
    assert move(account,oid,5)['difference_minor']==84000
    assert move(account,oid,2)['difference_minor']==-126000
    assert move(account,oid,4)['difference_minor']==84000
    assert rental.get(account,oid)['total_amount_minor']==168000
    first=rental.cancel(account,oid);again=rental.cancel(account,oid)
    assert first==again and first['refund_amount_minor']==168000
    assert balances()=={'CAPTURE':294000,'REFUND':294000}
    with SessionLocal() as s:
        rows=s.scalars(select(Movement).where(Movement.movement_type=='REFUND')).all()
        assert all(s.get(Movement,r.parent_movement_id).movement_type=='CAPTURE' for r in rows)
        assert len(s.scalars(select(MobilityRefundRow)).all())==1


def test_quote_is_explicit_bound_to_amount_owner_and_dates(client):
    account,oid,headers=paid(client)
    q=changes.quote(account,oid,START,end(4))
    assert rental.get(account,oid)['return_at']==end(3) and balances()['CAPTURE']==126000
    with pytest.raises(ValueError,match='NOT_FOUND'):changes.execute('intruder',oid,q['quote_id'],42000,'CNY')
    for amount,currency in [(1,'CNY'),(42000,'USD'),(True,'CNY')]:
        with pytest.raises(ValueError,match='RECONFIRM'):changes.execute(account,oid,q['quote_id'],amount,currency)
    r=client.post(f'/v1/mobility/rentals/orders/{oid}/changes/{q["quote_id"]}',headers=headers,
        json={'expected_difference_minor':42000,'currency':'CNY'})
    assert r.status_code==422
    rental.modify(account,oid,'2026-10-01T11:00:00')
    with pytest.raises(ValueError,match='STALE'):changes.execute(account,oid,q['quote_id'],42000,'CNY')


def test_expired_quote_and_mismatched_order_do_not_move_money(client):
    account,oid,_=paid(client);q=changes.quote(account,oid,START,end(4))
    with SessionLocal.begin() as s:s.get(Quote,q['quote_id']).expires_at=datetime(2000,1,1)
    with pytest.raises(ValueError,match='EXPIRED'):changes.execute(account,oid,q['quote_id'],42000,'CNY')
    assert balances()['CAPTURE']==126000


def test_topup_failure_is_recoverable_and_blocks_competing_actions(client,monkeypatch):
    account,oid,_=paid(client);q=changes.quote(account,oid,START,end(4))
    original=bridge.capture_adjustment
    def fail(*a,**kw):raise ValueError('INJECTED_CAPTURE_INTERRUPTION')
    monkeypatch.setattr(bridge,'capture_adjustment',fail)
    with pytest.raises(ValueError,match='INTERRUPTION'):changes.execute(account,oid,q['quote_id'],42000,'CNY')
    current=rental.get(account,oid)
    assert current['status']=='CHANGE_PENDING' and current['pending_change']['quote_id']==q['quote_id']
    assert current['return_at']==end(3)
    with pytest.raises(ValueError,match='NOT_CANCELLABLE'):rental.cancel(account,oid)
    with pytest.raises(ValueError,match='ILLEGAL'):rental.fulfill(account,oid,'PICKUP','test://pickup')
    monkeypatch.setattr(bridge,'capture_adjustment',original)
    for _ in range(2):assert changes.execute(account,oid,q['quote_id'],42000,'CNY')['status']=='EXECUTED'
    assert balances()['CAPTURE']==168000


@pytest.mark.parametrize('operation',['shorten','cancel'])
def test_partial_refund_worker_restart_reuses_frozen_allocations(client,monkeypatch,operation):
    account,oid,_=paid(client);move(account,oid,5)
    q=changes.quote(account,oid,START,end(1)) if operation=='shorten' else None
    def execute():return changes.execute(account,oid,q['quote_id'],q['difference_minor'],'CNY') if q else rental.cancel(account,oid)
    original=money.create;seen=0
    def fail_second(intent,body,*args,**kwargs):
        nonlocal seen
        if body['movement_type']=='REFUND':
            seen+=1
            if seen==2:raise ValueError('INJECTED_SECOND_COMPONENT_INTERRUPTION')
        return original(intent,body,*args,**kwargs)
    monkeypatch.setattr(money,'create',fail_second)
    with pytest.raises(ValueError,match='INTERRUPTION'):execute()
    assert balances()['REFUND']==126000
    monkeypatch.setattr(money,'create',original)
    first=execute();again=execute();assert first==again
    assert balances()['REFUND']==(168000 if q else 210000)
    if q:rental.cancel(account,oid);assert balances()['REFUND']==210000


def test_competing_quotes_only_one_can_change_order(client):
    account,oid,_=paid(client)
    quotes=[changes.quote(account,oid,START,end(days)) for days in (4,5)]
    def execute(q):
        try:return changes.execute(account,oid,q['quote_id'],q['difference_minor'],'CNY')['status']
        except ValueError:return 'BLOCKED'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(execute,quotes))
    assert sorted(results)==['BLOCKED','EXECUTED']
    assert balances()['CAPTURE']==rental.get(account,oid)['total_amount_minor']


def test_same_quote_concurrent_retries_charge_once(client):
    account,oid,_=paid(client);q=changes.quote(account,oid,START,end(4))
    def execute(_):return changes.execute(account,oid,q['quote_id'],42000,'CNY')['status']
    with ThreadPoolExecutor(max_workers=2) as pool:assert list(pool.map(execute,range(2)))==['EXECUTED','EXECUTED']
    assert balances()['CAPTURE']==168000


def test_equal_price_change_does_not_add_money_movements(client):
    account,oid,_=paid(client);q=changes.quote(account,oid,'2026-10-02T10:00:00',end(4))
    assert q['difference_minor']==0
    changes.execute(account,oid,q['quote_id'],0,'CNY')
    assert balances()=={'CAPTURE':126000,'REFUND':0}


def test_staging_cannot_run_rental_simulator(client,monkeypatch):
    account,oid,_=paid(client)
    monkeypatch.setattr(changes.settings,'app_env','staging')
    with pytest.raises(ValueError,match='FORBIDDEN'):changes.quote(account,oid,START,end(4))
