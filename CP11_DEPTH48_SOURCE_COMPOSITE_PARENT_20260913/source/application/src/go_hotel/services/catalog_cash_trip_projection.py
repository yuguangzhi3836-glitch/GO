"""Cash after-sales facts published atomically with the accepted operation.

Amounts describe the retained quote and completed cash operation; they are not
bank settlement evidence. Original booking amounts and payment roots stay intact.
"""
from datetime import timezone
from sqlalchemy import select
from go_hotel.db.models import ConsumerUnifiedLifecycleRow as Life
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service


def cash_facts(op):
    b = op.plan_json['quote']
    changed = b['action'] == 'CHANGE' and op.state == 'COMPLETED'
    cancelled = b['action'] == 'CANCEL' and op.state == 'COMPLETED'
    extra = b['amount_due_minor'] if changed else 0
    refunded = b['prior_refund_minor'] + (b['refund_amount_minor'] if cancelled else 0)
    paid = b['gross_paid_minor'] + extra
    return {
        'operation_id': op.operation_id, 'action': b['action'], 'state': op.state,
        'currency': b['currency'], 'check_in': b['new_check_in'] if changed else b['check_in'],
        'check_out': b['new_check_out'] if changed else b['check_out'],
        'requested_check_in': b.get('new_check_in'), 'requested_check_out': b.get('new_check_out'),
        'amount_due_minor': b.get('amount_due_minor', 0), 'amount_paid_minor': extra,
        'current_room_value_minor': b['new_value_minor'] if changed else b['current_room_value_minor'],
        'gross_paid_minor': paid, 'refunded_minor': refunded, 'net_paid_minor': paid - refunded,
        'paid_change_fees_minor': b['paid_change_fees_minor'] + (b['change_fee_minor'] if changed else 0),
        'forfeited_change_value_minor': b['forfeited_change_value_minor'] +
            (b['lower_price_difference_minor'] if changed else 0),
        'scope': 'ACCEPTED_CASH_FARE_OPERATION_FACTS', 'bank_settlement_verified': False,
    }


def project(s, order, op, timestamp):
    current = s.scalar(select(Life).where(Life.vertical == 'HOTEL', Life.order_id == order.order_id))
    facts = dict(current.facts_json or {}) if current else {}
    facts.update(native_status=order.status, cash_after_sales=cash_facts(op))
    cancel = op.plan_json['quote']['action'] == 'CANCEL'
    active = op.state not in {'COMPLETED', 'REJECTED', 'PAYMENT_DECLINED'}
    return consumer_unified_lifecycle_service.project_in_session(s, {
        'account_id': order.account_id, 'supplier_id': order.supplier_id,
        'vertical': 'HOTEL', 'order_id': order.order_id,
        'title': current.title if current else f'HOTEL {order.order_id}',
        'lifecycle_state': 'CANCELLED' if order.status == 'CANCELLED' else 'CONFIRMED',
        'payment_state': 'PAID',
        'refund_state': ('REFUND_COMPLETED' if op.state == 'COMPLETED' else 'REFUND_PROCESSING')
            if cancel else (current.refund_state if current else 'NOT_REQUESTED'),
        'change_allowed': not active and not cancel, 'cancel_allowed': not active and not cancel,
        'facts': facts, 'evidence_reference': 'cash-fare-operation://' + op.operation_id,
        'source_updated_at': timestamp, 'event_type': 'CASH_FARE_OPERATION_STATE_SYNC',
    })


def read(s, order):
    """Return current display facts only after the caller has checked ownership."""
    row = s.scalar(select(Life).where(Life.vertical == 'HOTEL', Life.order_id == order.order_id,
        Life.account_id == order.account_id))
    if not row or row.supplier_id != order.supplier_id:
        return None
    aware = lambda t: t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
    if aware(row.source_updated_at) < aware(order.updated_at):
        return None
    return (row.facts_json or {}).get('cash_after_sales')
