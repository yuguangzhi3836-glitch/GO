"""An old quote or supplier response cannot mutate a later change episode."""
import pytest
from test_depth21_refund_recovery import booked


def test_rail_old_fare_quote_cannot_execute_after_another_change():
    svc, owner, oid = booked('RAIL')
    first = svc.change_quote(owner, oid, '2026-09-16', 'FIRST_CLASS')
    stale = svc.change_quote(owner, oid, '2026-09-17', 'SECOND_CLASS')
    svc.execute_change(owner, oid, first['quote_id'])
    svc.admin_external_state(oid, 'TICKETED', 'isolated://first', 'ops', 'BOOK-NEW', ['N-A', 'N-B'], first['quote_id'])
    before = svc.order(owner, oid)
    with pytest.raises(ValueError, match='RAIL_CHANGE_QUOTE_INVALID'):
        svc.execute_change(owner, oid, stale['quote_id'])
    assert svc.order(owner, oid) == before
    fresh = svc.change_quote(owner, oid, '2026-09-17', 'SECOND_CLASS')
    assert fresh['fare_difference_minor'] != stale['fare_difference_minor']


def attraction_second_change():
    svc, owner, oid = booked('ATTRACTION')
    first = svc.change_quote(owner, oid, '2026-09-16')
    svc.execute_change(owner, oid, first['quote_id'])
    svc.admin_external_state(oid, 'CONFIRMED', 'isolated://first', 'ops', 'SUP-FIRST', 'V-FIRST', first['quote_id'])
    second = svc.change_quote(owner, oid, '2026-09-17')
    svc.execute_change(owner, oid, second['quote_id'])
    return svc, owner, oid, first, second


def test_attraction_delayed_unbound_confirmation_cannot_confirm_next_change():
    svc, owner, oid, first, second = attraction_second_change()
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='ATTRACTION_RESOLUTION_QUOTE_ID_REQUIRED'):
        svc.admin_external_state(oid, 'CONFIRMED', 'isolated://first', 'ops', 'SUP-FIRST', 'V-FIRST')
    assert svc.get(owner, oid) == before


def test_attraction_current_change_submission_is_replay_safe():
    svc, owner, oid = booked('ATTRACTION')
    q = svc.change_quote(owner, oid, '2026-09-16')
    first = svc.execute_change(owner, oid, q['quote_id'])
    before = svc.get(owner, oid)
    assert svc.execute_change(owner, oid, q['quote_id']) == first
    assert svc.get(owner, oid) == before


@pytest.mark.parametrize('state', ['CONFIRMED', 'CLOSED_BY_SUPPLIER'])
def test_attraction_old_quote_cannot_resolve_current_episode(state):
    svc, owner, oid, first, second = attraction_second_change()
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='ATTRACTION_RESOLUTION_QUOTE_INVALID'):
        svc.admin_external_state(oid, state, 'isolated://old', 'ops', 'SUP-FIRST', 'V-FIRST', first['quote_id'])
    assert svc.get(owner, oid) == before
    result = svc.admin_external_state(oid, state, 'isolated://second', 'ops', 'SUP-SECOND', 'V-SECOND', second['quote_id'])
    assert result['status'] == state
    if state == 'CONFIRMED':
        assert result['visit_date'] == '2026-09-17'
        assert result['voucher_code'] == 'V-SECOND'


def test_attraction_api_carries_quote_identity_and_replays_bound_request(client):
    from types import SimpleNamespace
    from go_hotel.security.deps import admin_principal
    from go_hotel.main import app
    svc, owner, oid, first, second = attraction_second_change()
    app.dependency_overrides[admin_principal] = lambda: SimpleNamespace(user_id='ops')
    try:
        endpoint = f'/internal/v1/admin/attractions/orders/{oid}/external-state'
        body = {'state': 'CONFIRMED', 'evidence_reference': 'isolated://second',
                'supplier_reference': 'SUP-SECOND', 'voucher_code': 'V-SECOND'}
        denied = client.post(endpoint, json=body)
        assert denied.status_code == 409
        assert denied.json()['detail'] == 'ATTRACTION_RESOLUTION_QUOTE_ID_REQUIRED'
        body['quote_id'] = first['quote_id']
        assert client.post(endpoint, json=body).status_code == 409
        body['quote_id'] = second['quote_id']
        headers = {'Idempotency-Key': 'c06-second-bound-confirmation'}
        accepted = client.post(endpoint, json=body, headers=headers)
        assert accepted.status_code == 200
        assert accepted.json()['data']['voucher_code'] == 'V-SECOND'
        assert client.post(endpoint, json=body, headers=headers).json() == accepted.json()
    finally:
        app.dependency_overrides.pop(admin_principal, None)


def test_prechange_reconciliation_cannot_resolve_first_change():
    svc, owner, oid = booked('ATTRACTION')
    svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://old-unknown', 'ops')
    svc.admin_external_state(oid, 'CONFIRMED', 'isolated://old-confirm', 'ops', 'OLD-SUP', 'OLD-VOUCHER')
    quote = svc.change_quote(owner, oid, '2026-09-17')
    svc.execute_change(owner, oid, quote['quote_id'])
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='ATTRACTION_RESOLUTION_QUOTE_ID_REQUIRED'):
        svc.admin_external_state(oid, 'CONFIRMED', 'isolated://old-confirm', 'ops', 'OLD-SUP', 'OLD-VOUCHER')
    assert svc.get(owner, oid) == before
    result = svc.admin_external_state(oid, 'CONFIRMED', 'isolated://bound-first', 'ops', 'NEW-SUP', 'NEW-VOUCHER', quote['quote_id'])
    assert result['voucher_code'] == 'NEW-VOUCHER'
