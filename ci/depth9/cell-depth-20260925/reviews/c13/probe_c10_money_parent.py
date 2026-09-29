from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderSupplierFulfillmentRow as Fulfillment, OmnichannelMoneyMovementRow as Movement
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as svc
from tests.test_depth20_api_fulfillment import captured


def test_orphan_capture_cannot_establish_paid(client):
    _, order, _, fid, _ = captured(client)
    with SessionLocal.begin() as session:
        fulfillment = session.get(Fulfillment, fid)
        cap = session.scalar(select(Movement).where(Movement.root_payment_intent_id == fulfillment.payment_intent_id,
            Movement.movement_type == 'CAPTURE'))
        cap.parent_movement_id = 'not-an-authorization'
    result = svc.record_supplier_fact(fid, {'state': 'UNKNOWN_EXTERNAL_STATE', 'evidence_reference': 'supplier://unknown'})
    assert result['unified_lifecycle']['payment_state'] == 'UNKNOWN_EXTERNAL_STATE'
