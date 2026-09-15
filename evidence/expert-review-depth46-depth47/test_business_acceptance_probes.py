"""Business acceptance probes against the unchanged DEPTH47 candidate.

These assertions encode the owner's lower-price-forfeiture rule. A failure is a
review finding, not an expected-failure marker or a change to application tests.
Run from application with PYTHONPATH=src:.:tests and the isolated local venv.
"""
from tests.conftest import client, reset_db  # noqa: F401; isolated test fixtures
from tests.test_depth08_hosted_fare import booked
from tests.test_depth08_hosted_change import change_quote, rate, apply


def test_direct_lower_then_higher_cannot_reuse_forfeited_difference(client, monkeypatch):
    reservation, account, *_ = booked(client, monkeypatch)
    first = change_quote(reservation, account)
    rate(reservation, first['check_in'], first['check_out'], 70000)
    first = change_quote(reservation, account)
    assert first['old_amount_minor'] == 162000
    assert first['new_room_quote_minor'] == 140000
    assert first['additional_amount_minor'] == 0
    reservation = {**reservation, **apply(reservation, account, first)}

    second = change_quote(reservation, account)
    rate(reservation, second['check_in'], second['check_out'], 75000)
    second = change_quote(reservation, account)
    assert second['new_room_quote_minor'] == 150000
    assert second['change_fee_minor'] == 0
    observed = {key: second[key] for key in (
        'old_amount_minor', 'new_room_quote_minor', 'additional_amount_minor',
        'new_amount_minor', 'lower_price_rule')}
    assert second['additional_amount_minor'] == 10000, observed


def test_catalog_lower_then_higher_collects_current_room_difference(client):
    from test_depth14_cash_fare import booked_order, change_quote as quote, execute
    order_id = booked_order(client)
    first = quote(order_id, -43200, 50)
    assert first['amount_due_minor'] == 0
    assert execute(order_id, first)['state'] == 'COMPLETED'
    second = quote(order_id, -33200, 60)
    assert second['amount_due_minor'] == 10000


def test_direct_lower_then_credit_excludes_forfeited_value(client, monkeypatch):
    from tests.test_depth08_hosted_fare import RULES
    from go_hotel.services import hosted_stay_credit as credit, hosted_credit_value as value
    reservation, account, *_ = booked(client, monkeypatch, rules={**RULES, 'credit_terms': value.TERMS})
    first = change_quote(reservation, account)
    rate(reservation, first['check_in'], first['check_out'], 70000)
    first = change_quote(reservation, account)
    reservation = {**reservation, **apply(reservation, account, first)}
    quote = credit.conversion_quote(reservation['hosted_reservation_id'], account)
    result = credit.convert(reservation['hosted_reservation_id'], account, quote['quote_id'],
                            quote['retained_value_minor'], 'CNY')
    observed = {key: result['credit'].get(key) for key in ('issued_minor', 'available_minor', 'state')}
    assert result['credit']['issued_minor'] == 140000, observed


def test_round_trip_with_changeable_fares_can_request_change_quote(client):
    from test_flight_journey_depth import auth, compose, search, ticket, day
    headers = auth(client)
    offer = compose(client, search(client), [0, 0]).json()['data']
    order_id = ticket(client, offer, headers)
    response = client.post(f'/v1/flights/orders/{order_id}/change-quote', headers=headers,
                           json={'new_departure_date': day(12)})
    assert response.status_code == 200, response.text
