"""Isolated partial-party planning only; no HTTP, persistence, pricing or money executor.

Original coupon amounts must be supplied explicitly and conserve the order total.
The plan freezes passenger/coupon identity. A preview does not change an order.
"""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def facts(order, account):
    if not isinstance(order, dict) or order.get('account_id') != account:
        raise ValueError('COUPON_PLAN_OWNER_INVALID')
    keys = ('order_id', 'account_id', 'status', 'passengers', 'ticket_numbers',
            'itinerary', 'total_amount_minor', 'currency')
    if any(key not in order for key in keys) or order['status'] != 'TICKETED':
        raise ValueError('COUPON_PLAN_ORDER_INVALID')
    value = deepcopy({key: order[key] for key in keys})
    value['pnr'] = deepcopy(order.get('pnr'))
    people, legs, tickets = value['passengers'], value['itinerary'], value['ticket_numbers']
    if (not isinstance(people, list) or not people or not isinstance(legs, list) or not legs
            or not isinstance(tickets, list) or len(tickets) != len(people) * len(legs)
            or any(not isinstance(ticket, str) or not ticket.strip() for ticket in tickets)
            or len(set(tickets)) != len(tickets)
            or type(value['total_amount_minor']) is not int or value['total_amount_minor'] <= 0
            or not isinstance(value['currency'], str) or not value['currency']):
        raise ValueError('COUPON_PLAN_ORDER_INVALID')
    return value


