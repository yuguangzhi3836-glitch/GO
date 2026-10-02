"""Independent negative assertions; no changes to product implementation."""
import pytest
from sqlalchemy import select
from tests.test_sprint3d_attractions import auth
from tests.attraction_fixtures import quoted_attraction
from tests.vertical_transaction_helpers import pay_and_confirm
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement


def booked(client):
    headers=auth(client)
    response=client.post('/v1/attractions/orders',headers=headers,json=quoted_attraction(client,{'offer_id':'tokyo_skytree','visit_date':'2020-01-01','quantity':1}))
    assert response.status_code==200,response.text
    oid=response.json()['data']['order_id']
    pay_and_confirm(client,headers,'ATTRACTION_ORDER',oid,'INDEPENDENT-SUPPLIER',voucher_code='INDEPENDENT-VOUCHER')
    return headers,oid


@pytest.mark.parametrize('missing_policy',[False,True])
def test_past_session_cannot_redeem_without_verified_window(client,monkeypatch,missing_policy):
    if missing_policy:
        from go_hotel.attractions.service import CATALOG
        monkeypatch.delitem(CATALOG['tokyo_skytree'],'supplier_validity_policy',raising=False)
    h,oid=booked(client)
    before=client.get(f'/v1/attractions/orders/{oid}',headers=h).json()['data']
    r=client.post(f'/v1/attractions/orders/{oid}/redeem',headers=h,json={'evidence_reference':'customer-unverified-claim'})
    assert r.status_code>=400,{'before':before,'response':r.json()}
    after=client.get(f'/v1/attractions/orders/{oid}',headers=h).json()['data']
    assert after==before


@pytest.mark.parametrize('field,value',[('amount_minor',1),('currency','USD'),('state','UNKNOWN')])
def test_completed_refund_replay_checks_real_money(client,field,value):
    h,oid=booked(client)
    first=client.post(f'/v1/attractions/orders/{oid}/refund',headers=h)
    assert first.status_code==200,first.text
    with SessionLocal.begin() as s:
        refunds=list(s.scalars(select(Movement).where(Movement.movement_type=='REFUND')))
        assert len(refunds)==1
        setattr(refunds[0],field,value)
    replay=client.post(f'/v1/attractions/orders/{oid}/refund',headers=h)
    assert replay.status_code>=400,{'field':field,'first':first.json(),'replay':replay.json()}
