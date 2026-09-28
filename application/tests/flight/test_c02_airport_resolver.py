from datetime import date, timedelta

import pytest

from go_hotel.flight.airports import AirportResolutionError, resolve_airport
from go_hotel.flight.journeys import JourneySearch
from go_hotel.security.service import identity_service
from tests.test_sprint3a_flight import auth


@pytest.mark.parametrize(('query', 'expected'), [
    ('PVG', 'PVG'),
    ('pvg', 'PVG'),
    (' 上海浦东国际机场 ', 'PVG'),
    ('東京羽田空港', 'HND'),
    ('인천국제공항', 'ICN'),
    ('Aéroport de Paris-Charles-de-Gaulle', 'CDG'),
    ('Nueva York', 'JFK'),
    ('新加坡', 'SIN'),
    ('ท่าอากาศยานสุวรรณภูมิ', 'BKK'),
    ('مطار دبي الدولي', 'DXB'),
    ('Шереметьево', 'SVO'),
    ('Flughafen Frankfurt', 'FRA'),
    ('Aeroporto di Roma Fiumicino', 'FCO'),
    ('Aeropuerto Adolfo Suárez Madrid-Barajas', 'MAD'),
])
def test_exact_multilingual_airport_aliases(query, expected):
    assert resolve_airport(query)['iata'] == expected


@pytest.mark.parametrize(('query', 'code', 'candidates'), [
    ('上海', 'AIRPORT_AMBIGUOUS', ('PVG', 'SHA')),
    ('Tokyo', 'AIRPORT_AMBIGUOUS', ('HND', 'NRT')),
    ('上海浦冬机场', 'AIRPORT_NOT_FOUND', ()),
    ('London Gatwick', 'AIRPORT_NOT_FOUND', ()),
    ('ZZZ', 'AIRPORT_NOT_FOUND', ()),
])
def test_ambiguous_or_unknown_airports_never_fuzzy_match(query, code, candidates):
    with pytest.raises(AirportResolutionError) as caught:
        resolve_airport(query)
    assert caught.value.code == code
    assert caught.value.candidates == candidates


def test_consumer_api_resolves_chinese_and_multilingual_inputs(client):
    consumer = auth(client, 'c02-airports@example.test')
    body = {
        'origin': '上海浦东国际机场',
        'destination': '東京成田空港',
        'departure_date': (date.today() + timedelta(days=10)).isoformat(),
        'cabin': 'ECONOMY',
        'currency': 'CNY',
    }
    response = client.post('/v1/flights/search', headers=consumer, json=body)
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['resolved_airports']['origin']['iata'] == 'PVG'
    assert data['resolved_airports']['destination']['iata'] == 'NRT'
    assert all(item['origin'] == 'PVG' and item['destination'] == 'NRT' for item in data['items'])


def test_api_reports_ambiguity_and_no_match_without_searching(client):
    consumer = auth(client, 'c02-airport-errors@example.test')
    common = {
        'departure_date': (date.today() + timedelta(days=10)).isoformat(),
        'cabin': 'ECONOMY',
        'currency': 'CNY',
    }
    ambiguous = client.post('/v1/flights/search', headers=consumer, json={
        **common, 'origin': '上海', 'destination': 'NRT',
    })
    assert ambiguous.status_code == 409
    assert ambiguous.json()['detail'] == {
        'code': 'AIRPORT_AMBIGUOUS', 'query': '上海', 'candidates': ['PVG', 'SHA'],
    }

    unknown = client.post('/v1/flights/search', headers=consumer, json={
        **common, 'origin': '上海浦冬机场', 'destination': 'NRT',
    })
    assert unknown.status_code == 422
    assert unknown.json()['detail']['code'] == 'AIRPORT_NOT_FOUND'


def test_supplier_and_admin_gain_no_flight_mutation_authority(client):
    supplier_token = identity_service.login('supplier_owner', 'change-me-supplier')
    admin_token = identity_service.login('go_admin', 'change-me-admin')
    body = {
        'origin': 'PVG',
        'destination': 'NRT',
        'departure_date': (date.today() + timedelta(days=10)).isoformat(),
    }
    for token in (supplier_token, admin_token):
        headers = {'Authorization': 'Bearer ' + token['access_token']}
        assert client.post('/v1/flights/search', headers=headers, json=body).status_code == 200
        assert client.post('/v1/flights/orders/not-owned/change-quote', headers=headers, json={
            'new_departure_date': (date.today() + timedelta(days=11)).isoformat(),
        }).status_code == 403


def test_journey_search_resolves_multilingual_airport_fields():
    request = JourneySearch(
        trip_type='ONE_WAY',
        legs=[{
            'origin': '上海浦东国际机场',
            'destination': '東京成田空港',
            'departure_date': (date.today() + timedelta(days=10)).isoformat(),
        }],
    )
    assert request.legs[0].origin == 'PVG'
    assert request.legs[0].destination == 'NRT'
