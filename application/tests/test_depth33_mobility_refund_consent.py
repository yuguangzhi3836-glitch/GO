from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import MobilityRideOrderRow, MobilityRentalOrderRow, MobilityRefundRow
from go_hotel.mobility.ride.service import ride_service
from go_hotel.mobility.rental.service import rental_service
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
from test_depth21_refund_recovery import refunded_movements


def booked(v):
    owner='mobility-consent-owner';svc=ride_service if v=='RIDE' else rental_service
    body={'offer_id':'ride_standard' if v=='RIDE' else 'rental_compact','pickup_at':'2026-10-10T10:00:00+08:00',
          'return_at':'2026-10-13T10:00:00+08:00','pickup':'PVG','dropoff':'Bund',
          'pickup_location':'NRT','return_location':'NRT','passengers':[{'full_name':'ISOLATED ADULT'}],
          'drivers':[{'full_name':'ISOLATED DRIVER'}],'currency':'CNY'}
    oid=svc.create(owner,body)['order_id']
    tx=vertical_transaction_bridge.checkout_contract(v,oid,owner,'test-source','isolated://mobility-refund')
    supplier.record_supplier_fact(tx['supplier_fulfillment_id'],{'state':'SUPPLIER_CONFIRMED',
        'external_operation_id':'op-'+oid,'supplier_confirmation_reference':'CONF-'+oid,
        'evidence_reference':'isolated://mobility-confirmed'})
    assert svc.get(owner,oid)['status']=='CONFIRMED'
    return svc,owner,oid


@pytest.mark.parametrize('v',['RIDE','RENTAL'])
def test_mobility_exact_consent_replay_and_owner_binding(v):
    svc,owner,oid=booked(v);q=svc.refund_quote(owner,oid)
    with pytest.raises(ValueError,match='RECONFIRM'):svc.cancel(owner,oid,'f'*64)
    with pytest.raises(ValueError,match='NOT_FOUND'):svc.cancel('other',oid,q['quote_hash'])
    assert not refunded_movements()
    first=svc.cancel(owner,oid,q['quote_hash'])
    assert svc.cancel(owner,oid,q['quote_hash'])==first
    with pytest.raises(ValueError,match='RECONFIRM'):svc.cancel(owner,oid,'f'*64)
    assert len(refunded_movements())==1


@pytest.mark.parametrize('v',['RIDE','RENTAL'])
def test_mobility_order_change_requires_new_refund_consent(v):
    svc,owner,oid=booked(v);q=svc.refund_quote(owner,oid)
    svc.modify(owner,oid,'2026-10-10T11:00:00+08:00')
    with pytest.raises(ValueError,match='RECONFIRM'):svc.cancel(owner,oid,q['quote_hash'])
    assert not refunded_movements()


@pytest.mark.parametrize('v',['RIDE','RENTAL'])
def test_mobility_crash_after_money_keeps_pending_and_recovers_once(v,monkeypatch):
    svc,owner,oid=booked(v);q=svc.refund_quote(owner,oid)
    method='refund' if v=='RIDE' else 'execute_refund_plan';original=getattr(money,method)
    def lost(*a,**kw):original(*a,**kw);raise RuntimeError('AFTER_MONEY')
    monkeypatch.setattr(money,method,lost)
    with pytest.raises(RuntimeError,match='AFTER_MONEY'):svc.cancel(owner,oid,q['quote_hash'])
    assert svc.get(owner,oid)['status']=='REFUND_PENDING'
    assert len(refunded_movements())==1
    with pytest.raises(ValueError,match='CHANGEABLE'):svc.modify(owner,oid,'2026-10-10T11:00:00+08:00')
    monkeypatch.setattr(money,method,original)
    assert svc.cancel(owner,oid,q['quote_hash'])['status']=='REFUND_COMPLETED'
    assert len(refunded_movements())==1


def test_ride_pending_refund_blocks_fulfillment_and_modification(monkeypatch):
    svc,owner,oid=booked('RIDE');q=svc.refund_quote(owner,oid)
    entered=Event();finish=Event();original=money.refund
    def paused(*a,**kw):entered.set();assert finish.wait(10);return original(*a,**kw)
    monkeypatch.setattr(money,'refund',paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task=pool.submit(svc.cancel,owner,oid,q['quote_hash'])
        try:
            assert entered.wait(10)
            with pytest.raises(ValueError,match='CHANGEABLE'):svc.modify(owner,oid,'2026-10-10T11:00:00+08:00')
            with pytest.raises(ValueError,match='ILLEGAL_STATE'):svc.fulfill(owner,oid,'START','isolated://start')
        finally:finish.set()
        assert task.result()['status']=='REFUND_COMPLETED'


def test_ride_fabricated_money_receipt_does_not_complete_order(monkeypatch):
    svc,owner,oid=booked('RIDE');q=svc.refund_quote(owner,oid)
    monkeypatch.setattr(money,'refund',lambda *a,**kw:{'state':'CONFIRMED','money_movement_id':'absent'})
    with pytest.raises(ValueError,match='MONEY_NOT_CONFIRMED'):svc.cancel(owner,oid,q['quote_hash'])
    assert svc.get(owner,oid)['status']=='REFUND_PENDING'


def test_rental_changed_settlement_plan_cannot_resume(monkeypatch):
    svc,owner,oid=booked('RENTAL');q=svc.refund_quote(owner,oid)
    monkeypatch.setattr(money,'execute_refund_plan',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('OFFLINE')))
    with pytest.raises(RuntimeError):svc.cancel(owner,oid,q['quote_hash'])
    with SessionLocal.begin() as s:
        row=s.scalar(select(MobilityRefundRow).where(MobilityRefundRow.order_id==oid));row.settlement_plan_json=[]
    with pytest.raises(ValueError,match='INTEGRITY'):svc.cancel(owner,oid,q['quote_hash'])
    assert not refunded_movements()
