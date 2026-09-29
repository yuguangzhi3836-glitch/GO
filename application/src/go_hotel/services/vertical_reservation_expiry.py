"""Unpaid reservation deadlines, serialized against payment on the native order.

Only new orders get a deadline. Any payment intent, including an uncertain or
failed attempt, retains its allocation for money reconciliation. Database time
and transactions determine the winner; the browser clock never releases seats.
"""
from datetime import datetime, UTC
from sqlalchemy import bindparam, select
from sqlalchemy.orm import object_session
from go_hotel.autonomy.durable import db_now_ms, digest, transaction
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    VerticalPaymentDeadlineRow as Deadline, OmnichannelPaymentIntentRow as Intent,
    RailOrderRow, AttractionOrderRow, MobilityRideOrderRow, MobilityRentalOrderRow,
)

HOLD_MS = 15 * 60 * 1000
MODELS = {'RAIL': RailOrderRow, 'ATTRACTION': AttractionOrderRow, 'RIDE': MobilityRideOrderRow, 'RENTAL': MobilityRentalOrderRow}

_PAYMENT_ID = select(Intent.payment_intent_id).where(
    Intent.business_type == bindparam('business_type'),
    Intent.business_id == bindparam('business_id')).limit(1)


def terms(row):
    return {k: getattr(row, k) for k in ('vertical', 'order_id', 'account_id', 'created_ms', 'expires_ms')}


def checked_in(s, vertical, order):
    row = s.get(Deadline, (vertical, order.order_id))
    if row and (row.account_id != order.account_id or row.terms_hash != digest(terms(row))):
        raise ValueError('PAYMENT_DEADLINE_INTEGRITY_INVALID')
    return row


def issue_in(s, vertical, order):
    if vertical not in MODELS or order.status != 'PAYMENT_PENDING':
        raise ValueError('PAYMENT_DEADLINE_TERMS_INVALID')
    if s.get(Deadline, (vertical, order.order_id)):
        raise ValueError('PAYMENT_DEADLINE_ALREADY_ISSUED')
    now = db_now_ms(s)
    row = Deadline(vertical=vertical, order_id=order.order_id, account_id=order.account_id,
        created_ms=now, expires_ms=now + HOLD_MS, state='OPEN')
    row.terms_hash = digest(terms(row))
    s.add(row)
    s.flush()


def projection(vertical, order):
    s = object_session(order)
    row = checked_in(s, vertical, order) if s else None
    return {'payment_deadline_ms': row.expires_ms if row else None,
            'unpaid_reservation_state': row.state if row else None}


def payment_in(s, vertical, order_id):
    return s.scalar(_PAYMENT_ID, {'business_type': vertical + '_ORDER', 'business_id': order_id})


def guard_payment_in(s, vertical, order):
    # Caller holds the native order lock, as do cancellation and expiration.
    row = checked_in(s, vertical, order)
    if not row:
        return  # No retroactive expiration for historical orders.
    if row.state in {'CANCELLED', 'EXPIRED', 'REVIEW'}:
        raise ValueError('RESERVATION_' + row.state + '_NOT_PAYABLE')
    started = payment_in(s, vertical, order.order_id)
    if row.state == 'PAYMENT_STARTED' and not started:
        raise ValueError('PAYMENT_DEADLINE_ROOT_INTEGRITY_INVALID')
    if not started and db_now_ms(s) >= row.expires_ms:
        raise ValueError('RESERVATION_EXPIRED_NOT_PAYABLE')


def finish_in(s, row, state, reason):
    row.state = state
    row.reason = reason
    row.finalized_ms = db_now_ms(s)
    s.flush()


def payment_started_in(s, vertical, order_id):
    row = s.get(Deadline, (vertical, order_id))
    if row and row.state == 'OPEN':
        if not payment_in(s, vertical, order_id):
            raise ValueError('PAYMENT_DEADLINE_ROOT_REQUIRED')
        finish_in(s, row, 'PAYMENT_STARTED', 'PAYMENT_INTENT_COMMITTED')


def guard_checkout_payment_in(s, vertical, order, account_id):
    """Caller holds the native order lock; reuse its transaction and connection."""
    if not order or order.account_id != account_id: raise ValueError('MOBILITY_ORDER_NOT_FOUND')
    if order.status != 'PAYMENT_PENDING': raise ValueError('MOBILITY_ORDER_NOT_PAYABLE')
    guard_payment_in(s, vertical, order)


def guard_checkout_payment(vertical, order_id, account_id):
    if vertical not in {'RIDE','RENTAL'}: return
    with transaction(SessionLocal) as s:
        order = s.get(MODELS[vertical], order_id, with_for_update=True)
        guard_checkout_payment_in(s, vertical, order, account_id)


def payment_started(vertical, order_id, account_id):
    if vertical not in {'RIDE','RENTAL'}: return
    with transaction(SessionLocal) as s:
        order = s.get(MODELS[vertical], order_id, with_for_update=True)
        confirm_payment_started_in(s, vertical, order, account_id)


