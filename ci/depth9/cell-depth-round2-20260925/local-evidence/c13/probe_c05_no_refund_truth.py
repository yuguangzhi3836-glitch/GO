from sqlalchemy import select, func
from test_c05_cancellation_policy import BODY, confirm, svc
from ride_cancellation_fixture import synthetic_policy, accepted_body
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import MobilityRideOrderRow as Order, MobilityRefundRow as Refund, ConsumerUnifiedLifecycleRow as Life, OmnichannelMoneyMovementRow as Money
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle

def test_zero_refund_has_no_false_receipt_in_api_db_or_reprojection():
    with synthetic_policy(before=16800, after=16800):
        oid=confirm(svc.create('owner',accepted_body(svc,BODY)))
    quote=svc.refund_quote('owner',oid)
    result=svc.cancel('owner',oid,quote['quote_hash'])
    assert result['outcome']=='NO_REFUND_DUE' and result['refund_performed'] is False
    assert result['status']!='REFUND_COMPLETED'
    assert svc.cancel('owner',oid,quote['quote_hash'])==result
    with SessionLocal.begin() as s:
        order=s.get(Order,oid)
        assert order.status=='CANCELLED'
        refund=s.scalar(select(Refund).where(Refund.order_id==oid))
        assert refund.status=='NO_REFUND_DUE'
        assert not s.scalar(select(func.count()).select_from(Money).where(Money.movement_type=='REFUND'))
        life=s.scalar(select(Life).where(Life.order_id==oid))
        assert life.lifecycle_state=='CANCELLED' and life.payment_state=='PAID'
        assert life.refund_state not in {'REFUNDED','REFUND_COMPLETED','REFUND_PROCESSING'}
        project_vertical_lifecycle(s,'RIDE',order,'independent://later-reprojection')
        assert life.lifecycle_state=='CANCELLED' and life.payment_state=='PAID'
        assert life.refund_state not in {'REFUNDED','REFUND_COMPLETED','REFUND_PROCESSING'}
    from go_hotel.services.transaction_order_view import snapshot
    view=snapshot('RIDE',oid,account_id='owner')
    assert all(item['status']!='REFUND_COMPLETED' for item in view['refunds'])
