"""Freeze one supplier decision before settling an isolated flight change.

An explicit quote_id identifies retries even after another change starts. Conflicting
facts cannot reverse a money decision. Unknown outcomes keep the order unavailable.
"""
from datetime import UTC, datetime
from uuid import uuid4
from sqlalchemy import select
from go_hotel.autonomy.durable import transaction, db_now_ms, digest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    FlightOrderRow as Order, FlightChangeQuoteRow as Quote, FlightChangeResolutionRow as Resolution,
    PaymentOrderRootRow as Root, OmnichannelPaymentIntentRow as Intent,
    OmnichannelMoneyMovementRow as Movement,
)
from go_hotel.services.vertical_money_bridge import vertical_money_bridge
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle

LEASE_MS = 30000


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _terms(s, o, q):
    from go_hotel.flight.changes import checked
    plan = checked(s, o, q)
    return {'order_id': o.order_id, 'account_id': o.account_id, 'quote_id': q.quote_id,
            'amount_minor': q.total_due_minor, 'currency': q.currency,
            'old_itinerary': o.current_itinerary, 'old_ticket_numbers': o.ticket_numbers,
            'old_pnr': o.pnr, 'old_total_minor': o.total_amount_minor,
            'party_count': len(o.passengers or []), 'plan_hash': plan.plan_hash,
            'changes': plan.plan_json['changes'], 'new_itinerary': plan.plan_json['new_itinerary']}


def _printable_token(value, maximum, code):
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum
            or value != value.strip() or not value.isprintable()):
        raise ValueError(code)
    return value


def _invalid_ticket(value):
    try:
        _printable_token(value, 64, 'FLIGHT_REISSUED_TICKETS_INVALID')
        return False
    except ValueError:
        return True


def _tickets(values, count):
    if (not isinstance(values, list) or len(values) != count
            or any(_invalid_ticket(x) for x in values)
            or len(set(values)) != len(values)):
        raise ValueError('FLIGHT_REISSUED_TICKETS_INVALID')
    return list(values)


def validate_existing_tickets(order):
    """Observation-only recovery cannot create an initial supplier issuance."""
    count = len(order.passengers or []) * len(order.current_itinerary or [])
    if not count:
        raise ValueError('FLIGHT_EXISTING_TICKETS_INVALID')
    _tickets(order.ticket_numbers, count)
    _printable_token(order.pnr, 16, 'FLIGHT_SUPPLIER_REFERENCE_INVALID')


def _identity(op):
    return {'quote_id': op.quote_id, 'order_id': op.order_id, 'account_id': op.account_id,
            'actor_id': op.actor_id, 'request': op.request_json, 'terms': op.terms_json}


def _event(s, o, kind, evidence, facts):
    o.updated_at = _now()
    append_vertical_evidence(s, 'FLIGHT', o.order_id, kind, o.status, facts)
    project_vertical_lifecycle(s, 'FLIGHT', o, evidence, facts=facts)


def _money_in(s, op, result):
    terms = op.terms_json
    if terms['amount_minor'] == 0:
        return None
    kind = 'CAPTURE' if op.request_json['state'] == 'TICKETED' else 'RELEASE'
    key = 'capture_id' if kind == 'CAPTURE' else 'release_id'
    root = s.scalar(select(Root).where(Root.business_type == 'FLIGHT_CHANGE', Root.business_id == op.quote_id))
    intent = s.get(Intent, root.payment_intent_id) if root else None
    money = s.get(Movement, result.get(key)) if result and result.get(key) else None
    auth = s.get(Movement, money.parent_movement_id) if money else None
    if (not intent or intent.payer_id != op.account_id or intent.currency != terms['currency']
            or not money or money.root_payment_intent_id != root.payment_intent_id
            or money.state != 'CONFIRMED' or money.movement_type != kind
            or money.amount_minor != terms['amount_minor'] or money.currency != terms['currency']
            or not auth or auth.movement_type != 'AUTHORIZATION' or auth.state != 'CONFIRMED'
            or auth.root_payment_intent_id != money.root_payment_intent_id
            or auth.amount_minor != terms['amount_minor'] or auth.currency != terms['currency']):
        raise ValueError('FLIGHT_CHANGE_MONEY_NOT_CONFIRMED')
    opposite = 'RELEASE' if kind == 'CAPTURE' else 'CAPTURE'
    if s.scalar(select(Movement.money_movement_id).where(
            Movement.root_payment_intent_id == root.payment_intent_id,
            Movement.movement_type == opposite,
            Movement.state.notin_(['FAILED', 'REJECTED', 'CANCELLED']))):
        raise ValueError('FLIGHT_CHANGE_MONEY_CONFLICT')
    return money.money_movement_id


