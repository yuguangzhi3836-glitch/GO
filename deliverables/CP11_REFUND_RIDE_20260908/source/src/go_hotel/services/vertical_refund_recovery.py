"""Durable whole-order refunds for the isolated rail and attraction executors.

Freeze the amount and capture list before money moves. A short database lease
limits concurrent retries; provider idempotency remains the money-side fence.
Unknown money outcomes stay pending and never restore a changeable order.
"""
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from go_hotel.autonomy.durable import db_now_ms, digest, transaction
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    VerticalRefundOperationRow as Operation, RailOrderRow, AttractionOrderRow,
    RailRefundRow, AttractionRefundRow, RailChangeQuoteRow,
    OmnichannelMoneyMovementRow as Movement, OmnichannelPaymentIntentRow as Intent,
    PaymentOrderRootRow as Root, MobilityRideOrderRow, MobilityRefundRow,
)
from go_hotel.domain.models import new_id
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
from go_hotel.services.vertical_money_bridge import vertical_money_bridge
from go_hotel.services import vertical_capacity as capacity

MODELS = {'RAIL': (RailOrderRow, RailRefundRow, 'TICKETED'),
          'ATTRACTION': (AttractionOrderRow, AttractionRefundRow, 'CONFIRMED'),
          'RIDE': (MobilityRideOrderRow, MobilityRefundRow, 'CONFIRMED')}
LEASE_MS = 30000


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _identity(row):
    return {'vertical': row.vertical, 'order_id': row.order_id, 'account_id': row.account_id,
            'quote': row.quote_json, 'adjustments': row.adjustment_ids_json}


def bind_quote(vertical, order, quote):
    """Bind consent to the current fulfillment identity, even at the same price.

    No personal details are returned: only their digest is part of the quote.
    Order status is deliberately excluded because an accepted refund moves it
    to REFUND_PENDING while retaining exactly this authorized identity.
    """
    context = {'vertical': vertical, 'order_id': order.order_id,
               'account_id': order.account_id, 'amount_minor': order.total_amount_minor,
               'currency': order.currency}
    if vertical == 'RAIL':
        context.update(prebook_id=order.prebook_id, journey=order.current_journey,
                       passengers=order.passengers, tickets=order.ticket_numbers,
                       supplier_reference=order.booking_reference)
    elif vertical == 'ATTRACTION':
        context.update(product_id=order.product_id, visit_date=order.visit_date,
                       session_time=order.session_time, quantity=order.quantity,
                       attendees=order.attendees, voucher=order.voucher_code,
                       supplier_reference=order.supplier_reference)
    elif vertical == 'RIDE':
        context.update(pickup=order.pickup, dropoff=order.dropoff,
                       pickup_at=order.pickup_at, vehicle_class=order.vehicle_class,
                       passengers=order.passengers, flight_no=order.flight_no,
                       supplier_reference=order.supplier_reference)
    else:
        raise ValueError('REFUND_VERTICAL_INVALID')
    values = {k: v for k, v in quote.items() if k not in {'quote_hash', 'order_context_hash'}}
    values['order_context_hash'] = digest(context)
    return {**values, 'quote_hash': digest(values)}


def _verify_context(op, order):
    # Older accepted operations retain their original evidence. Do not invent
    # a past consent or order fingerprint for them during recovery.
    if 'order_context_hash' in op.quote_json:
        current = bind_quote(op.vertical, order, op.quote_json)
        if current['quote_hash'] != op.quote_json.get('quote_hash'):
            raise ValueError('REFUND_ORDER_CONTEXT_CHANGED_REVIEW_REQUIRED')


def progress(vertical, account, order_id):
    if vertical not in MODELS:
        raise ValueError('REFUND_VERTICAL_INVALID')
    with SessionLocal() as s:
        order = s.get(MODELS[vertical][0], order_id)
        if not order or order.account_id != account:
            raise ValueError(f'{vertical}_ORDER_NOT_FOUND')
        op = s.get(Operation, (vertical, order_id))
        if not op:
            raise ValueError('REFUND_OPERATION_NOT_FOUND')
        _verify(op, account)
        return {'order_id': order_id, 'status': op.state,
                'refund_amount_minor': op.quote_json['refund_amount_minor'],
                'refund_fee_minor': op.quote_json['refund_fee_minor'],
                'currency': op.quote_json['currency'],
                'refund_to': 'ORIGINAL_PAYMENT_METHOD', 'external_live': False}