def _time(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('COUPON_PLAN_TIME_INVALID')
    return value


def build(order, account, selections, original_coupon_amounts, *, at, expires_at):
    frozen = facts(order, account)
    if _time(expires_at) <= _time(at):
        raise ValueError('COUPON_PLAN_EXPIRED')
    count = len(frozen['passengers'])
    legs = frozen['itinerary']
    if (not isinstance(original_coupon_amounts, list)
            or len(original_coupon_amounts) != len(frozen['ticket_numbers'])
            or any(type(value) is not int or value < 0 for value in original_coupon_amounts)
            or sum(original_coupon_amounts) != frozen['total_amount_minor']):
        raise ValueError('COUPON_ORIGINAL_ALLOCATION_INVALID')
    coupons = []
    for leg_index, leg in enumerate(legs):
        if not isinstance(leg, dict) or any(key not in leg for key in ('departure_date', 'origin', 'destination')):
            raise ValueError('COUPON_PLAN_ORDER_INVALID')
        for passenger_index, passenger in enumerate(frozen['passengers']):
            index = leg_index * count + passenger_index
            coupons.append({'leg_index': leg_index, 'passenger_index': passenger_index,
                'ticket_number': frozen['ticket_numbers'][index], 'passenger': deepcopy(passenger),
                'leg': deepcopy(leg), 'original_amount_minor': original_coupon_amounts[index]})
    if not isinstance(selections, list) or not selections:
        raise ValueError('COUPON_SELECTION_INVALID')
    changes, seen = [], set()
    expected = {'leg_index', 'passenger_index', 'new_departure_date', 'fare_difference_minor', 'change_fee_minor'}
    for selection in selections:
        if not isinstance(selection, dict) or set(selection) != expected:
            raise ValueError('COUPON_SELECTION_INVALID')
        li, pi = selection['leg_index'], selection['passenger_index']
        if (type(li) is not int or type(pi) is not int or not 0 <= li < len(legs)
                or not 0 <= pi < count or (li, pi) in seen):
            raise ValueError('COUPON_SELECTION_INVALID')
        try:
            new_date = date.fromisoformat(selection['new_departure_date'])
        except (ValueError, TypeError):
            raise ValueError('COUPON_SELECTION_DATE_INVALID') from None
        if (new_date.isoformat() != selection['new_departure_date'] or new_date < at.date()
                or selection['new_departure_date'] == legs[li]['departure_date']):
            raise ValueError('COUPON_SELECTION_DATE_INVALID')
        if any(type(selection[key]) is not int or selection[key] < 0 for key in ('fare_difference_minor', 'change_fee_minor')):
            raise ValueError('COUPON_SELECTED_AMOUNT_INVALID')
        changes.append({**deepcopy(selection), 'original_coupon': deepcopy(coupons[li * count + pi])})
        seen.add((li, pi))
    changes.sort(key=lambda row: (row['leg_index'], row['passenger_index']))
    for pi in range(count):
        dates = [next((c['new_departure_date'] for c in changes
                      if (c['leg_index'], c['passenger_index']) == (li, pi)), leg['departure_date'])
                 for li, leg in enumerate(legs)]
        if any(second <= first for first, second in zip(dates, dates[1:])):
            raise ValueError('COUPON_ITINERARY_DATE_ORDER_INVALID')
    plan = {'schema_version': 1, 'mode': 'ISOLATED_PLAN_ONLY', 'runtime_integrated': False,
        'order': frozen, 'order_hash': digest(frozen), 'coupons': coupons, 'changes': changes,
        'total_due_minor': sum(c['fare_difference_minor'] + c['change_fee_minor'] for c in changes),
        'created_at': at.isoformat(), 'expires_at': expires_at.isoformat()}
    return {**plan, 'plan_hash': digest(plan)}


def validate(plan, current_order, account, *, at):
    if not isinstance(plan, dict) or 'plan_hash' not in plan:
        raise ValueError('COUPON_PLAN_INTEGRITY_INVALID')
    payload = {key: value for key, value in plan.items() if key != 'plan_hash'}
    if digest(payload) != plan['plan_hash']:
        raise ValueError('COUPON_PLAN_INTEGRITY_INVALID')
    current = facts(current_order, account)
    if plan['order'] != current or plan['order_hash'] != digest(current):
        raise ValueError('COUPON_PLAN_ORDER_CHANGED')
    if _time(datetime.fromisoformat(plan['expires_at'])) <= _time(at):
        raise ValueError('COUPON_PLAN_EXPIRED')
    return deepcopy(plan)


def preview(plan, current_order, account, receipts, *, at):
    checked = validate(plan, current_order, account, at=at)
    if not isinstance(receipts, list) or len(receipts) != len(checked['changes']):
        raise ValueError('COUPON_REISSUE_TICKETS_INVALID')
    changes = {(c['leg_index'], c['passenger_index']): c for c in checked['changes']}
    by_index, seen_tickets = {}, set(checked['order']['ticket_numbers'])
    for receipt in receipts:
        if not isinstance(receipt, dict) or set(receipt) != {'leg_index', 'passenger_index', 'ticket_number'}:
            raise ValueError('COUPON_REISSUE_TICKETS_INVALID')
        li, pi, ticket = receipt['leg_index'], receipt['passenger_index'], receipt['ticket_number']
        if (type(li) is not int or type(pi) is not int or (li, pi) not in changes
                or (li, pi) in by_index or not isinstance(ticket, str) or not ticket.strip()
                or ticket in seen_tickets):
            raise ValueError('COUPON_REISSUE_TICKETS_INVALID')
        by_index[(li, pi)] = (changes[(li, pi)], ticket)
        seen_tickets.add(ticket)
    result = deepcopy(checked['coupons'])
    for coupon in result:
        selected = by_index.get((coupon['leg_index'], coupon['passenger_index']))
        if selected:
            change, ticket = selected
            coupon['ticket_number'] = ticket
            coupon['leg']['departure_date'] = change['new_departure_date']
            coupon['new_amount_minor'] = coupon['original_amount_minor'] + change['fare_difference_minor']
    return {'mode': 'ISOLATED_PREVIEW_ONLY', 'runtime_integrated': False,
        'plan_hash': checked['plan_hash'], 'coupons': result, 'total_due_minor': checked['total_due_minor'],
        'new_total_amount_minor': current_order['total_amount_minor'] + checked['total_due_minor']}