def confirm_payment_started_in(s, vertical, order, account_id):
    """Same checks as payment_started; caller holds the native order lock."""
    if not order or order.account_id != account_id: raise ValueError('MOBILITY_ORDER_NOT_FOUND')
    if order.status != 'PAYMENT_PENDING': raise ValueError('MOBILITY_ORDER_NOT_PAYABLE')
    row = checked_in(s, vertical, order)
    if not row: raise ValueError('PAYMENT_DEADLINE_ROOT_REQUIRED')
    if row.state in {'CANCELLED','EXPIRED','REVIEW'}: raise ValueError('RESERVATION_' + row.state + '_NOT_PAYABLE')
    if not payment_in(s, vertical, order.order_id): raise ValueError('PAYMENT_DEADLINE_ROOT_REQUIRED')
    if row.state == 'OPEN': finish_in(s, row, 'PAYMENT_STARTED', 'PAYMENT_INTENT_COMMITTED')


def cancelled_in(s, vertical, order):
    row = checked_in(s, vertical, order)
    if row and row.state == 'OPEN':
        finish_in(s, row, 'CANCELLED', 'CUSTOMER_CANCELLED_UNPAID')


def expire_one(vertical, order_id):
    if vertical not in MODELS:
        raise ValueError('CAPACITY_VERTICAL_INVALID')
    with transaction(SessionLocal) as s:
        order = s.get(MODELS[vertical], order_id, with_for_update=True)
        row = s.get(Deadline, (vertical, order_id), with_for_update=True)
        if not row or row.state != 'OPEN':
            return 'UNCHANGED'
        if not order or row.account_id != order.account_id or row.terms_hash != digest(terms(row)):
            finish_in(s, row, 'REVIEW', 'PAYMENT_DEADLINE_INTEGRITY_INVALID')
            return 'REVIEW'
        if db_now_ms(s) < row.expires_ms:
            return 'NOT_DUE'
        if payment_in(s, vertical, order_id):
            finish_in(s, row, 'PAYMENT_STARTED', 'PAYMENT_RECONCILIATION_RETAINS_CAPACITY')
            return 'PAYMENT_STARTED'
        if order.status == 'CANCELLED':
            finish_in(s, row, 'CANCELLED', 'ORDER_ALREADY_CANCELLED')
            return 'CANCELLED'
        if order.status != 'PAYMENT_PENDING':
            finish_in(s, row, 'REVIEW', 'ORDER_STATE_REQUIRES_RECONCILIATION')
            return 'REVIEW'
        from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
        from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
        capacity_released = False
        if vertical in {'RAIL', 'ATTRACTION'}:
            from go_hotel.db.models import VerticalCapacityClaimRow as Claim
            claims = list(s.scalars(select(Claim).where(Claim.vertical == vertical,
                Claim.order_id == order_id, Claim.state == 'ALLOCATED')))
            quantity = len(order.passengers or []) if vertical == 'RAIL' else order.quantity
            if len(claims) != 1 or claims[0].slot != 'ORIGINAL' or claims[0].quantity != quantity:
                finish_in(s, row, 'REVIEW', 'CAPACITY_CLAIM_REQUIRES_RECONCILIATION')
                return 'REVIEW'
            from go_hotel.services.vertical_capacity import release_all_in
            release_all_in(s, vertical, order_id)
            capacity_released = True
        elif getattr(order, 'supplier_reference', None):
            finish_in(s, row, 'REVIEW', 'MOBILITY_SUPPLIER_REFERENCE_REQUIRES_RECONCILIATION')
            return 'REVIEW'
        order.status = 'CANCELLED'
        order.updated_at = datetime.now(UTC).replace(tzinfo=None)
        finish_in(s, row, 'EXPIRED', 'UNPAID_DEADLINE_REACHED')
        reference = 'unpaid-expiry://' + order_id
        facts = {'unpaid': True, 'capacity_released': capacity_released, 'payment_deadline_ms': row.expires_ms,
                 'deadline_terms_hash': row.terms_hash}
        append_vertical_evidence(s, vertical, order_id, 'UNPAID_RESERVATION_EXPIRED', order.status, facts)
        project_vertical_lifecycle(s, vertical, order, reference, facts=facts)
        return 'EXPIRED'


def expire_due(limit=100):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('EXPIRY_BATCH_LIMIT_INVALID')
    # Candidate reads take no row locks. Each bounded operation reacquires the
    # native order before its deadline, matching the checkout lock order.
    with SessionLocal() as s:
        candidates = list(s.execute(select(Deadline.vertical, Deadline.order_id).where(
            Deadline.state == 'OPEN', Deadline.expires_ms <= db_now_ms(s)).order_by(
                Deadline.expires_ms, Deadline.vertical, Deadline.order_id).limit(limit)))
    result = {'scanned': len(candidates), 'expired': 0, 'review': 0, 'payment_started': 0, 'errors': []}
    for vertical, order_id in candidates:
        try:
            state = expire_one(vertical, order_id).lower()
            if state in result:
                result[state] += 1
        except Exception as exc:
            # Keep the transaction rolled back; a transient failure must never
            # fabricate cancellation or prevent other candidates progressing.
            result['errors'].append({'vertical': vertical, 'order_id': order_id, 'error': type(exc).__name__})
    return result
