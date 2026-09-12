"""Quoted ordinary cash after-sales with one durable owner per hotel order.

External uncertainty is queried, never retried as a new supplier instruction.
Money and final business facts share a transaction in the isolated executor.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
from sqlalchemy import select

from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    CatalogCashFareQuoteRow as Quote, CatalogCashFareOperationRow as Operation,
    CatalogCashFareClaimRow as Claim, OrderRow as Order, OfferRow, PrebookRow,
    ChangeQuoteRow, CancellationQuoteRow, OrderChangeRow, PaymentRow, RefundRow,
    StayCreditRow, CatalogCreditAllocationRow, SupplierFaultCaseRow,
    PaymentOrderRootRow as Root, OmnichannelPaymentIntentRow as Intent,
    OmnichannelMoneyMovementRow as Movement, PaymentOrderFactBindingRow as Binding,
)
from go_hotel.services.alipay_safeguarded_settlement import transaction
from go_hotel.services.hosted_direct_booking import ident, now
from go_hotel.services.hosted_reservation_operations import aware
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services import hosted_money as funds, catalog_supplier_remedy as remedy
from go_hotel.services.catalog_fare_snapshot import order_snapshot, cancellation_terms, offer_facts
from go_hotel.services.hotel_money_bridge import hotel_money_bridge
from go_hotel.services import hotel_change_policy

POLICY = 'NET_CASH_LESS_FORFEITED_CHANGE_VALUE_INCLUDING_PAID_CHANGE_FEES'
TERMINAL = {'COMPLETED', 'REJECTED', 'PAYMENT_DECLINED'}


def context(s, oid, available=True):
    order = s.get(Order, oid, with_for_update=True, populate_existing=True)
    if not order: raise ValueError('ORDER_NOT_FOUND')
    if s.get(CatalogCreditAllocationRow, oid): raise ValueError('CREDIT_ORDER_AFTERSALES_REQUIRED')
    if s.scalar(select(StayCreditRow).where(StayCreditRow.original_order_id == oid)):
        raise ValueError('CREDIT_SOURCE_ORDER_FROZEN')
    if s.scalar(select(SupplierFaultCaseRow).where(SupplierFaultCaseRow.order_id == oid, SupplierFaultCaseRow.status != 'COMPLETED')):
        raise ValueError('SUPPLIER_REMEDY_ORDER_FROZEN')
    snap = order_snapshot(s, order)
    if order.total_amount_minor != snap.snapshot_json['offer']['amount_minor']:
        raise ValueError('ORIGINAL_ROOM_VALUE_RECONCILIATION_REQUIRED')
    if available and (order.status != 'CONFIRMED' or s.get(Claim, oid)):
        raise ValueError('CASH_ORDER_AFTERSALES_IN_PROGRESS')
    pb = s.get(PrebookRow, order.prebook_id)
    offer = s.get(OfferRow, pb.offer_id)
    return order, offer, snap


def facts(s, order, offer):
    gross, prior, lines = remedy.paid_facts(s, order)
    changes = s.scalars(select(OrderChangeRow).where(OrderChangeRow.order_id == order.order_id)
        .order_by(OrderChangeRow.confirmed_at, OrderChangeRow.change_id)).all()
    current_value = offer.total_amount_minor
    fees = forfeited = 0
    ci, co = offer.check_in, offer.check_out
    confirmed_quotes = set()
    for change in changes:
        if change.status == 'FAILED': continue
        if change.status != 'CONFIRMED': raise ValueError('ORDER_CHANGE_RECONCILIATION_REQUIRED')
        q = s.get(ChangeQuoteRow, change.quote_id)
        if not q or q.order_id != order.order_id or change.additional_payment_minor != q.amount_due_minor:
            raise ValueError('CHANGE_PAYMENT_FACT_RECONCILIATION_REQUIRED')
        accepted = s.scalar(select(Operation).where(Operation.quote_id == q.quote_id))
        if accepted:
            _, accepted, quoted = lock(s, accepted.operation_id)
            fields = ['old_value_minor', 'new_value_minor', 'fare_difference_minor', 'change_fee_minor',
                'amount_due_minor', 'new_check_in', 'new_check_out']
            if accepted.state != 'COMPLETED' or any(getattr(q, k) != quoted[k] for k in fields):
                raise ValueError('ACCEPTED_CHANGE_FACT_RECONCILIATION_REQUIRED')
        root = s.scalar(select(Root).where(Root.business_type == 'HOTEL_CHANGE', Root.business_id == q.quote_id))
        caps = s.scalars(select(Movement).where(Movement.root_payment_intent_id == root.payment_intent_id,
            Movement.movement_type == 'CAPTURE')).all() if root else []
        if sum(c.amount_minor for c in caps) != q.amount_due_minor or any(c.state != 'CONFIRMED' for c in caps):
            raise ValueError('CONFIRMED_CHANGE_CAPTURE_REQUIRED')
        forfeited += max(current_value - q.new_value_minor, 0)
        current_value = q.new_value_minor
        fees += q.change_fee_minor
        ci, co = change.new_check_in, change.new_check_out
        confirmed_quotes.add(q.quote_id)
    # An orphan capture or unconsumed authorization cannot disappear from a quote.
    for root in remedy.roots(s, order):
        moves = s.scalars(select(Movement).where(Movement.root_payment_intent_id == root.payment_intent_id)).all()
        if root.business_type == 'HOTEL_CHANGE' and root.business_id not in confirmed_quotes and any(m.movement_type == 'CAPTURE' for m in moves):
            raise ValueError('ORPHAN_CHANGE_CAPTURE_RECONCILIATION_REQUIRED')
        for auth in [m for m in moves if m.movement_type == 'AUTHORIZATION']:
            if sum(m.amount_minor for m in moves if m.parent_movement_id == auth.money_movement_id and m.movement_type in {'CAPTURE', 'RELEASE'}) != auth.amount_minor:
                raise ValueError('UNSETTLED_AUTHORIZATION_RECONCILIATION_REQUIRED')
    if gross != current_value + fees + forfeited:
        raise ValueError('HISTORICAL_CHANGE_VALUE_RECONCILIATION_REQUIRED')
    return {'gross_paid_minor': gross, 'prior_refund_minor': prior, 'paid_amount_minor': gross - prior,
        'current_room_value_minor': current_value, 'paid_change_fees_minor': fees,
        'forfeited_change_value_minor': forfeited,
        'available_refund_lines': lines, 'check_in': ci, 'check_out': co}


def base_quote(s, order, offer, snap):
    b = facts(s, order, offer)
    rules = snap.snapshot_json['version']['rules']
    if (b['paid_change_fees_minor'] or b['forfeited_change_value_minor']) and rules.get('cash_cancellation_value_basis') != POLICY:
        raise ValueError('HISTORICAL_CHANGE_FEE_CANCELLATION_POLICY_REQUIRED')
    return {**b, 'order_id': order.order_id, 'account_id': order.account_id, 'order_version': order.version,
        'currency': order.currency, 'supplier_confirmation_no': order.supplier_confirmation_no,
        'order_snapshot_hash': snap.snapshot_hash, 'rule_hash': snap.snapshot_json['version']['rule_hash'],
        'rule_version_id': snap.version_id, 'rules': deepcopy(rules),
        'order_created_at': snap.snapshot_json['order_created_at'], 'data_mode': 'SIMULATION',
        **hotel_change_policy.terms(snap.snapshot_json['order_created_at'])}


def quote_public(q):
    b = deepcopy(q.payload_json)
    for key in ['account_id', 'available_refund_lines', 'refund_lines', 'prebook', 'new_offer', 'rules']:
        b.pop(key, None)
    return {**b, 'quote_id': q.quote_id, 'change_quote_id': q.quote_id if q.action == 'CHANGE' else None,
        'quote_hash': q.quote_hash, 'expires_at': aware(q.expires_at).isoformat(), 'external_live': False}


def save_quote(s, action, b, exp, qid):
    body = {**b, 'action': action, 'quote_id': qid, 'expires_at': aware(exp).isoformat()}
    q = Quote(quote_id=qid, order_id=b['order_id'], action=action, payload_json=body,
        quote_hash=digest(body), expires_at=exp, created_at=now())
    s.add(q)
    remedy.event(s, b['order_id'], 'CASH_FARE_QUOTED', 'fare-engine', {'quote_id': qid, 'quote_hash': q.quote_hash, 'action': action})
    return quote_public(q)


def cancellation_quote(oid):
    funds.require_isolated()
    hotel_money_bridge.ensure_original_root(oid)
    with transaction() as s:
        order, offer, snap = context(s, oid)
        b = base_quote(s, order, offer, snap)
        terms = cancellation_terms(order, b['check_in'], b, now())
        eligible = max(b['paid_amount_minor'] - b['forfeited_change_value_minor'], 0)
        fee = eligible * terms['fee_basis_points'] // 10000
        remaining = eligible - fee
        lines = []
        for source in b['available_refund_lines']:
            amount = min(remaining, source['amount_minor'])
            if amount: lines.append({**source, 'amount_minor': amount})
            remaining -= amount
        if remaining: raise ValueError('CASH_REFUND_PLAN_NOT_FUNDED')
        b.update(cancellation_fee_minor=fee, refund_amount_minor=eligible - fee,
            refund_lines=lines, fee_basis_points=terms['fee_basis_points'], fee_basis_minor=eligible,
            cooling_off_applied=terms['cooling_off_applied'], check_in_at=terms['check_in_at'],
            hotel_timezone=terms['hotel_timezone'])
        qid = ident('cq')
        s.add(CancellationQuoteRow(quote_id=qid, order_id=oid, paid_amount_minor=b['paid_amount_minor'],
            cancellation_fee_minor=fee, refund_amount_minor=b['refund_amount_minor'], rule_snapshot=deepcopy(b),
            expires_at=terms['expires_at'], created_at=now()))
        return save_quote(s, 'CANCEL', b, terms['expires_at'], qid)


async def change_quote(oid, check_in, check_out):
    funds.require_isolated()
    try:
        ci, co = date.fromisoformat(check_in), date.fromisoformat(check_out)
        if not now().date() <= ci < co or (co - ci).days > 365: raise ValueError()
    except (ValueError, TypeError): raise ValueError('VALID_FUTURE_CHANGE_DATES_REQUIRED')
    hotel_money_bridge.ensure_original_root(oid)
    with transaction() as s:
        order, old_offer, snap = context(s, oid)
        b = base_quote(s, order, old_offer, snap)
        if not b['rules']['change_allowed']: raise ValueError('CHANGE_NOT_ALLOWED')
        hotel_change_policy.require_window(b['order_created_at'], check_in, now(),
            b['rules']['timezone'], b['rules']['check_in_hour'])
        if b['prior_refund_minor']: raise ValueError('REFUNDED_ROOM_VALUE_RECONCILIATION_REQUIRED')
        cancellation_terms(order, b['check_in'], b, now())  # No ordinary amendment after the stay starts.
        if b['rules'].get('cash_cancellation_value_basis') != POLICY:
            raise ValueError('HISTORICAL_CHANGE_FEE_CANCELLATION_POLICY_REQUIRED')
        conn = remedy.connector(s, order)
    offers = await conn.search('TYO', check_in, check_out, order.currency)
    candidates = [o for o in offers if (o.hotel_id, o.room_type_id, o.rate_plan_id, o.supplier_id, o.currency, o.check_in, o.check_out) ==
        (order.hotel_id, old_offer.room_type_id, old_offer.rate_plan_id, order.supplier_id, order.currency, check_in, check_out)]
    if not candidates: raise ValueError('CHANGE_NOT_AVAILABLE')
    new_offer = candidates[0]
    if type(new_offer.total_amount_minor) is not int or new_offer.total_amount_minor <= 0:
        raise ValueError('POSITIVE_CHANGE_ROOM_VALUE_REQUIRED')
    pb = await conn.prebook_with_key(new_offer, 'cash-change-quote:' + new_offer.offer_id)
    if not pb.price_locked or pb.status.value != 'PREBOOKED' or (pb.total_amount_minor, pb.currency) != (new_offer.total_amount_minor, order.currency):
        raise ValueError('CHANGE_PRICE_OR_INVENTORY_REQUOTE_REQUIRED')
    exp = min(aware(pb.expires_at), aware(new_offer.expires_at), now() + timedelta(minutes=10),
        datetime.fromisoformat(b['change_valid_until']))
    if exp <= now(): raise ValueError('CHANGE_PRICE_LOCK_EXPIRED')
    from go_hotel.repositories.sql import repo
    from go_hotel.domain.models import Event
    repo.save_offer_with_event(new_offer, Event(ident('evt'), 'CHANGE_REPRICE_OFFER_CREATED', 'HOTEL_OFFER', new_offer.offer_id, {'order_id': oid}))
    diff = max(new_offer.total_amount_minor - b['current_room_value_minor'], 0)
    b.update(old_value_minor=b['current_room_value_minor'], new_value_minor=new_offer.total_amount_minor,
        fare_difference_minor=diff, change_fee_minor=0,
        amount_due_minor=diff, lower_price_no_refund=True,
        lower_price_difference_minor=max(b['current_room_value_minor'] - new_offer.total_amount_minor, 0),
        lower_price_rule='FORFEIT_NO_REFUND_NO_FUTURE_OFFSET',
        new_check_in=check_in, new_check_out=check_out, new_offer=offer_facts(new_offer),
        prebook={'prebook_id': pb.prebook_id, 'offer_id': pb.offer_id, 'amount_minor': pb.total_amount_minor,
            'currency': pb.currency, 'expires_at': aware(pb.expires_at).isoformat(), 'price_locked': pb.price_locked})
    with transaction() as s:
        current, offer, snap = context(s, oid)
        current_facts = base_quote(s, current, offer, snap)
        if any(value != b[key] for key, value in current_facts.items()):
            raise ValueError('CASH_FARE_QUOTE_STALE')
        qid = ident('chgq')
        s.add(ChangeQuoteRow(quote_id=qid, order_id=oid, new_check_in=check_in, new_check_out=check_out,
            old_value_minor=b['old_value_minor'], new_value_minor=b['new_value_minor'], fare_difference_minor=diff,
            change_fee_minor=b['change_fee_minor'], amount_due_minor=b['amount_due_minor'],
            rule_snapshot={**deepcopy(b), 'new_offer_id': new_offer.offer_id, 'lower_price_rule': 'NO_REFUND'},
            expires_at=exp, created_at=now()))
        return save_quote(s, 'CHANGE', b, exp, qid)


def checked_quote(s, qid):
    q = s.get(Quote, qid)
    if not q: raise ValueError('CURRENT_CASH_FARE_QUOTE_REQUIRED')
    if digest(q.payload_json) != q.quote_hash or (q.order_id, q.action, q.quote_id, aware(q.expires_at).isoformat()) != (
        q.payload_json['order_id'], q.payload_json['action'], q.payload_json['quote_id'], q.payload_json['expires_at']):
        raise ValueError('CASH_FARE_QUOTE_INTEGRITY_REQUIRED')
    return q


def lock(s, opid):
    probe = s.get(Operation, opid)
    if not probe: raise ValueError('CASH_FARE_OPERATION_NOT_FOUND')
    order = s.get(Order, probe.order_id, with_for_update=True, populate_existing=True)
    op = s.get(Operation, opid, with_for_update=True, populate_existing=True)
    q = checked_quote(s, op.quote_id)
    if digest(op.plan_json) != op.plan_hash or op.plan_json['quote'] != q.payload_json or op.plan_json['quote_hash'] != q.quote_hash:
        raise ValueError('CASH_FARE_PLAN_INTEGRITY_REQUIRED')
    if (order.order_id, order.account_id) != (q.order_id, q.payload_json['account_id']):
        raise ValueError('CASH_FARE_ORDER_IDENTITY_CHANGED')
    return order, op, q.payload_json


def public(op):
    b = op.plan_json['quote']; complete = op.state == 'COMPLETED'
    return {'operation_id': op.operation_id, 'order_id': op.order_id, 'quote_id': op.quote_id,
        'quote_hash': op.plan_json['quote_hash'], 'action': b['action'], 'state': op.state,
        'status': ('CANCELLED' if b['action'] == 'CANCEL' else 'CONFIRMED') if complete else op.state,
        'change_id': op.operation_id if b['action'] == 'CHANGE' else None,
        'supplier_confirmation_no': op.supplier_reference,
        'amount_paid_minor': b.get('amount_due_minor', 0) if complete else 0,
        'amount_due_minor': b.get('amount_due_minor', 0),
        'gross_paid_minor': b['gross_paid_minor'] + (b.get('amount_due_minor', 0) if complete and b['action'] == 'CHANGE' else 0),
        'prior_refund_minor': b['prior_refund_minor'] + (b.get('refund_amount_minor', 0) if complete and b['action'] == 'CANCEL' else 0),
        'cancellation_fee_minor': b.get('cancellation_fee_minor'), 'currency': b['currency'],
        'refund': {'refund_id': op.operation_id, 'amount_minor': b['refund_amount_minor'], 'currency': b['currency'],
            'status': 'COMPLETED' if complete else 'PROCESSING'} if b['action'] == 'CANCEL' else None,
        'payment_retry_allowed': op.state == 'CAPTURE_PENDING' and (op.payment_json or {}).get('outcome') == 'CAPTURE_FAILED',
        'reconcile_allowed': op.state not in TERMINAL, 'data_mode': 'SIMULATION', 'external_live': False}


def status(oid, opid=None):
    with SessionLocal() as s:
        op = s.get(Operation, opid) if opid else s.scalar(select(Operation).where(Operation.order_id == oid)
            .order_by(Operation.created_at.desc(), Operation.operation_id.desc()))
        if not op: return None
        if op.order_id != oid: raise ValueError('CASH_FARE_OPERATION_NOT_FOUND')
        _, op, _ = lock(s, op.operation_id)
        return public(op)


def money_action(s, intent, typ, amount, parent, key):
    oid = intent.business_id if intent.business_type == 'HOTEL_ORDER' else None
    if intent.business_type == 'HOTEL_CHANGE':
        q = s.get(ChangeQuoteRow, intent.business_id); oid = q.order_id if q else None
    if not oid: return
    claim = s.get(Claim, oid)
    if not claim: return
    _, op, b = lock(s, claim.operation_id)
    prefix = 'cash-fare:' + op.operation_id
    if b['action'] == 'CANCEL' and op.state == 'REFUND_PENDING' and typ == 'REFUND':
        if any((intent.payment_intent_id, parent, amount, key) == (x['payment_intent_id'], x['capture_id'], x['amount_minor'], prefix + ':refund:' + x['capture_id']) for x in b['refund_lines']): return
    if b['action'] == 'CHANGE' and intent.business_type == 'HOTEL_CHANGE' and intent.business_id == op.quote_id:
        payment = op.payment_json or {}
        allowed = {'AUTHORIZATION': ('AUTH_PENDING', None, ':auth'), 'CAPTURE': ('CAPTURE_PENDING', payment.get('authorization_id'), ':cap'),
            'RELEASE': ('REJECTED_RELEASE_PENDING', payment.get('authorization_id'), ':release')}
        if typ in allowed:
            phase, expected_parent, suffix = allowed[typ]
            if (op.state, amount, parent, key) == (phase, b['amount_due_minor'], expected_parent, prefix + suffix): return
    raise ValueError('CASH_FARE_FUNDS_RESERVED')
