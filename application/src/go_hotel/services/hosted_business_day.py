"""Hotel-local operational snapshots of the existing money graph, never bank truth.

An immutable close is replayable only while its underlying facts are unchanged.
Blocked previews are not persisted, so resolving an exception permits a real close.
"""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
from sqlalchemy import select, text
from go_hotel.db import models as m
from go_hotel.services import hosted_money
from go_hotel.services.hosted_direct_booking import ident, now, out
from go_hotel.services.hosted_reservation_operations import managed_session

ZONE = ZoneInfo('Asia/Shanghai')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def window(value):
    try:
        day = date.fromisoformat(value)
        if day.isoformat() != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('VALID_BUSINESS_DATE_REQUIRED') from None
    start = datetime.combine(day, time.min, ZONE).astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def snapshot(s, hotel_id, business_date):
    start, end = window(business_date)
    inside = lambda value: value is not None and start <= aware(value) < end
    offers = select(m.HostedDirectRoomOfferRow.hosted_offer_id).where(m.HostedDirectRoomOfferRow.hosted_hotel_id == hotel_id)
    reservations = list(s.scalars(select(m.HostedDirectReservationRow).where(m.HostedDirectReservationRow.hosted_offer_id.in_(offers)).order_by(m.HostedDirectReservationRow.hosted_reservation_id)))
    pools = select(m.HostedDirectInventoryPoolRow.inventory_pool_id).where(m.HostedDirectInventoryPoolRow.hosted_hotel_id == hotel_id)
    days = list(s.scalars(select(m.HostedInventoryDayRow).where(m.HostedInventoryDayRow.inventory_pool_id.in_(pools), m.HostedInventoryDayRow.stay_date == business_date).order_by(m.HostedInventoryDayRow.inventory_day_id)))
    blockers, movements, scoped, carry, stays = [], [], [], [], []
    all_intents = set()
    lifetime = []
    source_bindings = []
    order_facts = []
    for r in reservations:
        if aware(r.created_at) >= end:
            continue
        a = s.scalar(select(m.AlipayAuthorizationRow).where(m.AlipayAuthorizationRow.hosted_reservation_id == r.hosted_reservation_id))
        roots = list(s.scalars(select(m.PaymentOrderRootRow).where(m.PaymentOrderRootRow.business_type == hosted_money.BUSINESS, m.PaymentOrderRootRow.business_id == a.authorization_id))) if a else []
        funding_ids = list(s.scalars(select(m.HostedFareFundingRow.payment_intent_id).where(m.HostedFareFundingRow.hosted_reservation_id == r.hosted_reservation_id)))
        roots += list(s.scalars(select(m.PaymentOrderRootRow).where(m.PaymentOrderRootRow.payment_intent_id.in_(funding_ids)))) if funding_ids else []
        roots = [x for x in roots if aware(x.created_at) < end]
        intent_ids = {x.payment_intent_id for x in roots}
        all_intents.update(intent_ids)
        graph = list(s.scalars(select(m.OmnichannelMoneyMovementRow).where(m.OmnichannelMoneyMovementRow.root_payment_intent_id.in_(intent_ids), m.OmnichannelMoneyMovementRow.created_at < end).order_by(m.OmnichannelMoneyMovementRow.money_movement_id))) if intent_ids else []
        if a and not roots:
            blockers.append('MISSING_CANONICAL_MONEY_ROOT:' + r.hosted_reservation_id)
        for root in roots:
            intent = s.get(m.OmnichannelPaymentIntentRow, root.payment_intent_id)
            binding = s.scalar(select(m.PaymentOrderFactBindingRow).where(m.PaymentOrderFactBindingRow.payment_intent_id == root.payment_intent_id))
            source_bindings.append({'root': out(root), 'intent': out(intent) if intent else None, 'binding': out(binding) if binding else None})
            if not intent or not binding or (binding.payee_id, binding.amount_minor, binding.currency, binding.payer_id) != (hotel_id, intent.amount_minor, intent.currency, intent.payer_id):
                blockers.append('MONEY_ORDER_BINDING_DIFFERENCE:' + root.payment_intent_id)
            if intent and intent.amount_minor and not any(x.root_payment_intent_id == root.payment_intent_id and x.movement_type == 'AUTHORIZATION' for x in graph):
                blockers.append('MISSING_AUTHORIZATION_MOVEMENT:' + root.payment_intent_id)
        order_facts.append({k: getattr(r, k) for k in ('hosted_reservation_id','hosted_offer_id','check_in','check_out','amount_minor','currency','created_at','updated_at')})
        lifetime.extend(graph)
        all_intents.update(x.root_payment_intent_id for x in graph)
        daily = [x for x in graph if inside(x.created_at)]
        movements.extend(daily)
        guest = s.scalar(select(m.GuestStayLifecycleRow).where(m.GuestStayLifecycleRow.hosted_reservation_id == r.hosted_reservation_id))
        relevant = inside(r.created_at) or r.check_in <= business_date <= r.check_out or bool(daily) or (guest and (inside(guest.actual_check_in_at) or inside(guest.actual_check_out_at)))
        unresolved = bool(a and (a.external_invoked or a.state == 'UNKNOWN_EXTERNAL_STATE')) or any(x.state != 'CONFIRMED' for x in graph)
        if unresolved:
            blockers.append('PAYMENT_RECONCILIATION_REQUIRED:' + r.hosted_reservation_id)
            carry.append(r.hosted_reservation_id)
        if relevant:
            if aware(r.updated_at) >= end or (guest and aware(guest.updated_at) >= end):
                blockers.append('HOLD_HISTORICAL_STATE_UNPROVABLE:' + r.hosted_reservation_id)
            scoped.append({'reservation_id': r.hosted_reservation_id, 'state': r.reservation_state, 'payment_state': r.payment_state})
            if guest:
                stays.append({'stay_id': guest.stay_lifecycle_id, 'state': guest.state, 'check_in_at': str(guest.actual_check_in_at), 'check_out_at': str(guest.actual_check_out_at)})
        if guest:
            disputes = list(s.scalars(select(m.StayDisputeRow.stay_dispute_id).where(m.StayDisputeRow.stay_lifecycle_id == guest.stay_lifecycle_id, m.StayDisputeRow.state == 'OPEN_SETTLEMENT_FROZEN')))
            blockers.extend('OPEN_DISPUTE:' + x for x in disputes)
            refunds = list(s.scalars(select(m.RefundEligibilityRow).join(m.PostStayDecisionRow, m.PostStayDecisionRow.post_stay_decision_id == m.RefundEligibilityRow.post_stay_decision_id).join(m.PostStayDisputeCaseRow, m.PostStayDisputeCaseRow.dispute_case_id == m.PostStayDecisionRow.dispute_case_id).where(m.PostStayDisputeCaseRow.stay_lifecycle_id == guest.stay_lifecycle_id)))
            blockers.extend('PENDING_REFUND:' + x.refund_eligibility_id for x in refunds if x.eligible_amount_minor > 0 and x.decision != 'REFUND_CONFIRMED_SIMULATION')
    expected_pools = set(s.scalars(pools))
    actual_pools = {x.inventory_pool_id for x in days}
    blockers.extend('MISSING_INVENTORY_DAY:' + x for x in sorted(expected_pools - actual_pools))
    if not expected_pools:
        blockers.append('INVENTORY_POOLS_REQUIRED')
    for parent in lifetime:
        children = [x for x in lifetime if x.parent_movement_id == parent.money_movement_id and x.state == 'CONFIRMED']
        kinds = {'CAPTURE','RELEASE'} if parent.movement_type == 'AUTHORIZATION' else {'REFUND','COMPENSATION'} if parent.movement_type == 'CAPTURE' else set()
        if parent.amount_minor < 0 or sum(x.amount_minor for x in children if x.movement_type in kinds) > parent.amount_minor:
            blockers.append('PARENT_MONEY_BUDGET_DIFFERENCE:' + parent.money_movement_id)
    for move in lifetime:
        allowed = {'CAPTURE':'AUTHORIZATION','RELEASE':'AUTHORIZATION','REFUND':'CAPTURE','COMPENSATION':'CAPTURE'}
        if move.movement_type in allowed:
            parent = next((x for x in lifetime if x.money_movement_id == move.parent_movement_id), None)
            if not parent or (parent.movement_type,parent.root_payment_intent_id,parent.currency) != (allowed[move.movement_type],move.root_payment_intent_id,move.currency):
                blockers.append('MONEY_PARENT_BINDING_DIFFERENCE:' + move.money_movement_id)
    inventory = {'total': sum(x.capacity_total for x in days), 'available': sum(x.capacity_available for x in days), 'days': []}
    for day in days:
        held = len(list(s.scalars(select(m.HostedReservationNightRow.reservation_night_id).where(m.HostedReservationNightRow.inventory_day_id == day.inventory_day_id, m.HostedReservationNightRow.state == 'HELD'))))
        if aware(day.updated_at) >= end:
            blockers.append('HOLD_HISTORICAL_INVENTORY_UNPROVABLE:' + day.inventory_day_id)
        difference = day.capacity_total - day.capacity_available - held
        inventory['days'].append({'inventory_day_id': day.inventory_day_id, 'total': day.capacity_total, 'available': day.capacity_available, 'held': held, 'difference': difference})
        if difference or not 0 <= day.capacity_available <= day.capacity_total:
            blockers.append('INVENTORY_DIFFERENCE:' + day.inventory_day_id)
    ledger = list(s.scalars(select(m.OmnichannelLedgerEntryRow).where(m.OmnichannelLedgerEntryRow.payment_intent_id.in_(all_intents), m.OmnichannelLedgerEntryRow.transaction_id.in_([x.money_movement_id for x in movements])).order_by(m.OmnichannelLedgerEntryRow.ledger_entry_id))) if all_intents else []
    dated_entries = list(s.scalars(select(m.OmnichannelLedgerEntryRow).where(m.OmnichannelLedgerEntryRow.payment_intent_id.in_(all_intents),m.OmnichannelLedgerEntryRow.created_at >= start,m.OmnichannelLedgerEntryRow.created_at < end))) if all_intents else []
    blockers.extend('ORPHAN_LEDGER:' + x.ledger_entry_id for x in dated_entries if not s.get(m.OmnichannelMoneyMovementRow,x.transaction_id))
    cash = [x for x in movements if x.state == 'CONFIRMED' and x.movement_type not in {'AUTHORIZATION', 'RELEASE'}]
    for move in cash:
        entries = [x for x in ledger if x.transaction_id == move.money_movement_id]
        from go_hotel.services.unified_money_movement import business_ledger_account_code
        intent = s.get(m.OmnichannelPaymentIntentRow, move.root_payment_intent_id)
        pairs = {(f'PAYMENT_CLEARING:{intent.selected_channel}', 'DEBIT'), (business_ledger_account_code(intent.business_type, intent.business_id), 'CREDIT')}
        if move.movement_type in {'REFUND', 'COMPENSATION', 'PAYOUT'}:
            pairs = {(account, 'CREDIT' if direction == 'DEBIT' else 'DEBIT') for account, direction in pairs}
        if {(x.account_code, x.direction) for x in entries} != pairs:
            blockers.append('LEDGER_ACCOUNT_DIFFERENCE:' + move.money_movement_id)
        if len(entries) != 2 or sorted(x.direction for x in entries) != ['CREDIT', 'DEBIT'] or any((x.amount_minor, x.currency, x.payment_intent_id, x.entry_type) != (move.amount_minor, move.currency, move.root_payment_intent_id, move.movement_type) for x in entries):
            blockers.append('MOVEMENT_LEDGER_DIFFERENCE:' + move.money_movement_id)
    cash_ids = {x.money_movement_id for x in cash}
    blockers.extend('ORPHAN_LEDGER:' + x.ledger_entry_id for x in ledger if x.transaction_id not in cash_ids)
    currencies = {}
    for currency in sorted({x.currency for x in lifetime} | {x.currency for x in ledger}):
        totals = {kind.lower() + '_minor': sum(x.amount_minor for x in movements if x.currency == currency and x.state == 'CONFIRMED' and x.movement_type == kind) for kind in ['AUTHORIZATION', 'CAPTURE', 'RELEASE', 'REFUND']}
        totals.update({direction.lower() + '_minor': sum(x.amount_minor for x in ledger if x.currency == currency and x.direction == direction) for direction in ['DEBIT', 'CREDIT']})
        totals['difference_minor'] = totals['debit_minor'] - totals['credit_minor']
        totals['net_capture_minor'] = totals['capture_minor'] - totals['refund_minor']
        for label, boundary in [('opening', start), ('closing', end)]:
            stock = [x for x in lifetime if x.currency == currency and x.state == 'CONFIRMED' and aware(x.created_at) < boundary]
            amount = lambda kind: sum(x.amount_minor for x in stock if x.movement_type == kind)
            totals[label + '_held_minor'] = amount('AUTHORIZATION') - amount('CAPTURE') - amount('RELEASE')
            totals[label + '_net_capture_minor'] = amount('CAPTURE') - amount('REFUND')
            if totals[label + '_held_minor'] < 0 or totals[label + '_net_capture_minor'] < 0:
                blockers.append('NEGATIVE_FUND_BALANCE:' + currency)
        currencies[currency] = totals
    states = dict(Counter(x['state'] for x in scoped))
    exceptions = {'schema': 'HOSTED_BUSINESS_DAY_V1', 'timezone': str(ZONE), 'window_start': start.isoformat(), 'window_end_exclusive': end.isoformat(), 'pending': states.get('PENDING_HOTEL_CONFIRMATION', 0), 'payment_transactions': sum(x.movement_type == 'CAPTURE' for x in cash), 'refund_transactions': sum(x.movement_type == 'REFUND' for x in cash), 'currencies': currencies, 'blockers': sorted(set(blockers)), 'unresolved_reservations': sorted(set(carry)), 'reservations': scoped, 'order_facts': [{k:str(v) if isinstance(v,datetime) else v for k,v in x.items()} for x in order_facts], 'stays': stays, 'movement_ids': sorted(x.money_movement_id for x in movements), 'ledger_ids': sorted(x.ledger_entry_id for x in ledger), 'source_facts_hash': digest([[out(x) for x in sorted(lifetime, key=lambda x: x.money_movement_id)], [out(x) for x in ledger], source_bindings, order_facts]), 'external_reconciliation': 'NOT_PERFORMED', 'production_live': False}
    exceptions['state'] = 'BLOCKED' if blockers else 'OPERATIONAL_SNAPSHOT_RECONCILED'
    payload = {'hotel_id': hotel_id, 'business_date': business_date, 'inventory': inventory, 'reservations': states, 'exceptions': exceptions}
    return payload, digest(payload)


