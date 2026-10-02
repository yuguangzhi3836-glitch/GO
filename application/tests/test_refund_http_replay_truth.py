"""Same HTTP idempotency key must not bypass completed money verification."""
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Entry
from go_hotel.security.deps import consumer_principal
from tests.test_depth21_refund_recovery import booked
from tests.test_depth06_rental_settlement import paid
from go_hotel.mobility.rental.service import rental_service

@pytest.mark.parametrize('vertical',['RENTAL','ATTRACTION'])
@pytest.mark.parametrize('confirmed',[False,True])
@pytest.mark.parametrize('fault',['movement','ledger'])
def test_same_http_key_revalidates_financial_receipt(client,vertical,confirmed,fault):
    if vertical=='RENTAL':
        owner,oid,_=paid(client);svc=rental_service;base=f'/v1/mobility/orders/{oid}'
    else:
        svc,owner,oid=booked(vertical);base=f'/v1/attractions/orders/{oid}'
    client.app.dependency_overrides[consumer_principal]=lambda:SimpleNamespace(user_id=owner)
    try:
        q=svc.refund_quote(owner,oid)
        suffix='/refund-confirmed' if confirmed else ('/cancel' if vertical=='RENTAL' else '/refund')
        body={'quote_hash':q['quote_hash'],'confirmed':True} if confirmed else None
        request=lambda:client.post(base+suffix,headers={'Idempotency-Key':'same-original-request'},json=body)
        first=request();assert first.status_code==200,first.text
        assert request().json()==first.json()
        with SessionLocal.begin() as s:
            m=s.scalar(select(Movement).where(Movement.movement_type=='REFUND'))
            if fault=='movement':m.amount_minor=1
            else:s.scalar(select(Entry).where(Entry.transaction_id==m.money_movement_id)).amount_minor=1
        def snapshot():
            with SessionLocal() as s:
                return ([tuple(getattr(x,c.name) for c in Movement.__table__.columns) for x in s.scalars(select(Movement).order_by(Movement.money_movement_id))],
                        [tuple(getattr(x,c.name) for c in Entry.__table__.columns) for x in s.scalars(select(Entry).order_by(*Entry.__table__.primary_key.columns))])
        before=snapshot();replay=request()
        assert replay.status_code==409,replay.text
        assert snapshot()==before
    finally:
        client.app.dependency_overrides.pop(consumer_principal,None)
