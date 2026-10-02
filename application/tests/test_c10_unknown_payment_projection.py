from types import SimpleNamespace

import pytest

from go_hotel.db.session import SessionLocal
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service as svc
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle


@pytest.mark.parametrize('vertical', ['FLIGHT', 'RAIL', 'HOTEL', 'RIDE', 'RENTAL', 'ATTRACTION'])
def test_unknown_external_state_does_not_assert_payment_success(vertical):
    order = SimpleNamespace(status='UNKNOWN_EXTERNAL_STATE', account_id='owner',
                            order_id='unknown-order', supplier_id=None)
    with SessionLocal() as session:
        projected = project_vertical_lifecycle(session, vertical, order, 'recovery://unknown')
        session.commit()
    item = svc.detail('owner', projected['consumer_unified_lifecycle_id'])['item']
    assert item['lifecycle_state'] == 'UNKNOWN_EXTERNAL_STATE'
    assert item['payment_state'] == 'UNKNOWN_EXTERNAL_STATE'
    assert item['change_allowed'] is item['cancel_allowed'] is False


def test_unknown_can_recover_to_confirmed_on_later_authoritative_projection():
    order = SimpleNamespace(status='UNKNOWN_EXTERNAL_STATE', account_id='owner',
                            order_id='recovering-order', supplier_id=None)
    with SessionLocal() as session:
        first = project_vertical_lifecycle(session, 'FLIGHT', order, 'recovery://unknown')
        session.commit()
        order.status = 'TICKETED'
        second = project_vertical_lifecycle(session, 'FLIGHT', order, 'supplier://ticketed')
        session.commit()
    assert first['payment_state'] == 'UNKNOWN_EXTERNAL_STATE'
    assert second['lifecycle_state'] == 'CONFIRMED'
    assert second['payment_state'] == 'PAID'
