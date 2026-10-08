"""C01 R4: durable, authority-bound UNKNOWN episodes for mixed hotel funds."""
import pytest
from sqlalchemy import select

from go_hotel.db.models import (
    AlipayAuthorizationRow as Authorization,
    HostedStayCreditRow as Credit,
    HostedMoneyUnknownEpisodeRow as Episode,
    HostedMoneyUnknownEpisodeAuditRow as Audit,
)
from go_hotel.db.session import SessionLocal
from go_hotel.security.service import identity_service
from go_hotel.services import hosted_money
from tests.test_sprint3a_flight import auth as consumer_headers
from tests.test_v70_next_c01_unknown_funding import (
    ready, allocation_state, summary, payment,
)


def funding_movement(authorization_id, credit_id, source):
    with SessionLocal() as session:
        authorization = session.get(Authorization, authorization_id)
        if source == 'cash_authorization':
            return next(
                movement.money_movement_id
                for movement in hosted_money.active_movements(session, authorization)
                if movement.movement_type == 'AUTHORIZATION'
            )
        return session.get(Credit, credit_id).source_capture_id


@pytest.mark.parametrize('source', ['cash_authorization', 'credit_capture'])
def test_episode_digest_fences_resolution_and_mixed_settlement(client, monkeypatch, source):
    order, authorization_id, credit = ready(client, monkeypatch)
    movement_id = funding_movement(authorization_id, credit['credit_id'], source)
    opened = hosted_money.open_unknown_episode(
        authorization_id, movement_id, 'provider://timeout/req-1',
        {'provider_request_id': 'req-1', 'observation': 'TIMEOUT_AFTER_SEND'},
        'ops-maker',
    )
    assert opened['status'] == 'OPEN' and opened['episode_generation'] == 1
    assert opened['funding_leg'] == (
        'CASH_AUTHORIZATION' if source == 'cash_authorization'
        else 'STAY_CREDIT_SOURCE_CAPTURE'
    )
    replay = hosted_money.open_unknown_episode(
        authorization_id, movement_id, 'provider://timeout/req-1',
        {'provider_request_id': 'req-1', 'observation': 'TIMEOUT_AFTER_SEND'},
        'ops-maker',
    )
    assert replay['episode_id'] == opened['episode_id'] and replay['replay'] is True

    before = allocation_state(order)
    with pytest.raises(ValueError, match='RECONCILIATION_REQUIRED|FUNDING_FACT_MISMATCH'):
        payment.capture(authorization_id, {'mode': 'CONTRACT_DRY_RUN'})
    assert allocation_state(order) == before
    with pytest.raises(ValueError, match='OPEN_DIGEST_MISMATCH'):
        hosted_money.resolve_unknown_episode(
            opened['episode_id'], 'CONFIRMED', '0' * 64,
            'provider://status/req-1', {'state': 'CONFIRMED'}, 'ops-checker',
        )

    resolved = hosted_money.resolve_unknown_episode(
        opened['episode_id'], 'CONFIRMED', opened['open_evidence_digest'],
        'provider://status/req-1',
        {'state': 'CONFIRMED', 'provider_reference': 'provider-confirm-1'},
        'ops-checker',
    )
    assert resolved['status'] == 'RESOLVED_CONFIRMED'
    same = hosted_money.resolve_unknown_episode(
        opened['episode_id'], 'CONFIRMED', opened['open_evidence_digest'],
        'provider://status/req-1',
        {'state': 'CONFIRMED', 'provider_reference': 'provider-confirm-1'},
        'ops-checker',
    )
    assert same['replay'] is True

    with SessionLocal() as session:
        audits = list(session.scalars(
            select(Audit).where(Audit.episode_id == opened['episode_id'])
            .order_by(Audit.sequence)
        ))
        assert [row.event_type for row in audits] == [
            'UNKNOWN_OPENED', 'UNKNOWN_RESOLVED_CONFIRMED',
        ]
        assert audits[0].previous_hash is None
        assert audits[1].previous_hash == audits[0].event_hash
        assert len(audits[0].evidence_digest) == len(audits[1].evidence_digest) == 64

    payment.capture(authorization_id, {'mode': 'CONTRACT_DRY_RUN'})
    funds = summary(order)
    assert funds['capture_minor'] == 38000 and funds['held_minor'] == 0
    assert allocation_state(order)[0:2] == ('SETTLED', 162000)



def test_unknown_movement_without_open_episode_fails_closed_without_writes(client, monkeypatch):
    _, authorization_id, credit = ready(client, monkeypatch)
    movement_id = funding_movement(
        authorization_id, credit['credit_id'], 'cash_authorization',
    )
    with SessionLocal.begin() as session:
        authorization = session.get(Authorization, authorization_id)
        movement = next(
            movement for movement in hosted_money.active_movements(session, authorization)
            if movement.money_movement_id == movement_id
        )
        movement.state = 'UNKNOWN_EXTERNAL_STATE'

    with pytest.raises(ValueError, match='UNKNOWN_EPISODE_CONFIRMED_FUNDING_REQUIRED'):
        hosted_money.open_unknown_episode(
            authorization_id, movement_id, 'provider://timeout/orphan-unknown',
            {'provider_request_id': 'orphan-unknown'}, 'ops-maker',
        )

    with SessionLocal() as session:
        authorization = session.get(Authorization, authorization_id)
        movement = next(
            movement for movement in hosted_money.active_movements(session, authorization)
            if movement.money_movement_id == movement_id
        )
        assert movement.state == 'UNKNOWN_EXTERNAL_STATE'
        assert session.scalars(select(Episode)).all() == []
        assert session.scalars(select(Audit)).all() == []


def test_episode_and_movement_rollback_when_audit_write_fails(client, monkeypatch):
    _, authorization_id, credit = ready(client, monkeypatch)
    movement_id = funding_movement(
        authorization_id, credit['credit_id'], 'cash_authorization',
    )

    def fail_audit(*args, **kwargs):
        raise RuntimeError('AUDIT_STORE_UNAVAILABLE')

    monkeypatch.setattr(hosted_money, '_append_unknown_audit', fail_audit)
    with pytest.raises(RuntimeError, match='AUDIT_STORE_UNAVAILABLE'):
        hosted_money.open_unknown_episode(
            authorization_id, movement_id, 'provider://timeout/rollback',
            {'provider_request_id': 'rollback'}, 'ops-maker',
        )
    with SessionLocal() as session:
        authorization = session.get(Authorization, authorization_id)
        movement = next(
            movement for movement in hosted_money.active_movements(session, authorization)
            if movement.money_movement_id == movement_id
        )
        assert movement.state == 'CONFIRMED'
        assert session.scalars(select(Episode)).all() == []
