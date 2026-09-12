"""Resumable supplier and money phases for an explicitly accepted cash quote."""
from copy import deepcopy
import asyncio
from sqlalchemy import select
from go_hotel.services.catalog_cash_fare import (
    transaction, SessionLocal, Order, Operation, Quote, Claim, OrderChangeRow, ChangeQuoteRow,
    Root, Intent, Binding, PaymentRow, RefundRow, Movement, OfferRow,
    now, ident, aware, digest, settings, funds, remedy, checked_quote, context, base_quote,
    lock, public, offer_facts, cancellation_terms, TERMINAL,
)
from go_hotel.services.catalog_stay_credit import payment_outcome
from go_hotel.services import hotel_change_policy

def now():
    from go_hotel.services.catalog_cash_fare import now as clock
    return clock()


def project_operation(s, order, op):
    from go_hotel.services.catalog_cash_trip_projection import project
    return project(s, order, op, now())


def authorize(s, order, op, b):
    amount = b['amount_due_minor']
    if not amount: op.state = 'READY'; return
    outcome = op.plan_json['payment_outcome']
    if outcome == 'DECLINED':
        op.state = 'PAYMENT_DECLINED'; release_claim(s, order, op, failed=True); return
    original = s.scalar(select(Root).where(Root.business_type == 'HOTEL_ORDER', Root.business_id == order.order_id))
    binding = s.scalar(select(Binding).where(Binding.payment_intent_id == original.payment_intent_id)) if original else None
    if not binding: raise ValueError('ORIGINAL_PAYMENT_BINDING_REQUIRED')
    if s.scalar(select(Root).where(Root.business_type == 'HOTEL_CHANGE', Root.business_id == op.quote_id)):
        raise ValueError('CHANGE_ROOT_RECONCILIATION_REQUIRED')
    iid, t = ident('opi'), now()
    prefix = 'cash-fare:' + op.operation_id
    fact = {'business_type': 'HOTEL_CHANGE', 'business_id': op.quote_id, 'payer_id': order.account_id,
        'payee_id': order.supplier_id, 'amount_minor': amount, 'currency': order.currency,
        'quote_hash': op.plan_json['quote_hash'], 'source_decision_id': binding.source_decision_id}
    s.add(Intent(payment_intent_id=iid, business_type='HOTEL_CHANGE', business_id=op.quote_id,
        payer_id=order.account_id, payee_id=order.supplier_id, operation='PAY', amount_minor=amount,
        currency=order.currency, channel_priority_json=['LOCAL_MARKET'], selected_channel='LOCAL_MARKET',
        state='SUCCEEDED', idempotency_key=prefix + ':intent', automatic_fallback_allowed=False,
        user_channel_consent_at=t, created_at=t, updated_at=t))
    s.flush()
    s.add(Root(payment_order_root_id=ident('por'), business_type='HOTEL_CHANGE', business_id=op.quote_id,
        payment_intent_id=iid, legal_entity_id=original.legal_entity_id, state='ACTIVE',
        root_hash=digest({'business_type': 'HOTEL_CHANGE', 'business_id': op.quote_id,
            'payment_intent_id': iid, 'legal_entity_id': original.legal_entity_id}), created_at=t))
    s.add(Binding(payment_order_fact_binding_id=ident('pofb'), payment_intent_id=iid, business_type='HOTEL_CHANGE',
        business_id=op.quote_id, payer_id=order.account_id, payee_id=order.supplier_id, amount_minor=amount,
        currency=order.currency, legal_entity_id=original.legal_entity_id, source_decision_id=binding.source_decision_id,
        request_fingerprint=digest(fact), order_fact_hash=digest(fact), evidence_reference='cash-fare-quote://' + op.quote_id, created_at=t))
    s.flush()
    auth = funds.money.create_in_session(s, iid, {'movement_type': 'AUTHORIZATION', 'amount_minor': amount,
        'mode': 'CONTRACT_SIMULATOR', 'evidence': ['cash-fare-quote://' + op.quote_id]}, prefix + ':auth', 'catalog-cash-fare')
    op.payment_json = {'payment_intent_id': iid, 'authorization_id': auth['money_movement_id'], 'outcome': outcome}
    op.state = 'READY'


def release_claim(s, order, op, failed=False):
    claim = s.get(Claim, order.order_id)
    if not claim or claim.operation_id != op.operation_id: raise ValueError('CASH_FARE_CLAIM_CHANGED')
    s.delete(claim)
    order.status = 'CONFIRMED'; order.version += 1; order.updated_at = now()
    if failed:
        change = s.get(OrderChangeRow, op.operation_id)
        if change: change.status = 'FAILED'


