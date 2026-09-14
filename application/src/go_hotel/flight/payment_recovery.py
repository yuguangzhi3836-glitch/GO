"""Recover only the two opted-in flight commands from their durable roots.

No live provider is enabled here. Unknown attempts/movements remain fenced;
known simulator steps resume with the existing fixed keys and identities.
"""
from datetime import timezone
from sqlalchemy import select, text
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    FlightOrderRow as Order, FlightPrebookRow as Prebook, FlightOfferRow as Offer,
    FlightChangeQuoteRow as Quote, PaymentOrderRootRow as Root,
    PaymentOrderFactBindingRow as Binding, OmnichannelPaymentIntentRow as Intent,
    OmnichannelPaymentAttemptRow as Attempt, OmnichannelMoneyMovementRow as Movement,
)
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as checkout_bridge
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as change_bridge
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payments
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
from go_hotel.core.production_truth_gate import production_truth_required
from go_hotel.flight.changes import checked, consent


def _lock_sqlite(s):
    if s.bind.dialect.name == 'sqlite':
        s.execute(text('BEGIN IMMEDIATE'))


def _deny(boundary, code, *, safe=False):
    if safe:
        boundary.prove_no_effect()
    raise ValueError(code)


def payment_snapshot(s, order, *, quote=None):
    business_type = 'FLIGHT_CHANGE' if quote else 'FLIGHT_ORDER'
    business_id = quote.quote_id if quote else order.order_id
    amount = quote.total_due_minor if quote else order.total_amount_minor
    prefix = 'flight-change' if quote else 'flight'
    root = s.scalar(select(Root).where(Root.business_type == business_type, Root.business_id == business_id))
    intents = list(s.scalars(select(Intent).where(Intent.business_type == business_type, Intent.business_id == business_id)))
    if root is None:
        if intents:
            raise ValueError('FLIGHT_PAYMENT_ROOT_INTEGRITY_INVALID')
        return None
    if root.state != 'ACTIVE' or len(intents) != 1 or intents[0].payment_intent_id != root.payment_intent_id:
        raise ValueError('FLIGHT_PAYMENT_ROOT_INTEGRITY_INVALID')
    intent = intents[0]
    if (intent.payer_id, intent.amount_minor, intent.currency) != (order.account_id, amount, order.currency):
        raise ValueError('FLIGHT_PAYMENT_FACT_MISMATCH')
    binding = s.scalar(select(Binding).where(Binding.payment_intent_id == intent.payment_intent_id))
    if not binding or (binding.business_type, binding.business_id, binding.payer_id, binding.payee_id,
                       binding.amount_minor, binding.currency) != (business_type, business_id,
                       order.account_id, intent.payee_id, amount, order.currency):
        raise ValueError('FLIGHT_PAYMENT_BINDING_INVALID')
    if quote:
        base = s.scalar(select(Intent).where(Intent.business_type == 'FLIGHT_ORDER', Intent.business_id == order.order_id))
        if not base or (base.payer_id, base.payee_id, base.currency) != (intent.payer_id, intent.payee_id, intent.currency):
            raise ValueError('FLIGHT_CHANGE_PAYMENT_OWNER_MISMATCH')
    allowed = {'SUCCEEDED'} if quote else {'REQUIRES_CHANNEL_SELECTION', 'READY', 'CONTRACT_READY_NOT_EXTERNAL', 'SUCCEEDED'}
    if intent.state not in allowed:
        raise ValueError('FLIGHT_PAYMENT_RECONCILIATION_REQUIRED')
    attempts = list(s.scalars(select(Attempt).where(Attempt.payment_intent_id == intent.payment_intent_id)))
    if any(a.external_invoked or a.state not in {'SUCCEEDED', 'CONTRACT_READY_NOT_EXTERNAL'} for a in attempts):
        raise ValueError('FLIGHT_PAYMENT_RECONCILIATION_REQUIRED')
    pending = [a for a in attempts if a.state == 'CONTRACT_READY_NOT_EXTERNAL']
    if pending and (len(pending) != 1 or len(attempts) != 1 or intent.state != 'CONTRACT_READY_NOT_EXTERNAL'):
        raise ValueError('FLIGHT_PAYMENT_ATTEMPT_INTEGRITY_INVALID')
    if intent.state == 'CONTRACT_READY_NOT_EXTERNAL' and not pending:
        raise ValueError('FLIGHT_PAYMENT_ATTEMPT_INTEGRITY_INVALID')
    movements = list(s.scalars(select(Movement).where(Movement.root_payment_intent_id == intent.payment_intent_id)))
    result = {'intent_id': intent.payment_intent_id, 'state': intent.state,
              'pending_attempt_id': pending[0].payment_attempt_id if pending else None,
              'auth': None, 'cap': None, 'release': None}
    for movement in movements:
        suffix = {'AUTHORIZATION': 'auth', 'CAPTURE': 'cap', 'RELEASE': 'release'}.get(movement.movement_type)
        if (suffix is None or result[suffix] is not None or movement.state != 'CONFIRMED'
                or (movement.business_type, movement.business_id, movement.amount_minor, movement.currency)
                != (business_type, business_id, amount, order.currency)
                or movement.idempotency_key != f'{prefix}-{suffix}:{business_id}'):
            raise ValueError('FLIGHT_PAYMENT_MOVEMENT_RECONCILIATION_REQUIRED')
        result[suffix] = movement.money_movement_id
    if movements and intent.state != 'SUCCEEDED':
        raise ValueError('FLIGHT_PAYMENT_MOVEMENT_RECONCILIATION_REQUIRED')
    for movement in movements:
        if movement.movement_type in {'CAPTURE', 'RELEASE'} and movement.parent_movement_id != result['auth']:
            raise ValueError('FLIGHT_PAYMENT_MOVEMENT_PARENT_INVALID')
        if movement.movement_type == 'AUTHORIZATION' and movement.parent_movement_id is not None:
            raise ValueError('FLIGHT_PAYMENT_MOVEMENT_PARENT_INVALID')
    if result['cap'] and result['release']:
        raise ValueError('FLIGHT_PAYMENT_MOVEMENT_RECONCILIATION_REQUIRED')
    return result


