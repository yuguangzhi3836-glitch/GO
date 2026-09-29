import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Ledger
from test_attraction_independent import booked
from tests.test_depth06_rental_settlement import paid


def money_snapshot():
    with SessionLocal() as s:
        return {model.__tablename__:sorted([tuple(repr(getattr(row,c.name)) for c in model.__table__.columns) for row in s.scalars(select(model))]) for model in [Movement,Ledger]}


@pytest.mark.parametrize('vertical',['ATTRACTION','RENTAL'])
@pytest.mark.parametrize('field,value',[('amount_minor',1),('currency','USD'),('account_code','WRONG:ACCOUNT'),('evidence_hash','0'*64)])
def test_completed_replay_requires_correct_double_entry_ledger(client,vertical,field,value):
    if vertical=='ATTRACTION':
        headers,oid=booked(client);path=f'/v1/attractions/orders/{oid}/refund'
    else:
        _,oid,headers=paid(client);path=f'/v1/mobility/orders/{oid}/cancel'
    first=client.post(path,headers=headers)
    assert first.status_code==200,first.text
    with SessionLocal.begin() as s:
        refund=s.scalar(select(Movement).where(Movement.movement_type=='REFUND'))
        entry=s.scalar(select(Ledger).where(Ledger.transaction_id==refund.money_movement_id))
        assert entry is not None
        setattr(entry,field,value)
    before=money_snapshot()
    response=client.post(path,headers=headers)
    assert money_snapshot()==before
    assert response.status_code>=400,response.json()
