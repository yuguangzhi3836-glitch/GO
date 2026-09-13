"""A repeated hotel search must never book an earlier stay or currency."""
from datetime import datetime, timedelta, timezone
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OfferRow


def day(n):
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


def search(client, n, currency='CNY'):
    response = client.post('/v1/search/hotels', json={
        'destination': {'city_code': 'TYO'}, 'stay': {'check_in': day(n), 'check_out': day(n+2)},
        'occupancy': {'rooms': 1, 'adults': 2, 'children': 0}, 'currency': currency})
    assert response.status_code == 200, response.text
    return response.json()['data']['hotels'][0]['best_offer']


def query(n, currency='CNY'):
    return {'check_in': day(n), 'check_out': day(n+2), 'currency': currency}


def test_repeated_search_keeps_only_requested_dates_and_currency(client):
    old = search(client, 30)
    chosen = search(client, 40)
    other_currency = search(client, 40, 'USD')
    response = client.get('/v1/consumer/hotels/htl_conrad_tokyo', params=query(40))
    assert response.status_code == 200
    offers = response.json()['data']['offers']
    assert [x['offer_id'] for x in offers] == [chosen['offer_id']]
    assert all((x['check_in'], x['check_out'], x['currency']) == (day(40), day(42), 'CNY') for x in offers)
    assert old['offer_id'] != chosen['offer_id'] != other_currency['offer_id']


def test_matching_offer_is_filtered_before_history_limit(client):
    chosen = search(client, 40)
    for n in range(60, 83):
        search(client, n)
    offers = client.get('/v1/consumer/hotels/htl_conrad_tokyo', params=query(40)).json()['data']['offers']
    assert [x['offer_id'] for x in offers] == [chosen['offer_id']]


def test_missing_or_expired_quote_does_not_fall_back_to_other_dates(client):
    chosen = search(client, 40)
    assert client.get('/v1/consumer/hotels/htl_conrad_tokyo', params=query(50)).json()['data']['offers'] == []
    with SessionLocal.begin() as session:
        session.get(OfferRow, chosen['offer_id']).expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
    assert client.get('/v1/consumer/hotels/htl_conrad_tokyo', params=query(40)).json()['data']['offers'] == []


@pytest.mark.parametrize('params', [
    {'check_in': 'bad-date', 'check_out': '2026-12-12'},
    {'check_in': '2026-12-12'}, {'check_out': '2026-12-12'},
    {'check_in': '2026-12-12', 'check_out': '2026-12-12'},
    {'check_in': '2026-12-13', 'check_out': '2026-12-12'},
    {'check_in': '2026-12-12', 'check_out': '2026-12-13', 'currency': 'CNY,USD'},
])
def test_invalid_stay_filter_is_rejected(client, params):
    response = client.get('/v1/consumer/hotels/htl_conrad_tokyo', params=params)
    assert response.status_code == 422
