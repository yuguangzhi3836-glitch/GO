"""C02 boundary: unsupported partial-party reissue must not silently change everybody."""
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightChangePlanRow, FlightChangeQuoteRow
from tests.test_depth48_flight_changes import booked, amounts
from tests.test_flight_journey_depth import day


@pytest.mark.parametrize('kind', ['ROUND_TRIP', 'MULTI_CITY'])
@pytest.mark.parametrize('location', ['body', 'leg'])
def test_partial_passenger_selection_is_rejected_before_quote_or_money(client, kind, location):
    owner, order, headers = booked(client, kind, party=3)
    selection = [{'leg_index': 0, 'new_departure_date': day(11)}]
    if kind == 'MULTI_CITY':
        selection.append({'leg_index': 2, 'new_departure_date': day(20)})
    body = {'changes': selection}
    if location == 'body':
        body['passenger_indices'] = [1]
    else:
        selection[0]['passenger_indices'] = [1]
    before = amounts()
    response = client.post('/v1/flights/orders/' + order['order_id'] + '/change-quote',
                           headers=headers, json=body)
    assert response.status_code == 422, response.text
    assert 'extra_forbidden' in response.text
    assert amounts() == before
    with SessionLocal() as session:
        assert not list(session.scalars(select(FlightChangePlanRow)))
        assert not list(session.scalars(select(FlightChangeQuoteRow)))
    current = client.get('/v1/flights/orders/' + order['order_id'], headers=headers).json()['data']
    assert current['status'] == 'TICKETED'
    assert current['ticket_numbers'] == order['ticket_numbers']
    assert current['itinerary'] == order['itinerary']
