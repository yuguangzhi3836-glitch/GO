"""C06: server supplied, frozen IANA-zone windows; no invented supplier policy."""
from copy import deepcopy
from datetime import datetime, UTC
import pytest
from sqlalchemy import select

from go_hotel.attractions.service import attraction_service as svc, CATALOG
from go_hotel.attractions import service
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import AttractionOrderRow, VerticalPrebookContractRow as Contract
from test_depth21_refund_recovery import booked


POLICY = {'destination_timezone': 'Asia/Tokyo', 'opens_minutes_before_session': 30,
          'closes_minutes_after_session': 120, 'policy_reference': 'isolated-supplier://frozen-policy/v1'}


def install(monkeypatch, **overrides):
    policy = {**POLICY, **overrides}
    monkeypatch.setitem(CATALOG['tokyo_skytree'], 'supplier_validity_policy', policy)
    return policy


def test_prebook_freezes_server_policy_and_utc_boundary(monkeypatch):
    install(monkeypatch)
    quote = svc.prebook('tokyo_skytree', '2026-09-15', 1)
    window = quote['redemption_window']
    assert window['state'] == 'FROZEN_SUPPLIER_WINDOW'
    assert window['destination_timezone'] == 'Asia/Tokyo'
    assert window['opens_at'] == '2026-09-15T06:30:00+00:00'
    assert window['closes_at'] == '2026-09-15T09:00:00+00:00'
    assert window['boundary'] == '[opens_at,closes_at)'
    with SessionLocal() as session:
        assert session.get(Contract, quote['prebook_id']).terms_json['redemption_window'] == window


@pytest.mark.parametrize('instant,allowed', [
    ('2026-09-15T06:29:59.999+00:00', False),
    ('2026-09-15T06:30:00+00:00', True),
    ('2026-09-15T08:59:59.999+00:00', True),
    ('2026-09-15T09:00:00+00:00', False),
])
def test_redemption_respects_exact_half_open_window(monkeypatch, instant, allowed):
    install(monkeypatch)
    _, owner, oid = booked('ATTRACTION')
    at = int(datetime.fromisoformat(instant).timestamp()*1000)
    # The service uses DB time; this controls that clock at a fixed boundary.
    monkeypatch.setattr(service, 'db_now_ms', lambda session: at, raising=False)
    if allowed:
        assert svc.redeem(owner, oid, 'isolated://entry')['status'] == 'FULFILLED'
    else:
        with pytest.raises(ValueError, match='ATTRACTION_OUTSIDE_SUPPLIER_VALIDITY_WINDOW'):
            svc.redeem(owner, oid, 'isolated://entry')
        assert svc.get(owner, oid)['status'] == 'CONFIRMED'
        assert not [x for x in svc.get(owner, oid)['evidence'] if x['kind'] == 'VOUCHER_REDEEMED']


def test_later_catalog_policy_cannot_rewrite_consumed_contract(monkeypatch):
    install(monkeypatch)
    _, owner, oid = booked('ATTRACTION')
    original = deepcopy(svc.get(owner, oid)['redemption_window'])
    install(monkeypatch, destination_timezone='Europe/London', closes_minutes_after_session=1)
    assert svc.get(owner, oid)['redemption_window'] == original
    monkeypatch.setattr(service, 'db_now_ms', lambda session: int(datetime(2026,9,15,8,0,tzinfo=UTC).timestamp()*1000), raising=False)
    assert svc.redeem(owner, oid, 'isolated://entry')['status'] == 'FULFILLED'


@pytest.mark.parametrize('day,session', [('2026-03-08', '02:30'), ('2026-11-01', '01:30')])
def test_nonexistent_or_ambiguous_supplier_local_session_requires_review(monkeypatch, day, session):
    install(monkeypatch, destination_timezone='America/New_York')
    monkeypatch.setitem(CATALOG['tokyo_skytree'], 'sessions', [session])
    with pytest.raises(ValueError, match='ATTRACTION_SUPPLIER_LOCAL_TIME_REVIEW_REQUIRED'):
        svc.prebook('tokyo_skytree', day, 1, session_time=session)
    with SessionLocal() as connection:
        assert not list(connection.scalars(select(Contract)))


def test_cross_midnight_window_uses_supplier_timezone_not_server_date(monkeypatch):
    install(monkeypatch)
    monkeypatch.setitem(CATALOG['tokyo_skytree'], 'sessions', ['00:15'])
    quote = svc.prebook('tokyo_skytree', '2026-09-15', 1, session_time='00:15')
    assert quote['redemption_window']['opens_at'] == '2026-09-14T14:45:00+00:00'
    assert quote['redemption_window']['closes_at'] == '2026-09-14T17:15:00+00:00'