def ensure_actor(q, actor):
    if actor is None:
        if settings.app_env.lower() not in {'local', 'test', 'demo'}: raise ValueError('CUSTOMER_FARE_CONSENT_REQUIRED')
        return 'LOCAL_CASH_FARE_FIXTURE'
    if actor != q.payload_json['account_id']: raise ValueError('OWN_CASH_FARE_QUOTE_REQUIRED')
    return actor


async def start(oid, qid, expected_hash, consent, actor, token='pm_success', action=None):
    funds.require_isolated()
    outcome = payment_outcome(token)
    with transaction() as s:
        # Same order-first lock ordering as credit conversion and supplier review.
        order = s.get(Order, oid, with_for_update=True, populate_existing=True)
        q = checked_quote(s, qid)
        if q.order_id != oid or action is not None and q.action != action: raise ValueError('OWN_CASH_FARE_QUOTE_REQUIRED')
        owner = ensure_actor(q, actor)
        fixture = actor is None and expected_hash is None and consent is False
        if not fixture and (expected_hash != q.quote_hash or consent is not True):
            raise ValueError('CURRENT_CASH_FARE_QUOTE_CONSENT_REQUIRED')
        old = s.scalar(select(Operation).where(Operation.quote_id == qid))
        if old:
            _, old, _ = lock(s, old.operation_id)
            if (old.plan_json['actor_id'], old.plan_json['payment_outcome']) != (owner, outcome):
                raise ValueError('CASH_FARE_REQUEST_CONFLICT')
            return public(old)
        if aware(q.expires_at) <= now(): raise ValueError('CASH_FARE_QUOTE_EXPIRED')
        order, offer, snap = context(s, oid)
        current = base_quote(s, order, offer, snap)
        b = q.payload_json
        if any(current[k] != b.get(k) for k in current): raise ValueError('CASH_FARE_QUOTE_STALE')
        if q.action == 'CANCEL':
            terms = cancellation_terms(order, b['check_in'], b, now())
            if terms['fee_basis_points'] != b['fee_basis_points']: raise ValueError('CANCELLATION_FEE_CHANGED_REQUOTE_REQUIRED')
        else:
            hotel_change_policy.require_zero_fee(b)
            hotel_change_policy.require_window(b['order_created_at'], b['new_check_in'], now(),
                b['rules']['timezone'], b['rules']['check_in_hour'])
            new_offer = s.get(OfferRow, b['new_offer']['offer_id'])
            if not new_offer or offer_facts(new_offer) != b['new_offer']: raise ValueError('CHANGE_OFFER_FACT_CHANGED')
            if aware(q.expires_at) > aware(new_offer.expires_at): raise ValueError('CHANGE_PRICE_LOCK_CHANGED')
        opid, t = ident('cfo'), now()
        plan = {'quote': deepcopy(b), 'quote_hash': q.quote_hash, 'actor_id': owner, 'payment_outcome': outcome,
            'acceptance_kind': 'ISOLATED_FIXTURE' if actor is None else 'CUSTOMER_EXPLICIT'}
        op = Operation(operation_id=opid, order_id=oid, quote_id=qid, state='AUTH_PENDING' if q.action == 'CHANGE' else 'READY',
            plan_json=plan, plan_hash=digest(plan), created_at=t, updated_at=t)
        s.add_all([op, Claim(order_id=oid, operation_id=opid)])
        order.status = 'CHANGE_PENDING' if q.action == 'CHANGE' else 'CANCEL_PENDING'
        order.version += 1; order.updated_at = t
        if q.action == 'CHANGE':
            s.add(OrderChangeRow(change_id=opid, order_id=oid, quote_id=qid, new_check_in=b['new_check_in'],
                new_check_out=b['new_check_out'], additional_payment_minor=b['amount_due_minor'], status='SUPPLIER_PROCESSING', created_at=t))
        s.flush()
        remedy.event(s, oid, 'CASH_FARE_ACCEPTED', owner, {'operation_id': opid, 'quote_id': qid,
            'quote_hash': q.quote_hash, 'plan_hash': op.plan_hash, 'acceptance_kind': plan['acceptance_kind']})
        project_operation(s, order, op)
    return await advance(opid)