def immutable_facts_hash(s, hotel_id, end):
    """Revalidate economic facts, not a later day's mutable lifecycle states."""
    intents = list(s.scalars(select(m.OmnichannelPaymentIntentRow).where(
        m.OmnichannelPaymentIntentRow.payee_id == hotel_id,
        m.OmnichannelPaymentIntentRow.business_type.in_([hosted_money.BUSINESS, 'HOSTED_HOTEL_FARE_CHANGE']),
        m.OmnichannelPaymentIntentRow.created_at < end).order_by(m.OmnichannelPaymentIntentRow.payment_intent_id)))
    ids = [x.payment_intent_id for x in intents]
    def stable(row):
        return {k:v for k,v in out(row).items() if k not in {'state','updated_at'}}
    roots = list(s.scalars(select(m.PaymentOrderRootRow).where(m.PaymentOrderRootRow.payment_intent_id.in_(ids)).order_by(m.PaymentOrderRootRow.payment_order_root_id))) if ids else []
    bindings = list(s.scalars(select(m.PaymentOrderFactBindingRow).where(m.PaymentOrderFactBindingRow.payment_intent_id.in_(ids)).order_by(m.PaymentOrderFactBindingRow.payment_order_fact_binding_id))) if ids else []
    movements = list(s.scalars(select(m.OmnichannelMoneyMovementRow).where(m.OmnichannelMoneyMovementRow.root_payment_intent_id.in_(ids),m.OmnichannelMoneyMovementRow.created_at < end).order_by(m.OmnichannelMoneyMovementRow.money_movement_id))) if ids else []
    mids = [x.money_movement_id for x in movements]
    ledger = list(s.scalars(select(m.OmnichannelLedgerEntryRow).where(m.OmnichannelLedgerEntryRow.transaction_id.in_(mids)).order_by(m.OmnichannelLedgerEntryRow.ledger_entry_id))) if mids else []
    return digest([[stable(x) for x in intents], [stable(x) for x in roots], [out(x) for x in bindings], [stable(x) for x in movements], [out(x) for x in ledger]])