def reconcile(order_id, state, evidence_reference, actor, supplier_reference, ticket_numbers, quote_id, output):
    _printable_token(evidence_reference, 512, 'EXTERNAL_STATE_ACTOR_AND_EVIDENCE_REQUIRED')
    _printable_token(actor, 128, 'EXTERNAL_STATE_ACTOR_AND_EVIDENCE_REQUIRED')
    state = state.upper()
    if state not in {'TICKETED', 'FAILED', 'UNKNOWN_EXTERNAL_STATE'}:
        raise ValueError('FLIGHT_EXTERNAL_STATE_INVALID')
    request = {'state': state, 'evidence_reference': evidence_reference,
               'supplier_reference': supplier_reference, 'ticket_numbers': ticket_numbers or []}
    with transaction(SessionLocal) as s:
        o = s.get(Order, order_id, with_for_update=True)
        if not o:
            raise ValueError('FLIGHT_ORDER_NOT_FOUND')
        if quote_id:
            q = s.get(Quote, quote_id, with_for_update=True)
            if not q or q.order_id != order_id:
                raise ValueError('FLIGHT_CHANGE_QUOTE_INVALID')
        else:
            # Once this order has resolution history, never guess which change a
            # delayed supplier response refers to. Callers must echo quote_id.
            if s.scalar(select(Resolution.quote_id).where(Resolution.order_id == order_id)):
                raise ValueError('FLIGHT_RESOLUTION_QUOTE_ID_REQUIRED')
            q = s.scalar(select(Quote).where(Quote.order_id == order_id,
                         Quote.status == 'PENDING_SUPPLIER').with_for_update())
        if q:
            if state not in {'TICKETED', 'FAILED'}:
                raise ValueError('FLIGHT_RESOLUTION_CONFLICT')
            if state == 'TICKETED':
                _printable_token(supplier_reference, 16, 'FLIGHT_RECONCILIATION_SUPPLIER_REFERENCE_REQUIRED')
                terms = _terms(s, o, q) if q.status == 'PENDING_SUPPLIER' else None
                if terms:
                    request['ticket_numbers'] = _tickets(ticket_numbers or [], len(terms['changes'])*len(o.passengers or []))
                    unchanged = [x for i,x in enumerate(o.ticket_numbers) if i//len(o.passengers) not in {c['leg_index'] for c in terms['changes']}]
                    if set(unchanged) & set(request['ticket_numbers']):raise ValueError('FLIGHT_REISSUED_TICKETS_INVALID')
            elif supplier_reference or ticket_numbers:
                raise ValueError('FLIGHT_FAILED_RESOLUTION_TICKET_INVALID')
            op = s.get(Resolution, q.quote_id, with_for_update=True)
            if op:
                if op.request_hash != digest(_identity(op)) or op.account_id != o.account_id or op.order_id != order_id:
                    raise ValueError('FLIGHT_RESOLUTION_INTEGRITY_INVALID')
                if op.request_json != request:
                    raise ValueError('FLIGHT_RESOLUTION_CONFLICT')
                if op.state == 'COMPLETED':
                    return dict(op.result_json)
                if _terms(s, o, q) != op.terms_json:
                    raise ValueError('FLIGHT_RESOLUTION_TERMS_INVALID')
            else:
                if o.status != 'UNKNOWN_EXTERNAL_STATE' or q.status != 'PENDING_SUPPLIER':
                    raise ValueError('FLIGHT_RECONCILIATION_NOT_REQUIRED')
                terms = _terms(s, o, q)
                if type(terms['amount_minor']) is not int or terms['amount_minor'] < 0 or q.currency != o.currency:
                    raise ValueError('FLIGHT_RESOLUTION_TERMS_INVALID')
                op = Resolution(quote_id=q.quote_id, order_id=order_id, account_id=o.account_id,
                    actor_id=actor, state='PENDING', request_json=request, terms_json=terms,
                    request_hash='', lease_token=None, lease_until_ms=0, attempt=0,
                    created_ms=db_now_ms(s), completed_ms=None, result_json=None)
                op.request_hash = digest(_identity(op))
                s.add(op)
                _event(s, o, 'CHANGE_RESOLUTION_REQUESTED', evidence_reference,
                       {'quote_id': q.quote_id, 'decision': state, 'actor': actor, 'request_hash': op.request_hash})
            if o.status != 'UNKNOWN_EXTERNAL_STATE' or q.status != 'PENDING_SUPPLIER':
                raise ValueError('FLIGHT_RESOLUTION_STATE_INVALID')
            if op.lease_token and op.lease_until_ms > db_now_ms(s):
                raise ValueError('FLIGHT_RESOLUTION_ALREADY_PROCESSING')
            token = uuid4().hex
            op.lease_token = token
            op.lease_until_ms = db_now_ms(s) + LEASE_MS
            op.attempt += 1
            quote_id = q.quote_id
            due = op.terms_json['amount_minor']
        else:
            # Legacy non-change state observations never dispatch money.
            if state == 'UNKNOWN_EXTERNAL_STATE':
                if o.status != 'TICKETED':
                    raise ValueError('FLIGHT_ILLEGAL_STATE_TRANSITION')
                o.status = state
                kind = 'EXTERNAL_STATE_UNKNOWN'
            else:
                if o.status != 'UNKNOWN_EXTERNAL_STATE':
                    raise ValueError('FLIGHT_RECONCILIATION_NOT_REQUIRED')
                if state == 'TICKETED':
                    validate_existing_tickets(o)
                o.status = state
                kind = 'RECONCILED_TO_' + state
            _event(s, o, kind, evidence_reference, {'actor': actor, 'native_status': o.status})
            return output(o)
    try:
        action = vertical_money_bridge.capture_adjustment if state == 'TICKETED' else vertical_money_bridge.release_adjustment
        money = action('FLIGHT', quote_id, due, evidence_reference) if due else None
        with transaction(SessionLocal) as s:
            o = s.get(Order, order_id, with_for_update=True)
            q = s.get(Quote, quote_id, with_for_update=True)
            op = s.get(Resolution, quote_id, with_for_update=True)
            if not o or not q or not op or op.request_hash != digest(_identity(op)) or op.request_json != request:
                raise ValueError('FLIGHT_RESOLUTION_INTEGRITY_INVALID')
            if op.state == 'COMPLETED':
                return dict(op.result_json)
            if op.lease_token != token or op.lease_until_ms <= db_now_ms(s):
                raise ValueError('FLIGHT_RESOLUTION_LEASE_LOST')
            if o.status != 'UNKNOWN_EXTERNAL_STATE' or q.status != 'PENDING_SUPPLIER' or _terms(s, o, q) != op.terms_json:
                raise ValueError('FLIGHT_RESOLUTION_STATE_INVALID')
            mid = _money_in(s, op, money)
            if state == 'TICKETED':
                from copy import deepcopy
                itinerary = deepcopy(op.terms_json['new_itinerary'])
                tickets = list(op.terms_json['old_ticket_numbers'])
                party = op.terms_json['party_count']
                if len(tickets) != len(itinerary)*party:
                    raise ValueError('FLIGHT_ORIGINAL_TICKET_ASSIGNMENTS_INVALID')
                for position, cell in enumerate(op.terms_json['changes']):
                    index = cell['leg_index']
                    itinerary[index]['supplier_reference'] = request['supplier_reference']
                    tickets[index*party:(index+1)*party] = request['ticket_numbers'][position*party:(position+1)*party]
                o.current_itinerary = itinerary
                o.total_amount_minor = op.terms_json['old_total_minor'] + due
                if len(itinerary) == 1:o.pnr = request['supplier_reference']
                o.ticket_numbers = tickets
                q.status = 'EXECUTED'
                kind = 'CHANGE_RECONCILED_TO_TICKETED'
            else:
                q.status = 'FAILED'
                kind = 'CHANGE_FAILED_RESTORED_TICKETED'
            o.status = 'TICKETED'
            _event(s, o, kind, evidence_reference, {'actor': op.actor_id, 'resume_actor': actor,
                   'quote_id': quote_id, 'money_movement_id': mid, 'decision': state,
                   'booking_reference': o.pnr, 'ticket_numbers': o.ticket_numbers})
            result = output(o)
            op.state = 'COMPLETED'
            op.result_json = result
            op.completed_ms = db_now_ms(s)
            op.lease_token = None
            op.lease_until_ms = 0
            return result
    except Exception:
        with transaction(SessionLocal) as s:
            s.get(Order, order_id, with_for_update=True)
            op = s.get(Resolution, quote_id, with_for_update=True)
            if op and op.state == 'PENDING' and op.lease_token == token:
                op.lease_token = None
                op.lease_until_ms = 0
        raise