async def advance(opid):
    """Only a never-dispatched READY operation may send an instruction."""
    funds.require_isolated()
    dispatch = False
    with transaction() as s:
        order, op, b = lock(s, opid)
        if op.state == 'AUTH_PENDING':
            authorize(s, order, op, b)
            project_operation(s, order, op)
        if op.state == 'READY':
            conn = remedy.connector(s, order)
            op.state = 'SUPPLIER_PENDING'; op.updated_at = now(); dispatch = True
            remedy.event(s, op.order_id, 'CASH_FARE_SUPPLIER_DISPATCH_PLANNED', op.plan_json['actor_id'],
                {'operation_id': opid, 'action': b['action'], 'plan_hash': op.plan_hash})
            project_operation(s, order, op)
        elif op.state not in {'CAPTURE_PENDING', 'REFUND_PENDING', 'REJECTED_RELEASE_PENDING'}:
            return public(op)
    if dispatch:
        try:
            if b['action'] == 'CANCEL':
                result = await asyncio.wait_for(conn.cancel(b['supplier_confirmation_no']), settings.connector_timeout_seconds)
                observed = {'status': 'CONFIRMED' if result == 'CANCELLED' else 'UNKNOWN', 'confirmation': result}
            else:
                reference = await asyncio.wait_for(conn.change_locked(b['supplier_confirmation_no'], b['new_check_in'], b['new_check_out'], b['prebook'], opid), settings.connector_timeout_seconds)
                observed = {'status': 'CONFIRMED', 'confirmation': reference}
        except BaseException as exc:
            with transaction() as s:
                order, op, _ = lock(s, opid)
                if op.state == 'SUPPLIER_PENDING': op.state = 'UNKNOWN_SUPPLIER'; op.updated_at = now()
                project_operation(s, order, op)
                result = public(op)
            if isinstance(exc, Exception): return result
            raise
        with transaction() as s:
            order, op, b = lock(s, opid)
            accept_observation(s, order, op, b, observed)
    return complete(opid)


def accept_observation(s, order, op, b, observed):
    if op.state not in {'SUPPLIER_PENDING', 'UNKNOWN_SUPPLIER'}: return
    if observed['status'] == 'CONFIRMED':
        if not observed.get('confirmation'): raise ValueError('SUPPLIER_FARE_REFERENCE_REQUIRED')
        op.supplier_reference = observed['confirmation']
        if b['action'] == 'CANCEL':
            op.state = 'REFUND_PENDING'; order.status = 'CANCELLED'; order.version += 1; order.updated_at = now()
            remedy.event(s, order.order_id, 'CANCEL_CONFIRMED', op.plan_json['actor_id'], {'operation_id': op.operation_id, 'quote_id': op.quote_id})
        else: op.state = 'CAPTURE_PENDING'
    elif observed['status'] == 'REJECTED' and b['action'] == 'CHANGE': op.state = 'REJECTED_RELEASE_PENDING'
    else: op.state = 'UNKNOWN_SUPPLIER'
    op.updated_at = now()
    project_operation(s, order, op)


