"""Rental recovery must prove the current phase and UNKNOWN episode."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest
from sqlalchemy import delete, select

from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as Evidence
from go_hotel.db.session import SessionLocal
from go_hotel.mobility.service import mobility_service
from go_hotel.security.service import identity_service
from go_hotel.services.rc20_vertical_evidence import _stable_hash
from tests.test_depth33_mobility_refund_consent import booked


def resolve(oid, state, episode, evidence='isolated://rental-resolution'):
    return mobility_service.admin_external_state(oid, state, evidence, 'rental-ops', episode)


@pytest.mark.parametrize('phase', ['CONFIRMED', 'IN_PROGRESS'])
@pytest.mark.parametrize('state', ['CONFIRMED', 'FAILED'])
@pytest.mark.parametrize('fault', [
    'missing_last', 'missing_all', 'payload_corruption', 'invalid_phase',
    'contradictory_phase', 'foreign_row',
])
def test_invalid_unknown_evidence_never_restores_or_terminates_rental(phase, state, fault):
    svc, owner, oid = booked('RENTAL')
    if phase == 'IN_PROGRESS':
        svc.fulfill(owner, oid, 'PICKUP', 'isolated://rental-pickup')
    episode = 'isolated://rental-unknown'
    svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', episode, 'rental-ops')
    with SessionLocal.begin() as session:
        rows = list(session.scalars(select(Evidence).where(
            Evidence.execution_id == 'rc20:RENTAL:' + oid).order_by(Evidence.sequence_no)))
        last = rows[-1]
        if fault == 'missing_last':
            session.delete(last)
        elif fault == 'missing_all':
            session.execute(delete(Evidence).where(Evidence.execution_id == 'rc20:RENTAL:' + oid))
        elif fault == 'foreign_row':
            rows[0].execution_item_id = 'other-rental-order'
        else:
            body = deepcopy(last.evidence_json)
            body['payload']['previous_status'] = 'IN_PROGRESS' if phase == 'CONFIRMED' else 'CONFIRMED'
            if fault == 'invalid_phase':
                body['payload']['previous_status'] = 'COMPLETED'
            last.evidence_json = body
            if fault != 'payload_corruption':
                last.evidence_hash = _stable_hash(body)
                last.entry_hash = _stable_hash({'evidence_hash': last.evidence_hash,
                    'previous_hash': last.previous_hash, 'sequence_no': last.sequence_no})
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='RENTAL_RECOVERY_EVIDENCE_INVALID'):
        resolve(oid, state, episode)
    assert svc.get(owner, oid) == before


@pytest.mark.parametrize('state', ['CONFIRMED', 'FAILED'])
@pytest.mark.parametrize('episode', [None, '', 'isolated://previous-episode'])
def test_missing_or_older_confirmation_cannot_resolve_current_episode(state, episode):
    svc, owner, oid = booked('RENTAL')
    first = 'isolated://previous-episode'
    svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', first, 'rental-ops')
    assert resolve(oid, 'CONFIRMED', first)['status'] == 'CONFIRMED'
    svc.fulfill(owner, oid, 'PICKUP', 'isolated://rental-pickup')
    second = 'isolated://current-episode'
    svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', second, 'rental-ops')
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='RENTAL_CONFIRMATION_EPISODE_MISMATCH'):
        resolve(oid, state, episode)
    assert svc.get(owner, oid) == before
    assert resolve(oid, state, second)['status'] == ('IN_PROGRESS' if state == 'CONFIRMED' else 'FAILED')


def test_resolved_episode_reference_cannot_be_reopened():
    svc, owner, oid = booked('RENTAL')
    episode = 'isolated://stable-rental-episode'
    svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', episode, 'rental-ops')
    resolve(oid, 'CONFIRMED', episode)
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='RENTAL_UNKNOWN_EPISODE_REFERENCE_REUSED'):
        svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', episode, 'rental-ops')
    assert svc.get(owner, oid) == before


@pytest.mark.parametrize('fault', ['foreign_row', 'missing_all'])
def test_damaged_history_cannot_open_unknown_episode(fault):
    svc, owner, oid = booked('RENTAL')
    with SessionLocal.begin() as session:
        rows = list(session.scalars(select(Evidence).where(
            Evidence.execution_id == 'rc20:RENTAL:' + oid).order_by(Evidence.sequence_no)))
        if fault == 'foreign_row':
            rows[0].execution_item_id = 'other-rental-order'
        else:
            session.execute(delete(Evidence).where(Evidence.execution_id == 'rc20:RENTAL:' + oid))
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='RENTAL_RECOVERY_EVIDENCE_INVALID'):
        svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://new-unknown', 'rental-ops')
    assert svc.get(owner, oid) == before


def test_concurrent_unknown_open_has_one_winner_and_single_episode():
    svc, owner, oid = booked('RENTAL')
    barrier = Barrier(6)

    def open_episode(index):
        barrier.wait()
        try:
            svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', f'isolated://race-{index}', 'rental-ops')
            return index
        except ValueError as error:
            assert str(error) == 'RENTAL_UNKNOWN_EPISODE_ALREADY_OPEN'
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(open_episode, range(6)))
    winner, = [value for value in results if value is not None]
    events = [e for e in svc.get(owner, oid)['evidence'] if e['kind'] == 'EXTERNAL_STATE_UNKNOWN']
    assert len(events) == 1
    assert events[0]['payload']['evidence_reference'] == f'isolated://race-{winner}'


def test_real_admin_http_preserves_rental_episode_binding(client):
    svc, owner, oid = booked('RENTAL')
    identity_service.create_user('c04_recovery_admin', 'local-recovery-admin-pass',
                                 'GO_ADMIN', None, ['GO_SUPER_ADMIN'])
    token = identity_service.login('c04_recovery_admin', 'local-recovery-admin-pass',
                                   expected_actor_type='GO_ADMIN')['access_token']
    headers = {'Authorization': 'Bearer ' + token, 'X-GO-Actor': 'GO_ADMIN'}
    path = f'/internal/v1/admin/mobility/orders/{oid}/external-state'
    opened = client.post(path, headers=headers, json={
        'state': 'UNKNOWN_EXTERNAL_STATE', 'evidence_reference': 'isolated://http-episode'})
    assert opened.status_code == 200, opened.text
    before = svc.get(owner, oid)
    denied = client.post(path, headers=headers, json={
        'state': 'CONFIRMED', 'evidence_reference': 'isolated://http-confirm',
        'confirmation_episode_reference': 'isolated://other-episode'})
    assert denied.status_code in {404, 409, 422}, denied.text
    assert denied.json()['detail'] == 'RENTAL_CONFIRMATION_EPISODE_MISMATCH'
    assert svc.get(owner, oid) == before
    accepted = client.post(path, headers=headers, json={
        'state': 'CONFIRMED', 'evidence_reference': 'isolated://http-confirm',
        'confirmation_episode_reference': 'isolated://http-episode'})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['data']['status'] == 'CONFIRMED'
    assert svc.get(owner, oid)['evidence'][-1]['payload']['confirmation_episode_reference'] == 'isolated://http-episode'