@pytest.mark.parametrize('bad', [
    {'destination_timezone': 'not/a-zone'}, {'opens_minutes_before_session': True},
    {'closes_minutes_after_session': 0}, {'policy_reference': ''},
])
def test_invalid_supplier_policy_never_issues_a_quote(monkeypatch, bad):
    install(monkeypatch, **bad)
    with pytest.raises(ValueError, match='ATTRACTION_SUPPLIER_VALIDITY_POLICY_INVALID'):
        svc.prebook('tokyo_skytree', '2026-09-15', 1)


def test_missing_supplier_policy_is_explicitly_legacy_unverified():
    quote = svc.prebook('tokyo_skytree', '2026-09-15', 1)
    assert quote['redemption_window'] == {'state': 'LEGACY_UNVERIFIED'}


def test_client_cannot_supply_a_validity_policy(monkeypatch):
    install(monkeypatch)
    quote = svc.prebook('tokyo_skytree', '2026-09-15', 1)
    body = {'prebook_id': quote['prebook_id'], 'offer_id': 'tokyo_skytree',
            'visit_date': '2026-09-15', 'quantity': 1, 'attendees': [{'full_name': 'A'}],
            'supplier_validity_policy': {**POLICY, 'closes_minutes_after_session': 999999}}
    with pytest.raises(ValueError, match='ATTRACTION_VALIDITY_CLIENT_FIELD_FORBIDDEN'):
        svc.create_order('owner', body)
    with SessionLocal() as connection:
        assert not list(connection.scalars(select(AttractionOrderRow)))


def test_deleting_frozen_window_without_resealing_cannot_downgrade_to_legacy(monkeypatch):
    install(monkeypatch)
    _, owner, oid = booked('ATTRACTION')
    with SessionLocal.begin() as session:
        contract = session.scalar(select(Contract).where(Contract.order_id == oid))
        changed = dict(contract.terms_json)
        changed.pop('redemption_window')
        contract.terms_json = changed
    with pytest.raises(ValueError, match='ATTRACTION_LEGACY_TERMS_REVIEW_REQUIRED'):
        svc.redeem(owner, oid, 'isolated://tampered-entry')
    with SessionLocal() as session:
        assert session.get(AttractionOrderRow, oid).status == 'CONFIRMED'


def test_missing_contract_cannot_downgrade_a_confirmed_order_to_legacy(monkeypatch):
    install(monkeypatch)
    _, owner, oid = booked('ATTRACTION')
    with SessionLocal.begin() as session:
        session.delete(session.scalar(select(Contract).where(Contract.order_id == oid)))
    with pytest.raises(ValueError, match='ATTRACTION_LEGACY_TERMS_REVIEW_REQUIRED'):
        svc.redeem(owner, oid, 'isolated://missing-contract')
    with SessionLocal() as session:
        assert session.get(AttractionOrderRow, oid).status == 'CONFIRMED'


def test_supplier_confirmed_date_change_uses_frozen_policy_on_new_session(monkeypatch):
    install(monkeypatch)
    _, owner, oid = booked('ATTRACTION')
    quote = svc.change_quote(owner, oid, '2026-09-16', '17:00')
    svc.execute_change(owner, oid, quote['quote_id'])
    assert svc.get(owner, oid)['status'] == 'UNKNOWN_EXTERNAL_STATE'
    svc.admin_external_state(oid, 'CONFIRMED', 'isolated://change-proof', 'ops', 'NEW-SUPPLIER', 'NEW-VOUCHER')
    window = svc.get(owner, oid)['redemption_window']
    assert window['opens_at'] == '2026-09-16T07:30:00+00:00'
    assert window['closes_at'] == '2026-09-16T10:00:00+00:00'
    # Old valid window cannot redeem the new supplier-confirmed session.
    monkeypatch.setattr(service, 'db_now_ms', lambda session: int(datetime(2026,9,15,8,0,tzinfo=UTC).timestamp()*1000))
    with pytest.raises(ValueError, match='ATTRACTION_OUTSIDE_SUPPLIER_VALIDITY_WINDOW'):
        svc.redeem(owner, oid, 'isolated://old-session-entry')


def test_valid_window_does_not_bypass_inflight_refund_exclusion(monkeypatch):
    from test_depth21_refund_recovery import test_concurrent_refund_has_one_executor_and_blocks_change_or_redeem
    install(monkeypatch)
    monkeypatch.setattr(service, 'db_now_ms', lambda session: int(datetime(2026,9,15,8,0,tzinfo=UTC).timestamp()*1000))
    test_concurrent_refund_has_one_executor_and_blocks_change_or_redeem('ATTRACTION', monkeypatch)


# Collect the Issue #146 internal fixture matrix in the already-admitted C06 shard.
from tests.test_c06_internal_policy_registry import *  # noqa: F401,F403,E402


# Collect the successor raw-byte binding matrix in the admitted C06 shard.
from tests.test_v70_r5_c06_raw_payload_binding import *  # noqa: F401,F403,E402
