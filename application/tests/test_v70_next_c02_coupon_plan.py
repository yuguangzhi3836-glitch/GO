"""C02-02 pure planning: explicit coupon allocation and immutable partial-party identity."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from go_hotel.flight import coupon_plan as planner

pytestmark = pytest.mark.no_db
AT = datetime(2026, 9, 14, tzinfo=timezone.utc)


def inputs():
    amounts = list(range(101, 110))
    order = {'order_id': 'isolation-order', 'account_id': 'owner', 'status': 'TICKETED',
        'passengers': [{'full_name': name} for name in ['A', 'B', 'C']],
        'ticket_numbers': ['OLD-' + str(i) for i in range(9)], 'currency': 'CNY',
        'total_amount_minor': sum(amounts),
        'itinerary': [{'origin': a, 'destination': b, 'departure_date': d}
            for a, b, d in [('SHA', 'NRT', '2026-10-01'), ('NRT', 'SIN', '2026-10-10'), ('SIN', 'SHA', '2026-10-20')]]}
    changes = [{'leg_index': leg, 'passenger_index': 1, 'new_departure_date': day,
                'fare_difference_minor': 30, 'change_fee_minor': 20}
        for leg, day in [(0, '2026-10-02'), (2, '2026-10-21')]]
    return order, changes, amounts


def build(order, changes, amounts):
    return planner.build(order, 'owner', changes, amounts, at=AT, expires_at=AT + timedelta(minutes=15))


def test_partial_party_preview_preserves_every_unselected_coupon_and_nonuniform_original_allocation():
    order, changes, amounts = inputs()
    before = deepcopy((order, changes, amounts))
    plan = build(order, changes, amounts)
    # Supplier receipt order differs: explicit tuple binding still maps the right ticket.
    receipts = [{'leg_index': 2, 'passenger_index': 1, 'ticket_number': 'NEW-RETURN'},
                {'leg_index': 0, 'passenger_index': 1, 'ticket_number': 'NEW-OUTBOUND'}]
    preview = planner.preview(plan, order, 'owner', receipts, at=AT)
    assert (order, changes, amounts) == before
    assert plan['total_due_minor'] == 100
    assert sum(c['original_amount_minor'] for c in plan['coupons']) == order['total_amount_minor']
    assert preview['new_total_amount_minor'] == order['total_amount_minor'] + 100
    for index, coupon in enumerate(preview['coupons']):
        if index not in {1, 7}:
            assert coupon == plan['coupons'][index]
        else:
            assert coupon['passenger'] == {'full_name': 'B'}
            assert coupon['ticket_number'] == ('NEW-OUTBOUND' if index == 1 else 'NEW-RETURN')
    assert not preview['runtime_integrated'] and preview['mode'] == 'ISOLATED_PREVIEW_ONLY'


@pytest.mark.parametrize('fault', ['bool_index', 'float_index', 'negative_index', 'overflow', 'duplicate', 'bool_money', 'float_money', 'negative_money', 'allocation_total', 'allocation_bool', 'duplicate_original_ticket'])
def test_invalid_indices_amounts_or_duplicate_coupons_cannot_form_plan(fault):
    order, changes, amounts = inputs()
    if fault in {'bool_index', 'float_index', 'negative_index', 'overflow'}:
        changes[0]['passenger_index'] = {'bool_index': True, 'float_index': 1.0, 'negative_index': -1, 'overflow': 3}[fault]
    elif fault == 'duplicate':
        changes.append(deepcopy(changes[0]))
    elif fault in {'bool_money', 'float_money', 'negative_money'}:
        changes[0]['fare_difference_minor'] = {'bool_money': True, 'float_money': 1.0, 'negative_money': -1}[fault]
    elif fault == 'allocation_total':
        amounts[0] += 1
    elif fault == 'duplicate_original_ticket':
        order['ticket_numbers'][-1] = order['ticket_numbers'][0]
    else:
        amounts[0] = True
    with pytest.raises(ValueError):
        build(order, changes, amounts)


@pytest.mark.parametrize('fault', ['owner', 'reorder_people', 'ticket', 'pnr', 'itinerary', 'amount', 'expired', 'payload'])
def test_frozen_plan_rejects_foreign_owner_stale_order_and_changed_payload(fault):
    order, changes, amounts = inputs()
    plan = build(order, changes, amounts)
    at, owner = AT, 'owner'
    if fault == 'owner': owner = 'other'
    elif fault == 'reorder_people': order['passengers'].reverse()
    elif fault == 'ticket': order['ticket_numbers'][0] = 'CHANGED'
    elif fault == 'pnr': order['pnr'] = 'DIFFERENT-BOOKING'
    elif fault == 'itinerary': order['itinerary'][1]['origin'] = 'HND'
    elif fault == 'amount': order['total_amount_minor'] += 1
    elif fault == 'expired': at = AT + timedelta(minutes=15)
    else: plan['changes'][0]['fare_difference_minor'] += 1
    with pytest.raises(ValueError):
        planner.validate(plan, order, owner, at=at)


@pytest.mark.parametrize('fault', ['wrong_coupon', 'duplicate_coupon', 'duplicate_ticket', 'old_ticket', 'bool_index'])
def test_same_count_supplier_receipts_must_map_exact_selected_coupons(fault):
    order, changes, amounts = inputs()
    plan = build(order, changes, amounts)
    receipts = [{'leg_index': 0, 'passenger_index': 1, 'ticket_number': 'NEW-A'},
                {'leg_index': 2, 'passenger_index': 1, 'ticket_number': 'NEW-B'}]
    if fault == 'wrong_coupon': receipts[1]['passenger_index'] = 2
    elif fault == 'duplicate_coupon': receipts[1]['leg_index'] = 0
    elif fault == 'duplicate_ticket': receipts[1]['ticket_number'] = 'NEW-A'
    elif fault == 'old_ticket': receipts[1]['ticket_number'] = order['ticket_numbers'][0]
    else: receipts[1]['passenger_index'] = True
    with pytest.raises(ValueError, match='REISSUE_TICKETS_INVALID'):
        planner.preview(plan, order, 'owner', receipts, at=AT)
