import pytest
from sqlalchemy import select
from tests.test_depth06_rental_settlement import paid
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement

@pytest.mark.parametrize('field,value',[('amount_minor',1),('currency','USD'),('state','UNKNOWN')])
def test_completed_rental_cancel_replay_checks_real_money(client,field,value):
    account,oid,headers=paid(client)
    first=client.post(f'/v1/mobility/orders/{oid}/cancel',headers=headers)
    assert first.status_code==200,first.text
    with SessionLocal.begin() as s:
        refunds=list(s.scalars(select(Movement).where(Movement.movement_type=='REFUND')))
        assert len(refunds)==1
        setattr(refunds[0],field,value)
    replay=client.post(f'/v1/mobility/orders/{oid}/cancel',headers=headers)
    assert replay.status_code>=400,{'field':field,'first':first.json(),'replay':replay.json()}
