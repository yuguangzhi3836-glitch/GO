import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ConsumerUnifiedLifecycleRow as Life
from go_hotel.attractions.service import CATALOG
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as bridge
from tests.test_depth21_refund_recovery import booked
from tests.test_depth06_rental_settlement import paid,move,balances
from go_hotel.mobility.rental.service import rental_service
from test_completed_ledger import money_snapshot


def test_closed_nonrefundable_refund_preserves_cancelled_and_frozen_quote(monkeypatch):
    monkeypatch.setitem(CATALOG['tokyo_skytree'],'refundable',False)
    svc,owner,oid=booked('ATTRACTION')
    assert svc.refund_quote(owner,oid)['refund_amount_minor']==0
    before=money_snapshot()
    with pytest.raises(ValueError,match='NON_REFUNDABLE'):svc.refund(owner,oid)
    assert money_snapshot()==before
    svc.admin_external_state(oid,'CLOSED_BY_SUPPLIER','independent://closure','ops')
    q=svc.refund_quote(owner,oid)
    assert q['reason']=='SUPPLIER_CLOSED' and q['refund_amount_minor']==36000
    original=bridge.refund_with_adjustments
    def stop(*args,**kwargs):raise ValueError('INDEPENDENT_PAUSE_BEFORE_MONEY')
    monkeypatch.setattr(bridge,'refund_with_adjustments',stop)
    with pytest.raises(ValueError,match='INDEPENDENT_PAUSE'):svc.refund(owner,oid,q['quote_hash'])
    assert svc.get(owner,oid)['status']=='REFUND_PENDING'
    assert svc.refund_quote(owner,oid)==q
    with SessionLocal() as s:
        life=s.scalar(select(Life).where(Life.order_id==oid))
        assert (life.lifecycle_state,life.refund_state)==('CANCELLED','REFUND_PROCESSING')
    assert money_snapshot()==before
    monkeypatch.setattr(bridge,'refund_with_adjustments',original)
    receipt=svc.refund(owner,oid,q['quote_hash']);after=money_snapshot()
    assert receipt['refund_amount_minor']==36000 and svc.refund(owner,oid,q['quote_hash'])==receipt
    assert money_snapshot()==after
    with SessionLocal() as s:
        life=s.scalar(select(Life).where(Life.order_id==oid))
        assert (life.lifecycle_state,life.refund_state)==('CANCELLED','REFUND_COMPLETED')


def test_attraction_stale_quote_preserves_order_capacity_and_money():
    svc,owner,oid=booked('ATTRACTION');first=svc.change_quote(owner,oid,'2026-10-20');old=svc.change_quote(owner,oid,'2026-10-21')
    svc.execute_change(owner,oid,first['quote_id']);svc.admin_external_state(oid,'CONFIRMED','independent://change','ops','NEW','NEW',first['quote_id'])
    before=(svc.get(owner,oid),svc.search('东京','2026-10-21'),money_snapshot())
    with pytest.raises(ValueError,match='ATTRACTION_CHANGE_QUOTE_STALE_REQUOTE_REQUIRED'):svc.execute_change(owner,oid,old['quote_id'])
    assert (svc.get(owner,oid),svc.search('东京','2026-10-21'),money_snapshot())==before


def test_rental_multiple_capture_refunds_remain_replayable(client):
    owner,oid,_=paid(client)
    move(owner,oid,5);move(owner,oid,2);move(owner,oid,4)
    receipt=rental_service.cancel(owner,oid);before=money_snapshot()
    assert receipt['refund_amount_minor']==168000
    assert rental_service.cancel(owner,oid)==receipt
    assert money_snapshot()==before
    assert balances()=={'CAPTURE':294000,'REFUND':294000}
