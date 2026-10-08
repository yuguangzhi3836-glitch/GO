"""Current-main integration boundaries, beyond the retained historical nodes."""
import pytest
from sqlalchemy import select
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.services import hosted_money
from go_hotel.services.hosted_direct_booking import ident, now
from go_hotel.security.service import identity_service
from tests.test_v70_next_c01_unknown_funding import ready
from tests.test_v70_r4_c01_unknown_episode import funding_movement


def fixture(client, monkeypatch):
    order, aid, credit = ready(client, monkeypatch)
    mid = funding_movement(aid, credit['credit_id'], 'cash_authorization')
    return order, aid, mid


def open_episode(aid, mid, request='one'):
    return hosted_money.open_unknown_episode(aid, mid, 'isolated://' + request, {'request': request}, 'maker')


def resolve(ep):
    return hosted_money.resolve_unknown_episode(ep['episode_id'], 'CONFIRMED', ep['open_evidence_digest'], 'isolated://confirm', {'state': 'CONFIRMED'}, 'checker')


def test_old_episode_cannot_resolve_new_generation(client, monkeypatch):
    _, aid, mid = fixture(client, monkeypatch)
    first = open_episode(aid, mid)
    resolve(first)
    second = open_episode(aid, mid, 'two')
    assert second['episode_generation'] == 2
    with pytest.raises(ValueError, match='UNKNOWN_EPISODE_STALE'):
        resolve(first)
    with SessionLocal() as session:
        assert session.get(m.OmnichannelMoneyMovementRow, mid).state == 'UNKNOWN_EXTERNAL_STATE'
        assert session.get(m.HostedMoneyUnknownEpisodeRow, second['episode_id']).status == 'OPEN'
    resolve(second)


def test_lost_open_response_after_resolution_does_not_reopen(client, monkeypatch):
    _, aid, mid = fixture(client, monkeypatch)
    ep = open_episode(aid, mid)
    resolve(ep)
    replay = open_episode(aid, mid)
    assert replay['replay'] is True and replay['episode_id'] == ep['episode_id']
    assert replay['status'] == 'RESOLVED_CONFIRMED'
    with SessionLocal() as session:
        assert session.get(m.OmnichannelMoneyMovementRow, mid).state == 'CONFIRMED'
        assert len(session.scalars(select(m.HostedMoneyUnknownEpisodeRow)).all()) == 1


def test_resolved_replay_refuses_untracked_movement_drift(client, monkeypatch):
    _, aid, mid = fixture(client, monkeypatch)
    ep = open_episode(aid, mid)
    resolve(ep)
    with SessionLocal.begin() as session:
        session.get(m.OmnichannelMoneyMovementRow, mid).state = 'UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError, match='UNKNOWN_EPISODE_MOVEMENT_STATE_MISMATCH'):
        resolve(ep)


def test_conflicting_open_and_resolution_audit_failure_are_zero_write(client, monkeypatch):
    _, aid, mid = fixture(client, monkeypatch)
    ep = open_episode(aid, mid)
    with pytest.raises(ValueError, match='UNKNOWN_EPISODE_EVIDENCE_CONFLICT'):
        open_episode(aid, mid, 'different')
    def fail(*args, **kwargs):
        raise RuntimeError('AUDIT_STORE_UNAVAILABLE')
    monkeypatch.setattr(hosted_money, '_append_unknown_audit', fail)
    with pytest.raises(RuntimeError, match='AUDIT_STORE_UNAVAILABLE'):
        resolve(ep)
    with SessionLocal() as session:
        assert session.get(m.OmnichannelMoneyMovementRow, mid).state == 'UNKNOWN_EXTERNAL_STATE'
        assert session.get(m.HostedMoneyUnknownEpisodeRow, ep['episode_id']).status == 'OPEN'
        assert len(session.scalars(select(m.HostedMoneyUnknownEpisodeAuditRow)).all()) == 1


