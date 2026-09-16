"""C04-01: bounded admin presentation over the inherited read-only diagnosis."""
from sqlalchemy import event, select

from go_hotel.api.routes import operations_console as ops
from go_hotel.db.models import MobilityRefundRow as Refund
from go_hotel.db.session import SessionLocal, engine
from go_hotel.security.deps import admin_principal
from tests.test_depth33_mobility_refund_consent import booked


def test_admin_rental_reconciliation_is_get_only_and_admin_bound():
    route = next(
        item for item in ops.router.routes
        if item.path.endswith('/reconciliations/rental/{order_id}/{refund_id}')
    )
    assert route.methods == {'GET'}
    assert [dependency.call for dependency in route.dependant.dependencies] == [admin_principal]


def test_admin_rental_reconciliation_presents_findings_without_writes_or_repair():
    service, owner, order_id = booked('RENTAL')
    quote = service.refund_quote(owner, order_id)
    completed = service.cancel(owner, order_id, quote['quote_hash'])
    refund_id = completed['refund_id']

    with SessionLocal.begin() as session:
        refund = session.scalar(select(Refund).where(Refund.refund_id == refund_id))
        refund.status = 'REFUND_COMPLETED'
        order = session.get(ops.MobilityRentalOrderRow, order_id)
        order.status = 'CONFIRMED'
    before = service.get(owner, order_id)

    def read_only(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().split()[0].upper() in {'SELECT', 'PRAGMA'}, statement

    event.listen(engine, 'before_cursor_execute', read_only)
    try:
        data = ops.rental_refund_reconciliation(order_id, refund_id, p=None)['data']
    finally:
        event.remove(engine, 'before_cursor_execute', read_only)

    diagnosis = data['diagnosis']
    presentation = data['presentation']
    assert diagnosis['status'] == 'CONTRADICTION'
    assert diagnosis['read_only'] is True
    assert diagnosis['automatic_repair'] is False
    assert presentation['status'] == {
        'code': 'CONTRADICTION',
        'label': '订单、退款或资金证据存在矛盾',
    }
    assert presentation['review_required'] is True
    case = presentation['case']
    assert case == {
        'case_id': f'RENTAL_REFUND:{order_id}:{refund_id}',
        'vertical': 'RENTAL',
        'order_id': order_id,
        'refund_id': refund_id,
        'next_review_action': diagnosis['next_action'],
        'confirmed_movement_ids': sorted(diagnosis['confirmed_movement_ids']),
        'read_only': True,
    }
    # Re-reading the same diagnosis yields the same handoff identity and does
    # not manufacture an acknowledgement or mutate business state.
    repeated = ops.rental_refund_reconciliation(order_id, refund_id, p=None)['data']
    assert repeated['presentation']['case'] == case
    assert service.get(owner, order_id) == before
    assert presentation['read_only'] is True
    assert presentation['automatic_repair'] is False
    assert any(
        finding['code'] == 'COMPLETED_REFUND_ORDER_STATE_MISMATCH'
        and finding['label'] == '退款已完成但订单状态不一致'
        for finding in presentation['findings']
    )
    assert '从本页面执行资金操作' in presentation['prohibited_operator_actions']
    assert '从本页面自动修改订单或退款状态' in presentation['prohibited_operator_actions']
    assert service.get(owner, order_id) == before
