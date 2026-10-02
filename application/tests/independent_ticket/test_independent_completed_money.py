"""Fixed local source: completed receipts must not hide changed money facts."""
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement
from go_hotel.flight import coupon_refunds as refunds
from tests.test_depth48_flight_changes import booked,amounts

@pytest.mark.parametrize('field,value',[('amount_minor',1),('currency','USD'),('state','FAILED')])
def test_completed_refund_replay_rejects_changed_money_fact(client,field,value):
    owner,order,_=booked(client)
    oid=order['order_id']
    quote=refunds.quote(owner,oid,[order['coupons'][0]['coupon_id']])
    confirmation={'quote_hash':quote['quote_hash'],'expected_refund_amount_minor':quote['refund_amount_minor'],
                  'currency':quote['currency'],'confirmed':True}
    result=refunds.execute(owner,oid,quote['refund_id'],confirmation)
    with SessionLocal.begin() as s:
        movement=s.get(Movement,result['money_movement_ids'][0])
        setattr(movement,field,value)
    before=amounts()
    with pytest.raises(ValueError,match='FLIGHT_COUPON_REFUND_MONEY_INVALID'):
        refunds.execute(owner,oid,quote['refund_id'],confirmation)
    assert amounts()==before