def close(hotel_id, body, actor, authorize):
    business_date = body.get('business_date') or now().astimezone(ZONE).date().isoformat()
    start, end = window(business_date)
    with managed_session() as s:
        if s.bind.dialect.name == 'postgresql':
            s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        authorize(s, hotel_id, actor, {'DUTY_MANAGER'})
        s.get(m.HostedDirectHotelRow, hotel_id, with_for_update=True)
        old = s.scalar(select(m.HostedDailyCloseRow).where(m.HostedDailyCloseRow.hosted_hotel_id == hotel_id, m.HostedDailyCloseRow.business_date == business_date))
        if old:
            archived = {'hotel_id': hotel_id, 'business_date': business_date, 'inventory': old.inventory_snapshot_json, 'reservations': old.reservation_summary_json, 'exceptions': old.exception_summary_json}
            if digest(archived) != old.evidence_hash or old.exception_summary_json.get('immutable_facts_hash') != immutable_facts_hash(s, hotel_id, end):
                raise ValueError('DAILY_CLOSE_SOURCE_CHANGED_REVIEW_REQUIRED')
            return out(old)
        payload, evidence_hash = snapshot(s, hotel_id, business_date)
        if now() < end and not payload['exceptions']['blockers']:
            payload['exceptions']['state'] = 'PREVIEW_OPEN_BUSINESS_DAY'
        payload['exceptions']['immutable_facts_hash'] = immutable_facts_hash(s, hotel_id, end)
        payload['exceptions']['snapshot_cutoff_at'] = min(now(),end).isoformat()
        evidence_hash = digest(payload)
        if payload['exceptions']['blockers'] or now() < end:
            return {'daily_close_id': None, 'hosted_hotel_id': hotel_id, 'business_date': business_date, 'inventory_snapshot_json': payload['inventory'], 'reservation_summary_json': payload['reservations'], 'exception_summary_json': payload['exceptions'], 'evidence_hash': evidence_hash}
        row = m.HostedDailyCloseRow(daily_close_id=ident('hdc'), hosted_hotel_id=hotel_id, business_date=business_date, inventory_snapshot_json=payload['inventory'], reservation_summary_json=payload['reservations'], exception_summary_json=payload['exceptions'], evidence_hash=evidence_hash, closed_by=actor, closed_at=now())
        s.add(row)
        s.flush()
        s.commit()
        return out(row)