def test_recovery_forbidden_outside_isolation_and_for_external_authorization(client, monkeypatch):
    _, aid, mid = fixture(client, monkeypatch)
    from go_hotel.core.config import settings
    monkeypatch.setattr(settings, 'app_env', 'production')
    with pytest.raises(ValueError, match='SIMULATED_CHECKOUT_FORBIDDEN'):
        open_episode(aid, mid)
    monkeypatch.setattr(settings, 'app_env', 'test')
    with SessionLocal.begin() as session:
        session.get(m.AlipayAuthorizationRow, aid).external_invoked = True
    with pytest.raises(ValueError, match='UNKNOWN_REAL_PROVIDER_RECOVERY_UNVERIFIED'):
        open_episode(aid, mid)
    with SessionLocal() as session:
        assert session.get(m.OmnichannelMoneyMovementRow, mid).state == 'CONFIRMED'
        assert session.scalars(select(m.HostedMoneyUnknownEpisodeRow)).all() == []


def test_http_requires_reserved_hotel_scope_and_rechecks_revocation(client, monkeypatch):
    order, aid, mid = fixture(client, monkeypatch)
    identity_service.create_user('unknown-review-admin', 'Unknown-Test-Password123!', 'GO_ADMIN', None, ['GO_GOVERNANCE'])
    token = identity_service.login('unknown-review-admin', 'Unknown-Test-Password123!')['access_token']
    principal = identity_service.authenticate(token)
    headers = {'Authorization': 'Bearer ' + token}
    path = f'/internal/v1/alipay/authorizations/{aid}/funding-movements/{mid}/unknown-episodes'
    body = {'evidence_reference': 'isolated://http', 'evidence': {'request': 'one'}}
    assert client.post(path, json=body).status_code == 401
    assert client.post(path, headers=headers, json=body).status_code == 403
    monkeypatch.setenv('GO_HOSTED_OPERATIONS_AUTHORITY_MODE', 'ISOLATED_FIXTURE')
    with SessionLocal.begin() as session:
        reservation = session.get(m.HostedDirectReservationRow, order['hosted_reservation_id'])
        hotel = session.get(m.HostedDirectRoomOfferRow, reservation.hosted_offer_id).hosted_hotel_id
        session.add(m.HostedStaffRoleRow(staff_role_id='unknown-fixture-grant', hosted_hotel_id=hotel + '-other', staff_id=principal.user_id, role='HOTEL_OPERATIONS_ADMIN', state='ACTIVE', evidence_reference='isolated://hosted-operations-authority/v1', created_at=now()))
    assert client.post(path, headers=headers, json=body).status_code == 403
    with SessionLocal() as session:
        assert session.scalars(select(m.HostedMoneyUnknownEpisodeRow)).all() == []
        assert session.get(m.OmnichannelMoneyMovementRow, mid).state == 'CONFIRMED'
    with SessionLocal.begin() as session:
        session.get(m.HostedStaffRoleRow, 'unknown-fixture-grant').hosted_hotel_id = hotel
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 200, response.text
    ep = response.json()['data']
    resolve_path = f"/internal/v1/alipay/unknown-funding-episodes/{ep['episode_id']}/resolve"
    resolution = {'expected_open_evidence_digest': ep['open_evidence_digest'], 'evidence_reference': 'isolated://resolved', 'evidence': {'state': 'CONFIRMED'}}
    with SessionLocal.begin() as session:
        session.get(m.HostedStaffRoleRow, 'unknown-fixture-grant').state = 'REVOKED'
    assert client.post(resolve_path, headers=headers, json=resolution).status_code == 403
    with SessionLocal.begin() as session:
        assert session.get(m.OmnichannelMoneyMovementRow, mid).state == 'UNKNOWN_EXTERNAL_STATE'
        session.get(m.HostedStaffRoleRow, 'unknown-fixture-grant').state = 'ACTIVE'
    assert client.post(resolve_path, headers=headers, json=resolution).status_code == 200
    assert client.post(resolve_path, headers=headers, json=resolution).json()['data']['replay'] is True


def test_staff_form_cannot_mint_reserved_recovery_scope(client):
    from go_hotel.services.hosted_frontdesk_uat import hosted_frontdesk_uat_service
    with pytest.raises(ValueError, match='VALID_STAFF_ROLE_EVIDENCE_REQUIRED'):
        hosted_frontdesk_uat_service.assign_role('any-hotel', {'role': 'HOTEL_OPERATIONS_ADMIN', 'staff_id': 'admin', 'evidence_reference': 'isolated://hosted-operations-authority/v1'}, 'admin')
