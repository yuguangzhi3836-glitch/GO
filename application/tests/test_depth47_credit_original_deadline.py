"""Credit conversion must not renew the original hotel booking's fixed year."""
from registration_terms_test_support import register_synthetic_consumer
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from go_hotel.db.models import OrderRow, StayCreditRow, HostedDirectReservationRow
from go_hotel.db.session import SessionLocal
from go_hotel.services import hotel_change_policy as policy
from go_hotel.services import catalog_stay_credit as catalog
from go_hotel.services import hosted_stay_credit as direct, hosted_credit_value as value
from go_hotel.services import hosted_fare_rules as fare
from go_hotel.connectors.mock_hotel import connector
from tests.test_depth12_catalog_credit import run, booked_order
from tests.test_depth08_hosted_fare import booked, RULES


def test_policy_caps_late_conversion_and_preserves_shorter_accepted_term():
    created = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
    quoted = created + timedelta(days=300)
    assert policy.credit_window(created, quoted, 365)['credit_expires_at'] == (created + timedelta(days=365)).isoformat()
    assert policy.credit_window(created, quoted, 7)['credit_expires_at'] == (quoted + timedelta(days=7)).isoformat()
    with pytest.raises(ValueError, match='ONE_YEAR_VALIDITY'):
        policy.credit_window(created, created + timedelta(days=365), 365)


def future_catalog_order(client):
    arrival = datetime.now(timezone.utc) + timedelta(days=400)
    oid = booked_order(client, arrival.date().isoformat(), (arrival + timedelta(days=3)).date().isoformat())
    with SessionLocal() as s:
        created = s.get(OrderRow, oid).created_at.replace(tzinfo=timezone.utc)
    return oid, created


def test_catalog_late_conversion_is_pinned_to_original_booking_and_replay(client, monkeypatch):
    oid, created = future_catalog_order(client)
    monkeypatch.setattr(catalog, 'now', lambda: created + timedelta(days=300))
    q = catalog.conversion_quote(oid)
    expected = (created + timedelta(days=365)).isoformat()
    assert q['credit_expires_at'] == expected
    c = run(catalog.convert(oid, q['quote_id'], q['quote_hash'], True, 'owner'))
    assert c['expires_at'] == expected
    assert run(catalog.convert(oid, q['quote_id'], q['quote_hash'], True, 'owner'))['expires_at'] == expected
    assert connector.cancel_calls == 1


def test_catalog_expired_original_year_cannot_cancel_or_issue_credit(client, monkeypatch):
    oid, created = future_catalog_order(client)
    monkeypatch.setattr(catalog, 'now', lambda: created + timedelta(days=366))
    before = connector.cancel_calls
    with pytest.raises(ValueError, match='ONE_YEAR_VALIDITY'):
        catalog.conversion_quote(oid)
    with SessionLocal() as s:
        assert not s.scalar(select(StayCreditRow))
        assert s.get(OrderRow, oid).status == 'CONFIRMED'
    assert connector.cancel_calls == before


def test_catalog_expiry_between_quote_and_acceptance_leaves_order_intact(client, monkeypatch):
    oid, created = future_catalog_order(client)
    t = created + timedelta(days=365) - timedelta(minutes=1)
    monkeypatch.setattr(catalog, 'now', lambda: t)
    q = catalog.conversion_quote(oid)
    monkeypatch.setattr(catalog, 'now', lambda: t + timedelta(minutes=2))
    before = connector.cancel_calls
    with pytest.raises(ValueError, match='ONE_YEAR_VALIDITY'):
        run(catalog.convert(oid, q['quote_id'], q['quote_hash'], True, 'owner'))
    assert connector.cancel_calls == before


def test_direct_late_conversion_does_not_renew_year(client, monkeypatch):
    r, account, *_ = booked(client, monkeypatch, rules={**RULES, 'credit_terms': value.TERMS})
    t = fare.now()
    created = t - timedelta(days=300)
    with SessionLocal.begin() as s:
        s.get(HostedDirectReservationRow, r['hosted_reservation_id']).created_at = created
    q = direct.conversion_quote(r['hosted_reservation_id'], account)
    expected = (created + timedelta(days=365)).isoformat()
    assert q['credit_expires_at'] == expected
    c = direct.convert(r['hosted_reservation_id'], account, q['quote_id'], q['retained_value_minor'], 'CNY')['credit']
    assert c['expires_at'] == expected
    assert direct.convert(r['hosted_reservation_id'], account, q['quote_id'], q['retained_value_minor'], 'CNY')['credit'] == c


def test_direct_expired_original_year_keeps_money_and_inventory(client, monkeypatch):
    from tests.test_depth07_hosted_money import summary, inventory
    r, account, *_ = booked(client, monkeypatch, rules={**RULES, 'credit_terms': value.TERMS})
    with SessionLocal.begin() as s:
        s.get(HostedDirectReservationRow, r['hosted_reservation_id']).created_at = fare.now() - timedelta(days=366)
    before_money, before_inventory = summary(r), inventory(r)
    with pytest.raises(ValueError, match='ONE_YEAR_VALIDITY'):
        direct.conversion_quote(r['hosted_reservation_id'], account)
    assert summary(r) == before_money and inventory(r) == before_inventory