def checkout(service, account, order_id, payment_method_id, boundary):
    from go_hotel.flight.service import now
    production_truth_required('FLIGHT', 'CHECKOUT')
    with SessionLocal() as s:
        _lock_sqlite(s)
        order = s.get(Order, order_id, with_for_update=True)
        if not order or order.account_id != account:
            _deny(boundary, 'FLIGHT_ORDER_NOT_FOUND', safe=True)
        snapshot = payment_snapshot(s, order)
        if snapshot is not None or order.status != 'PAYMENT_PENDING':
            boundary.before_effect()
        if order.status not in {'PAYMENT_PENDING', 'PAYMENT_AUTHORIZED', 'PAYMENT_CONFIRMED_AWAITING_SUPPLIER', 'TICKETED'}:
            _deny(boundary, 'FLIGHT_ORDER_PAYMENT_STATE_INVALID', safe=snapshot is None)
        if order.payment_method_id not in {None, payment_method_id} and snapshot is not None:
            _deny(boundary, 'FLIGHT_PAYMENT_METHOD_RECOVERY_CONFLICT')
        if snapshot and snapshot['release']:
            _deny(boundary, 'FLIGHT_PAYMENT_AUTHORIZATION_RELEASED')
        if order.status in {'TICKETED', 'PAYMENT_CONFIRMED_AWAITING_SUPPLIER'}:
            if not snapshot or not snapshot['cap']:
                _deny(boundary, 'FLIGHT_PAYMENT_RECONCILIATION_REQUIRED')
            return service._order(order)
        prebook = s.get(Prebook, order.prebook_id)
        offer = s.get(Offer, prebook.offer_id) if prebook else None
        if not offer:
            _deny(boundary, 'FLIGHT_PREBOOK_INVALID', safe=snapshot is None)
        source_id = offer.carrier_code or 'AIRLINE'
        boundary.before_effect()  # Before mutation/commit, including commit-ack loss.
        order.payment_method_id = payment_method_id
        order.status = 'PAYMENT_AUTHORIZED'
        order.updated_at = now()
        s.commit()
    if snapshot and snapshot['pending_attempt_id']:
        # Finish the already-created local simulator attempt, never execute a
        # new attempt or infer success for an external/unknown attempt.
        payments.simulate_result(snapshot['pending_attempt_id'], 'SUCCEEDED')
    tx = checkout_bridge.checkout_contract('FLIGHT', order_id, account, source_id,
                                          f'flight-offer://{order_id}', payment_method_id)
    with SessionLocal() as s:
        _lock_sqlite(s)
        order = s.get(Order, order_id, with_for_update=True)
        if not order or order.account_id != account:
            raise ValueError('FLIGHT_ORDER_NOT_FOUND')
        verified = payment_snapshot(s, order)
        if not verified or not verified['auth'] or not verified['cap'] or verified['release']:
            raise ValueError('FLIGHT_PAYMENT_MONEY_NOT_CONFIRMED')
        if (tx.get('payment_intent_id'), tx.get('authorization_id'), tx.get('capture_id')) != (
                verified['intent_id'], verified['auth'], verified['cap']):
            raise ValueError('FLIGHT_PAYMENT_RETURNED_RECEIPT_INVALID')
        if order.status in {'TICKETED', 'PAYMENT_CONFIRMED_AWAITING_SUPPLIER'}:
            return service._order(order)
        if order.status not in {'PAYMENT_PENDING', 'PAYMENT_AUTHORIZED'}:
            raise ValueError('FLIGHT_ORDER_PAYMENT_STATE_INVALID')
        order.status = 'PAYMENT_CONFIRMED_AWAITING_SUPPLIER'
        order.updated_at = now()
        append_vertical_evidence(s, 'FLIGHT', order_id, 'PAYMENT_CAPTURED', order.status,
            {'payment_intent_id':verified['intent_id'], 'capture_id':verified['cap'], 'external_live':False})
        s.flush()
        result = service._order(order)
        s.commit()
        return result