def complete(opid):
    with transaction() as s:
        order, op, b = lock(s, opid)
        key = 'cash-fare:' + opid
        if op.state == 'REFUND_PENDING':
            for line in b['refund_lines']:
                movement = funds.money.create_in_session(s, line['payment_intent_id'], {'movement_type': 'REFUND',
                    'parent_movement_id': line['capture_id'], 'amount_minor': line['amount_minor'], 'mode': 'CONTRACT_SIMULATOR',
                    'evidence': ['cash-fare-cancel://' + opid + '/' + op.plan_json['quote_hash']]}, key + ':refund:' + line['capture_id'], 'catalog-cash-fare')
                cap = s.get(Movement, line['capture_id'])
                # The legacy receipt can refer only to an actual original PaymentRow.
                if cap.business_type == 'HOTEL_ORDER':
                    pay = s.scalar(select(PaymentRow).where(PaymentRow.order_id == order.order_id,
                        PaymentRow.payment_type == 'ORIGINAL_BOOKING', PaymentRow.status == 'CAPTURED'))
                    s.add(RefundRow(refund_id=ident('ref'), order_id=order.order_id, payment_id=pay.payment_id,
                        amount_minor=line['amount_minor'], currency=order.currency, status='COMPLETED',
                        provider_refund_id=movement['money_movement_id'], created_at=now(), completed_at=now()))
            op.state = 'COMPLETED'
            remedy.event(s, order.order_id, 'REFUND_COMPLETED', op.plan_json['actor_id'],
                {'operation_id': opid, 'amount_minor': b['refund_amount_minor'], 'quote_hash': op.plan_json['quote_hash']})
            # Retain the cancellation claim: the fee remainder is not free to refund again.
        elif op.state in {'CAPTURE_PENDING', 'REJECTED_RELEASE_PENDING'}:
            rejected = op.state == 'REJECTED_RELEASE_PENDING'
            if b['amount_due_minor']:
                payment = op.payment_json
                if not payment: raise ValueError('CHANGE_AUTHORIZATION_REQUIRED')
                if not rejected and payment['outcome'] != 'SUCCESS': return public(op)
                funds.money.create_in_session(s, payment['payment_intent_id'], {'movement_type': 'RELEASE' if rejected else 'CAPTURE',
                    'parent_movement_id': payment['authorization_id'], 'amount_minor': b['amount_due_minor'],
                    'mode': 'CONTRACT_SIMULATOR', 'evidence': ['cash-fare-result://' + opid]}, key + (':release' if rejected else ':cap'), 'catalog-cash-fare')
            release_claim(s, order, op, failed=rejected)
            op.state = 'REJECTED' if rejected else 'COMPLETED'
            if not rejected:
                change = s.get(OrderChangeRow, opid)
                change.status = 'CONFIRMED'; change.supplier_confirmation_no = op.supplier_reference; change.confirmed_at = now()
                order.supplier_confirmation_no = op.supplier_reference
                remedy.event(s, order.order_id, 'CHANGE_CONFIRMED', op.plan_json['actor_id'],
                    {'change_id': opid, 'new_check_in': b['new_check_in'], 'new_check_out': b['new_check_out'], 'amount_paid_minor': b['amount_due_minor']})
        op.updated_at = now()
        project_operation(s, order, op)
        return public(op)


async def reconcile(oid, opid, actor=None):
    funds.require_isolated()
    with transaction() as s:
        order, op, b = lock(s, opid)
        if op.order_id != oid: raise ValueError('CASH_FARE_OPERATION_NOT_FOUND')
        ensure_actor(checked_quote(s, op.quote_id), actor)
        phase = op.state
        if phase in TERMINAL: return public(op)
        conn = remedy.connector(s, order)
    if phase in {'SUPPLIER_PENDING', 'UNKNOWN_SUPPLIER'}:
        try:
            if b['action'] == 'CANCEL':
                value = await asyncio.wait_for(conn.status(b['supplier_confirmation_no']), settings.connector_timeout_seconds)
                observed = {'status': 'CONFIRMED' if value == 'CANCELLED' else 'UNKNOWN', 'confirmation': value}
            else:
                observed = await asyncio.wait_for(conn.lookup_change(opid), settings.connector_timeout_seconds)
                if observed['status'] == 'CONFIRMED' and any(observed.get(k) != b[v] for k, v in
                    [('original_confirmation', 'supplier_confirmation_no'), ('check_in', 'new_check_in'), ('check_out', 'new_check_out')]):
                    observed = {'status': 'UNKNOWN', 'confirmation': None}
        except Exception:
            with SessionLocal() as s: return public(s.get(Operation, opid))
        with transaction() as s:
            order, op, b = lock(s, opid)
            accept_observation(s, order, op, b, observed)
        return complete(opid)
    return await advance(opid)


def retry_payment(oid, opid, expected_hash, consent, token, actor=None):
    funds.require_isolated()
    outcome = payment_outcome(token)
    with transaction() as s:
        order, op, b = lock(s, opid)
        if op.order_id != oid: raise ValueError('CASH_FARE_OPERATION_NOT_FOUND')
        ensure_actor(checked_quote(s, op.quote_id), actor)
        if expected_hash != op.plan_json['quote_hash'] or consent is not True: raise ValueError('CURRENT_CASH_FARE_QUOTE_CONSENT_REQUIRED')
        if op.state == 'COMPLETED': return public(op)
        if op.state != 'CAPTURE_PENDING' or not op.payment_json: raise ValueError('CONFIRMED_CHANGE_PAYMENT_RETRY_REQUIRED')
        op.payment_json = {**op.payment_json, 'outcome': outcome}
        remedy.event(s, oid, 'CASH_CHANGE_PAYMENT_RETRY_ACCEPTED', actor or 'LOCAL_CASH_FARE_FIXTURE',
            {'operation_id': opid, 'quote_hash': expected_hash, 'outcome': outcome})
    return complete(opid)