def _locked_order(s, vertical, order_id, account):
    model = MODELS[vertical][0]
    order = s.scalar(select(model).where(model.order_id == order_id).with_for_update())
    if not order or order.account_id != account:
        raise ValueError(f'{vertical}_ORDER_NOT_FOUND')
    return order


def _operation(s, vertical, order_id):
    return s.scalar(select(Operation).where(Operation.vertical == vertical,
                    Operation.order_id == order_id).with_for_update())


def _verify(row, account):
    if row.account_id != account or row.request_hash != digest(_identity(row)):
        raise ValueError('REFUND_OPERATION_INTEGRITY_INVALID')


def _confirmed_money_in(s, row, result):
    ids = result.get('money_movement_ids') or [result.get('money_movement_id')]
    if not ids or any(not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('REFUND_MONEY_NOT_CONFIRMED')
    roots = [(row.vertical + '_ORDER', row.order_id)]
    roots += [(row.vertical + '_CHANGE', x) for x in row.adjustment_ids_json]
    allowed = set()
    for business_type, business_id in roots:
        root = s.scalar(select(Root).where(Root.business_type == business_type,
                                           Root.business_id == business_id))
        intent = s.get(Intent, root.payment_intent_id) if root else None
        if not intent or intent.payer_id != row.account_id or intent.currency != row.quote_json['currency']:
            raise ValueError('REFUND_PAYMENT_OWNER_OR_CURRENCY_INVALID')
        allowed.add(root.payment_intent_id)
    total = 0
    for mid in ids:
        money = s.get(Movement, mid)
        parent = s.get(Movement, money.parent_movement_id) if money else None
        if (not money or money.state != 'CONFIRMED' or money.movement_type != 'REFUND'
                or money.root_payment_intent_id not in allowed or not parent
                or parent.movement_type != 'CAPTURE' or parent.state != 'CONFIRMED'
                or parent.root_payment_intent_id != money.root_payment_intent_id
                or money.currency != row.quote_json['currency']):
            raise ValueError('REFUND_MONEY_NOT_CONFIRMED')
        total += money.amount_minor
    if total != row.quote_json['refund_amount_minor']:
        raise ValueError('REFUND_CONFIRMED_AMOUNT_MISMATCH')
    return ids


def refund(vertical, account, order_id, quote_in, expected_quote_hash=None, existing_only=False):
    """quote_in receives the same locked session/order used to start the refund."""
    if vertical not in MODELS:
        raise ValueError('REFUND_VERTICAL_INVALID')
    with transaction(SessionLocal) as s:
        order = _locked_order(s, vertical, order_id, account)
        op = _operation(s, vertical, order_id)
        if op:
            _verify(op, account)
            if expected_quote_hash is not None and expected_quote_hash != op.quote_json.get('quote_hash'):
                raise ValueError('REFUND_QUOTE_CHANGED')
            _verify_context(op, order)
            if op.state == 'COMPLETED':
                if order.status != 'REFUNDED':
                    raise ValueError('REFUND_ORDER_STATE_INVALID')
                return dict(op.result_json)
            if order.status != 'REFUND_PENDING':
                raise ValueError('REFUND_ORDER_STATE_INVALID')
        else:
            if vertical == 'RIDE' and order.status == 'REFUNDED':
                # Pre-journal completed refunds are immutable receipts; retain
                # them without constructing a fictional past authorization.
                old = s.scalar(select(MobilityRefundRow).where(
                    MobilityRefundRow.order_id == order_id, MobilityRefundRow.vertical == 'RIDE',
                    MobilityRefundRow.status == 'REFUND_COMPLETED').order_by(MobilityRefundRow.created_at.desc()))
                if old:
                    return {'refund_id': old.refund_id, 'order_id': order_id, 'status': old.status,
                            'refund_fee_minor': old.fee_minor, 'refund_amount_minor': old.refund_amount_minor,
                            'currency': old.currency}
            if existing_only:
                raise ValueError('REFUND_OPERATION_NOT_FOUND')
            if order.status != MODELS[vertical][2]:
                raise ValueError(f'{vertical}_ORDER_NOT_REFUNDABLE')
            quote = bind_quote(vertical, order, quote_in(s, order))
            if expected_quote_hash is not None and expected_quote_hash != quote['quote_hash']:
                raise ValueError('REFUND_QUOTE_CHANGED')
            if type(quote['refund_amount_minor']) is not int or quote['refund_amount_minor'] <= 0:
                raise ValueError(f'{vertical}_NON_REFUNDABLE')
            adjustments = list(s.scalars(select(RailChangeQuoteRow.quote_id).where(
                RailChangeQuoteRow.order_id == order_id, RailChangeQuoteRow.status == 'EXECUTED'
            ).order_by(RailChangeQuoteRow.created_at, RailChangeQuoteRow.quote_id))) if vertical == 'RAIL' else []
            op = Operation(vertical=vertical, order_id=order_id, account_id=account,
                           state='PENDING', quote_json=quote, adjustment_ids_json=adjustments,
                           request_hash='', result_json=None, lease_token=None, lease_until_ms=0,
                           attempt=0, created_ms=db_now_ms(s), completed_ms=None)
            op.request_hash = digest(_identity(op))
            s.add(op)
            order.status = 'REFUND_PENDING'
            order.updated_at = _now()
            append_vertical_evidence(s, vertical, order_id, 'REFUND_REQUESTED', order.status,
                                     {'amount_minor': quote['refund_amount_minor'], 'request_hash': op.request_hash})
            project_vertical_lifecycle(s, vertical, order, f'{vertical.lower()}-refund-pending://{order_id}')
        now = db_now_ms(s)
        if op.lease_token and op.lease_until_ms > now:
            raise ValueError('REFUND_ALREADY_PROCESSING')
        token = uuid4().hex
        op.lease_token = token
        op.lease_until_ms = now + LEASE_MS
        op.attempt += 1
        quote = dict(op.quote_json)
        adjustments = list(op.adjustment_ids_json)
    try:
        prefix = vertical.lower()
        movement = vertical_money_bridge.refund_with_adjustments(
            vertical, order_id, adjustments, quote['refund_amount_minor'],
            f'{prefix}-refund://{order_id}', f'{prefix}-refund:{order_id}')
        if movement.get('state') != 'CONFIRMED':
            raise ValueError(f'{vertical}_REFUND_MONEY_NOT_CONFIRMED')
        with transaction(SessionLocal) as s:
            order = _locked_order(s, vertical, order_id, account)
            op = _operation(s, vertical, order_id)
            _verify(op, account)
            _verify_context(op, order)
            if op.state == 'COMPLETED':
                return dict(op.result_json)
            if op.lease_token != token or op.lease_until_ms <= db_now_ms(s):
                raise ValueError('REFUND_LEASE_LOST')
            if order.status != 'REFUND_PENDING':
                raise ValueError('REFUND_ORDER_STATE_INVALID')
            ids = _confirmed_money_in(s, op, movement)
            values = dict(refund_id=new_id(prefix+'_ref'), order_id=order_id,
                          refund_amount_minor=quote['refund_amount_minor'], currency=quote['currency'],
                          status='REFUND_COMPLETED', created_at=_now())
            if vertical == 'RIDE':
                values.update(vertical='RIDE', fee_minor=quote['refund_fee_minor'])
            else:
                values.update(refund_fee_minor=quote['refund_fee_minor'], completed_at=_now())
            record = MODELS[vertical][1](**values)
            s.add(record)
            result = {'refund_id': record.refund_id, 'order_id': order_id, 'status': record.status,
                      'refund_fee_minor': quote['refund_fee_minor'], 'refund_amount_minor': record.refund_amount_minor,
                      'currency': record.currency}
            if vertical in {'RAIL', 'ATTRACTION'}:
                capacity.release_all_in(s, vertical, order_id)
            order.status = 'REFUNDED'
            order.updated_at = _now()
            op.state = 'COMPLETED'
            op.result_json = result
            op.completed_ms = db_now_ms(s)
            op.lease_token = None
            op.lease_until_ms = 0
            facts = {**result, 'money_movement_ids': ids, 'money_movement_id': ids[0]}
            append_vertical_evidence(s, vertical, order_id, 'REFUND_COMPLETED', order.status, facts)
            project_vertical_lifecycle(s, vertical, order, 'refund:' + record.refund_id, facts=facts)
            return result
    except Exception:
        # Keep the frozen refund and REFUND_PENDING state. An ambiguous money
        # result is reconciled by the money ledger, never replaced with a new key.
        with transaction(SessionLocal) as s:
            _locked_order(s, vertical, order_id, account)
            op = _operation(s, vertical, order_id)
            if op and op.state == 'PENDING' and op.lease_token == token:
                op.lease_token = None
                op.lease_until_ms = 0
        raise
