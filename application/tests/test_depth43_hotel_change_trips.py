"""Hotel after-sales journeys remain queryable; isolated HTTP/services, not browser E2E."""
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from test_depth14_cash_fare import (booked_order, change_quote, execute, reconcile,
    moves, fare, execution, connector, SessionLocal, OrderRow)
from go_hotel.services.consumer_trip_index import list_trips
from go_hotel.services.transaction_order_view import snapshot


def trip(oid):
    with SessionLocal() as s:
        owner = s.get(OrderRow, oid).account_id
    rows = list_trips(owner)
    return next(x for x in rows if x['order_id'] == oid)


@pytest.mark.parametrize('delta', [80000, 0, -43200])
def test_changed_hotel_trip_has_current_payment_and_dates(client, delta):
    oid = booked_order(client)
    q = change_quote(oid, delta)
    done = execute(oid, q)
    row = trip(oid)
    assert done['state'] == 'COMPLETED'
    assert row['projection_current'], row
    assert row['payment_state'] == 'PAID'
    assert row['refund_state'] == 'NOT_REQUESTED'
    assert row['lifecycle_state'] == 'CONFIRMED'
    assert row['cash_after_sales']['state'] == 'COMPLETED'
    assert row['cash_after_sales']['check_in'] == q['new_check_in']
    assert row['cash_after_sales']['check_out'] == q['new_check_out']
    assert row['cash_after_sales']['amount_paid_minor'] == q['amount_due_minor']
    assert row['cash_after_sales']['current_room_value_minor'] == q['new_value_minor']
    assert row['cash_after_sales']['gross_paid_minor'] == sum(x.amount_minor for x in moves(oid, 'CAPTURE'))
    assert row['navigation']['order_id'] == oid


@pytest.mark.parametrize('failure', ['supplier_unknown', 'capture_pending', 'declined', 'rejected'])
def test_change_problem_keeps_original_trip_and_can_recover(client, failure):
    oid = booked_order(client)
    q = change_quote(oid, 80000)
    if failure == 'supplier_unknown': connector.ambiguous_change = True
    if failure == 'rejected': connector.fail_change = True
    token = {'capture_pending':'pm_capture_fail', 'declined':'pm_decline'}.get(failure, 'pm_success')
    result = execute(oid, q, token)
    if failure == 'rejected': result = reconcile(oid, result)
    row = trip(oid)
    assert row['projection_current'], row
    assert row['payment_state'] == 'PAID'  # Original booking remains paid.
    assert row['cash_after_sales']['state'] == result['state']
    assert row['cash_after_sales']['amount_paid_minor'] == 0
    assert row['cash_after_sales']['check_in'] == q['check_in']
    assert row['cash_after_sales']['check_out'] == q['check_out']
    assert len(moves(oid, 'CAPTURE')) == 1
    if failure == 'capture_pending':
        execution.retry_payment(oid, result['operation_id'], q['quote_hash'], True, 'pm_success')
        after = trip(oid)
        assert after['cash_after_sales']['state'] == 'COMPLETED'
        assert after['cash_after_sales']['amount_paid_minor'] == q['amount_due_minor']
        assert len(moves(oid, 'CAPTURE')) == 2 and connector.change_calls == 1


def test_two_changes_then_refund_retains_latest_stay_and_all_paid_money(client):
    oid = booked_order(client)
    execute(oid, change_quote(oid, 80000))
    second = change_quote(oid, 120000, 60)
    execute(oid, second)
    cancel = fare.cancellation_quote(oid)
    execute(oid, cancel)
    row = trip(oid)
    assert row['projection_current'] and row['refund_state'] == 'REFUND_COMPLETED'
    cash = row['cash_after_sales']
    assert cash['action'] == 'CANCEL' and cash['state'] == 'COMPLETED'
    assert cash['check_in'] == second['new_check_in']
    assert cash['gross_paid_minor'] == 1563200
    assert cash['refunded_minor'] == sum(x.amount_minor for x in moves(oid, 'REFUND')) == 1563200
    assert cash['net_paid_minor'] == 0
    assert len(moves(oid, 'REFUND')) == 3
    common = snapshot('HOTEL', oid, account_id='acct_demo')
    assert common == snapshot('HOTEL', oid, supplier_id='sup_mock')
    assert common == snapshot('HOTEL', oid, admin=True)
    assert common['cash_after_sales'] == cash
    # The legacy original payment has a deliberately narrower money scope.
    assert common['original_payment']['captured_minor'] == 1443200
    assert common['scope'] == 'ORIGINAL_PAYMENT_ROOT'
    from go_hotel.api.routes.interactive import supplier_order_workbench
    from types import SimpleNamespace
    assert supplier_order_workbench(oid, SimpleNamespace(supplier_id='sup_mock'))['data']['cash_after_sales'] == cash
    with pytest.raises(ValueError, match='ORDER_NOT_FOUND'):
        snapshot('HOTEL', oid, account_id='another-account')


def test_failed_refund_after_change_never_advances_trip_totals(client, monkeypatch):
    from go_hotel.services.hosted_money import money
    oid = booked_order(client)
    execute(oid, change_quote(oid, 80000))
    q = fare.cancellation_quote(oid)
    original = money.create_in_session
    calls = []
    def fail(s, intent, body, key, actor):
        if body['movement_type'] == 'REFUND':
            calls.append(key)
            if len(calls) == 2: raise ValueError('ISOLATED_SECOND_REFUND_FAILURE')
        return original(s, intent, body, key, actor)
    with monkeypatch.context() as m:
        m.setattr(money, 'create_in_session', fail)
        with pytest.raises(ValueError, match='SECOND_REFUND'): execute(oid, q)
    row = trip(oid)
    assert row['refund_state'] == 'REFUND_PROCESSING'
    assert row['cash_after_sales']['refunded_minor'] == 0
    assert row['cash_after_sales']['gross_paid_minor'] == 1523200
    assert not moves(oid, 'REFUND')
    reconcile(oid, fare.status(oid))
    assert trip(oid)['cash_after_sales']['refunded_minor'] == 1523200
    assert len(moves(oid, 'REFUND')) == 2 and connector.cancel_calls == 1


def test_stale_projection_is_hidden_and_order_reads_do_not_write(client):
    from go_hotel.db.models import ConsumerUnifiedLifecycleEventRow as Event
    oid = booked_order(client)
    execute(oid, change_quote(oid, 80000))
    with SessionLocal.begin() as s:
        s.get(OrderRow, oid).updated_at = datetime.now(timezone.utc) + timedelta(days=1)
        count = s.scalar(select(func.count()).select_from(Event))
    assert trip(oid)['cash_after_sales'] is None
    assert snapshot('HOTEL', oid, account_id='acct_demo')['cash_after_sales'] is None
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(Event)) == count