def execute_change(service, account, order_id, quote_id, confirmation, boundary):
    from go_hotel.flight.service import now
    production_truth_required('FLIGHT', 'EXECUTE_CHANGE')
    with SessionLocal() as s:
        _lock_sqlite(s)
        order = s.get(Order, order_id, with_for_update=True)
        quote = s.get(Quote, quote_id, with_for_update=True)
        if not order or order.account_id != account or not quote or quote.order_id != order_id:
            _deny(boundary, 'FLIGHT_CHANGE_QUOTE_INVALID', safe=True)
        snapshot = payment_snapshot(s, order, quote=quote)
        fresh = quote.status == 'QUOTED' and order.status == 'TICKETED' and snapshot is None
        if not fresh:
            boundary.before_effect()
        # This identified validation region performs only reads/pure checks.
        # Its proof is the code boundary and absence of a prior operation, not
        # the exception type or its eventual HTTP translation.
        try:
            plan = checked(s, order, quote, require_current=quote.status not in {'EXECUTED','FAILED'})
            consent(order, quote, plan, confirmation)
            expiry = quote.expires_at
            current = now()
            if expiry.tzinfo is not None:
                expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
            if current.tzinfo is not None:
                current = current.astimezone(timezone.utc).replace(tzinfo=None)
            if fresh and expiry < current:
                raise ValueError('FLIGHT_CHANGE_QUOTE_INVALID')
        except Exception:
            if fresh:
                boundary.prove_no_effect()
            raise
        if snapshot and snapshot['release']:
            _deny(boundary, 'FLIGHT_CHANGE_AUTHORIZATION_RELEASED_REQUOTE_REQUIRED')
        if quote.status == 'EXECUTED':
            if quote.total_due_minor and (not snapshot or not snapshot['cap']):
                raise ValueError('FLIGHT_CHANGE_MONEY_NOT_CONFIRMED')
            return service._order(order) | {'idempotent_replay': True}
        if quote.status == 'PENDING_SUPPLIER' and order.status == 'UNKNOWN_EXTERNAL_STATE':
            if quote.total_due_minor and (not snapshot or not snapshot['auth']):
                raise ValueError('FLIGHT_CHANGE_MONEY_NOT_CONFIRMED')
            return service._order(order) | {'idempotent_replay': True}
        resuming = quote.status == 'AUTHORIZATION_PENDING' and order.status == 'UNKNOWN_EXTERNAL_STATE'
        if not fresh and not resuming:
            _deny(boundary, 'FLIGHT_CHANGE_QUOTE_INVALID', safe=snapshot is None)
        boundary.before_effect()
        if fresh:
            quote.status = 'AUTHORIZATION_PENDING'
            order.status = 'UNKNOWN_EXTERNAL_STATE'
            order.updated_at = now()
            for other in s.scalars(select(Quote).where(Quote.order_id == order_id, Quote.quote_id != quote_id, Quote.status == 'QUOTED')):
                other.status = 'SUPERSEDED'
            append_vertical_evidence(s,'FLIGHT',order_id,'CHANGE_AUTHORIZATION_REQUESTED',order.status,
                {'quote_id':quote_id,'previous_pnr':order.pnr,'previous_ticket_numbers':order.ticket_numbers})
            project_vertical_lifecycle(s,'FLIGHT',order,'change-auth:'+quote_id,facts={'quote_id':quote_id})
        due = quote.total_due_minor
        s.commit()
    adjustment = change_bridge.prepare_adjustment('FLIGHT', order_id, quote_id, due, f'flight-change://{quote_id}')
    if adjustment and adjustment.get('released'):
        raise ValueError('FLIGHT_CHANGE_AUTHORIZATION_RELEASED_REQUOTE_REQUIRED')
    with SessionLocal() as s:
        _lock_sqlite(s)
        order = s.get(Order, order_id, with_for_update=True)
        quote = s.get(Quote, quote_id, with_for_update=True)
        if not order or order.account_id != account or not quote or quote.order_id != order_id:
            raise ValueError('FLIGHT_CHANGE_QUOTE_INVALID')
        snapshot = payment_snapshot(s, order, quote=quote)
        if due and (not snapshot or not snapshot['auth'] or snapshot['release'] or
                    not adjustment or adjustment.get('authorization_id') != snapshot['auth'] or
                    adjustment.get('payment_intent_id') != snapshot['intent_id']):
            raise ValueError('FLIGHT_CHANGE_MONEY_NOT_CONFIRMED')
        if quote.status == 'PENDING_SUPPLIER' and order.status == 'UNKNOWN_EXTERNAL_STATE':
            return service._order(order) | {'idempotent_replay': True}
        if order.status != 'UNKNOWN_EXTERNAL_STATE' or quote.status != 'AUTHORIZATION_PENDING':
            raise ValueError('FLIGHT_CHANGE_QUOTE_INVALID')
        checked(s, order, quote)
        quote.status = 'PENDING_SUPPLIER'
        order.updated_at = now()
        facts = {'quote_id':quote_id,'authorization_id':(adjustment or {}).get('authorization_id')}
        append_vertical_evidence(s,'FLIGHT',order_id,'CHANGE_SUBMITTED_AWAITING_SUPPLIER',order.status,facts)
        project_vertical_lifecycle(s,'FLIGHT',order,'change-pending:'+quote_id,facts=facts)
        s.flush()
        result = service._order(order)
        s.commit()
        return result
