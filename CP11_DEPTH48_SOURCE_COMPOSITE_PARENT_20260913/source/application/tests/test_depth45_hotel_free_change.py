"""Owner-authorized hotel rule: fee zero, fixed year, positive differences only."""
from datetime import datetime, timedelta, timezone
import pytest

from test_depth14_cash_fare import booked_order, change_quote, execute, moves, fare, day, run
from go_hotel.services import hotel_change_policy as policy, catalog_fare_snapshot as rules


@pytest.mark.parametrize('delta,due', [(80000, 80000), (0, 0), (-43200, 0)])
def test_hotel_only_collects_positive_room_difference(client, delta, due):
    oid = booked_order(client)
    quote = change_quote(oid, delta)
    assert quote['change_fee_minor'] == 0
    assert quote['amount_due_minor'] == quote['fare_difference_minor'] == due
    assert quote['change_policy'] == policy.POLICY
    assert quote['change_validity_days'] == 365
    result = execute(oid, quote)
    assert result['state'] == 'COMPLETED'
    assert result['amount_paid_minor'] == due
    assert not moves(oid, 'REFUND')
    assert len(moves(oid, 'CAPTURE')) == (2 if due else 1)
    assert sum(x.amount_minor for x in moves(oid, 'CAPTURE')) == 1443200 + due
    assert fare.cancellation_quote(oid)['paid_change_fees_minor'] == 0


def test_repeated_changes_do_not_extend_original_one_year_deadline(client):
    oid = booked_order(client)
    first = change_quote(oid, 80000, 50)
    execute(oid, first)
    second = change_quote(oid, 120000, 60)
    assert second['change_valid_until'] == first['change_valid_until']
    assert second['change_valid_from'] == first['change_valid_from']
    assert second['amount_due_minor'] == 40000


def test_same_high_high_low_then_cancel_retains_forfeiture_and_refunds_only_eligible_money(client):
    oid = booked_order(client)
    for delta, offset, due in [(0, 45, 0), (80000, 50, 80000), (120000, 60, 40000), (-43200, 70, 0)]:
        quote = change_quote(oid, delta, offset)
        assert quote['amount_due_minor'] == due and quote['change_fee_minor'] == 0
        assert execute(oid, quote)['state'] == 'COMPLETED'
    assert not moves(oid, 'REFUND')
    cancel = fare.cancellation_quote(oid)
    assert cancel['gross_paid_minor'] == 1563200
    assert cancel['forfeited_change_value_minor'] == 163200
    assert cancel['refund_amount_minor'] == 1400000
    assert cancel['paid_change_fees_minor'] == 0
    assert execute(oid, cancel)['state'] == 'COMPLETED'
    assert len(moves(oid, 'CAPTURE')) == 3
    assert len(moves(oid, 'REFUND')) == 1
    assert sum(x.amount_minor for x in moves(oid, 'REFUND')) == 1400000


def test_arrival_on_last_valid_day_is_allowed_but_next_day_is_rejected(client):
    oid = booked_order(client)
    accepted = run(fare.change_quote(oid, day(365), day(367)))
    assert accepted['new_check_in'] == day(365)
    with pytest.raises(ValueError, match='ONE_YEAR_VALIDITY'):
        run(fare.change_quote(oid, day(366), day(368)))
    assert len(moves(oid, 'CAPTURE')) == 1


def test_fixed_year_uses_original_timestamp_and_hotel_arrival_timezone():
    created = datetime(2026, 9, 12, 6, tzinfo=timezone.utc)
    deadline = created + timedelta(days=365)
    assert policy.require_window(created, '2027-09-12', created, 'Asia/Tokyo', 15)['change_valid_until'] == deadline.isoformat()
    with pytest.raises(ValueError, match='ONE_YEAR_VALIDITY'):
        policy.require_window(created, '2027-09-12', created, 'Asia/Tokyo', 16)
    with pytest.raises(ValueError, match='ONE_YEAR_VALIDITY'):
        policy.require_window(created, '2027-09-12', deadline, 'Asia/Tokyo', 15)


def test_supplier_cannot_publish_an_additional_hotel_change_fee(client):
    oid = booked_order(client)
    from test_depth13_catalog_fare import publish_for_order
    with pytest.raises(ValueError, match='FEE_MUST_BE_ZERO'):
        publish_for_order(oid, change_fee_minor=10000)
    assert rules.order_rule(oid)['change_fee_minor'] == 0


def test_hosted_hotel_uses_same_deadline_before_inventory_lookup(client, monkeypatch):
    from tests.test_depth08_hosted_fare import booked, RULES
    from go_hotel.services import hosted_fare_change as direct, hosted_fare_rules as published
    reservation, account, *_ = booked(client, monkeypatch)
    created = datetime.fromisoformat(reservation['created_at'])
    outside = (created + timedelta(days=366)).date()
    with pytest.raises(ValueError, match='ONE_YEAR_VALIDITY'):
        direct.create_quote(reservation['hosted_reservation_id'], account, 'CHANGE_DATE',
                            outside.isoformat(), (outside + timedelta(days=2)).isoformat())
    with pytest.raises(ValueError, match='FEE_MUST_BE_ZERO'):
        published.publish(reservation['hosted_offer_id'], {**RULES, 'change_fee_minor': 1},
                          'simulation://fee-rejected', 'hotel')