def test_catalog_old_unaccepted_conversion_quote_requires_reconfirmation(client):
    from go_hotel.db.models import CatalogCreditQuoteRow
    from go_hotel.services.omnichannel_payment import digest
    oid = booked_order(client)
    q = catalog.conversion_quote(oid)
    with SessionLocal.begin() as s:
        row = s.get(CatalogCreditQuoteRow, q['quote_id'])
        row.payload_json = {k: v for k, v in row.payload_json.items() if k not in {
            'credit_policy', 'credit_validity_basis', 'credit_original_created_at', 'credit_quoted_at', 'credit_expires_at'}}
        row.payload_hash = digest(row.payload_json)
        legacy_hash = row.payload_hash
    before = connector.cancel_calls
    with pytest.raises(ValueError, match='REQUOTE_REQUIRED'):
        run(catalog.convert(oid, q['quote_id'], legacy_hash, True, 'owner'))
    assert connector.cancel_calls == before


def test_catalog_same_date_after_hotel_local_arrival_deadline_is_rejected(client, monkeypatch):
    from go_hotel.services import catalog_fare_snapshot as snapshot
    original = snapshot.demo_rules
    monkeypatch.setattr(snapshot, 'demo_rules', lambda: {**original(), 'timezone': 'Etc/GMT+12', 'check_in_hour': 23})
    oid = booked_order(client)
    q = catalog.conversion_quote(oid)
    c = run(catalog.convert(oid, q['quote_id'], q['quote_hash'], True, 'owner'))
    last = datetime.fromisoformat(c['expires_at']).date()
    with pytest.raises(ValueError, match='WITHIN_VALIDITY'):
        run(catalog.redemption_quote(c['stay_credit_id'], last.isoformat(), (last + timedelta(days=2)).isoformat()))
    assert catalog.get_credit(c['stay_credit_id'])['available_minor'] == c['available_minor']


def test_catalog_expiry_during_prebook_cannot_start_payment_or_supplier_booking(client, monkeypatch):
    from go_hotel.services import catalog_credit_value
    from tests.test_depth12_catalog_credit import dates, net
    oid = booked_order(client)
    q = catalog.conversion_quote(oid)
    c = run(catalog.convert(oid, q['quote_id'], q['quote_hash'], True, 'owner'))
    redeem_q = run(catalog.redemption_quote(c['stay_credit_id'], *dates(100)))
    original = connector.prebook_with_key
    before = connector.book_calls
    async def cross_deadline(offer, key):
        pb = await original(offer, key)
        expired = datetime.fromisoformat(c['expires_at']) + timedelta(seconds=1)
        monkeypatch.setattr(catalog, 'now', lambda: expired)
        monkeypatch.setattr(catalog_credit_value, 'now', lambda: expired)
        return pb
    monkeypatch.setattr(connector, 'prebook_with_key', cross_deadline)
    result = run(catalog.redeem(c['stay_credit_id'], redeem_q['quote_id'], redeem_q['quote_hash'], True, 'pm_success', 'owner'))
    assert result['status'] == 'FAILED' and connector.book_calls == before
    assert not net(result['order_id'])
    assert catalog.get_credit(c['stay_credit_id'])['status'] == 'EXPIRED'


def test_actual_native_credit_helper_matches_owner_checked_mobile_api(client):
    from tests.test_depth30_native_api_contract import bridge
    from tests.test_master03_closure import profile
    registered = register_synthetic_consumer(client, json={'email': 'depth47-native@example.test', 'password': 'IsolatedPass47!', 'display_name': 'ISOLATED CREDIT TEST'})
    assert registered.status_code == 200, registered.text
    uid = registered.json()['data']['profile']['user_id']
    token = client.post('/v1/mobile/auth/login', json={'email': 'depth47-native@example.test', 'password': 'IsolatedPass47!'}).json()['data']['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    client.cookies.clear()
    tid = profile(uid, name='ISOLATED CREDIT TRAVELER')
    ci = (datetime.now(timezone.utc) + timedelta(days=20)).date().isoformat()
    co = (datetime.now(timezone.utc) + timedelta(days=23)).date().isoformat()
    search = client.post('/v1/search/hotels', headers=headers, json={'destination': {'city_code': 'TYO'}, 'stay': {'check_in': ci, 'check_out': co}, 'occupancy': {'rooms': 1, 'adults': 1, 'children': 0}, 'currency': 'CNY'})
    offer = search.json()['data']['hotels'][0]['best_offer']
    pb = client.post(f"/v1/offers/{offer['offer_id']}/prebook", headers=headers, json={'currency': 'CNY'}).json()['data']
    order = bridge(client, headers, {'action': 'create', 'vertical': 'HOTEL', 'params': {'prebook': pb}, 'userId': uid, 'travelerId': tid})['data']
    task = {'vertical': 'HOTEL', 'orderId': order['order_id']}
    assert bridge(client, headers, {**task, 'action': 'pay'})['order']['status'] == 'CONFIRMED'
    result = bridge(client, headers, {**task, 'action': 'credit'})
    assert result['order']['status'] == 'CONVERTED_TO_CREDIT'
    assert result['notice'] == 'CREDIT_REQUEST_SUBMITTED'
    with SessionLocal() as s:
        credit = s.scalar(select(StayCreditRow).where(StayCreditRow.original_order_id == order['order_id']))
        original = s.get(OrderRow, order['order_id'])
        assert credit.expires_at == original.created_at + timedelta(days=365)
        assert credit.account_id == uid
    assert connector.cancel_calls == 1
