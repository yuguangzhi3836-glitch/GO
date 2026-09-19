"""Account-fence SQL intent and local interleavings; no live PostgreSQL claim."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select, update

from go_hotel.db.models import ProfileImportJobRow
from go_hotel.db.session import SessionLocal
from go_hotel.services import personal_travel_vault as module
from go_hotel.services import personal_vault_management as management

svc = module.personal_travel_vault_service


@pytest.mark.no_db
def test_postgres_fence_is_parameterized_transaction_scoped_and_account_scoped():
    calls = []
    session = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name='postgresql')),
        execute=lambda statement, params: calls.append((str(statement), params)))
    management.lock_vault_account(session, "owner'; SELECT other_account")
    management.lock_vault_account(session, "owner'; SELECT other_account")
    management.lock_vault_account(session, 'second-owner')
    assert all(sql == 'SELECT pg_advisory_xact_lock(:key)' for sql, params in calls)
    keys = [params['key'] for sql, params in calls]
    assert all(type(key) is int and -(2**63) <= key < 2**63 for key in keys)
    assert keys[0] == keys[1] and keys[0] != keys[2]


def test_mutation_paths_take_account_fence_before_rows_and_reuse_transaction(monkeypatch):
    real_lock = management.lock_vault_account
    real_mutation = module.mutation_session
    probe_reads = []
    borrowed_sessions = []

    def capture_lock(session, user):
        if session.info.get('test_account_fenced') is not None:
            assert session.info['test_account_fenced'] == user
            borrowed_sessions.append(session)
        session.info['test_account_fenced'] = user
        real_lock(session, user)

    @contextmanager
    def inspect_transaction():
        with real_mutation() as session:
            # Observe service entry operations, not SQLAlchemy's nested calls
            # while performing the permitted unlocked callback owner probe.
            for method in ('get', 'scalar', 'scalars', 'add'):
                original = getattr(session, method)

                def fenced_call(*args, _method=method, _original=original, **kwargs):
                    if not session.info.get('test_account_fenced'):
                        assert _method == 'get' and args[0] is ProfileImportJobRow
                        assert not kwargs.get('with_for_update')
                        assert not session.info.get('test_owner_probe')
                        session.info['test_owner_probe'] = True
                        probe_reads.append(args[1])
                    if _method == 'get' and session.info.get('test_owner_probe') and kwargs.get('with_for_update'):
                        assert kwargs.get('populate_existing') is True
                    return _original(*args, **kwargs)

                monkeypatch.setattr(session, method, fenced_call)
            yield session

    monkeypatch.setattr(module, 'lock_vault_account', capture_lock)
    monkeypatch.setattr(management, 'lock_vault_account', capture_lock)
    monkeypatch.setattr(module, 'mutation_session', inspect_transaction)
    monkeypatch.setattr(management, 'mutation_session', inspect_transaction)
    job = svc.create_import('owner', {'source_fingerprint': 'same-source', 'items': [
        {'entity_type': 'TRAVELER', 'value': {'full_name': 'Owner'}, 'confidence_bps': 10000},
    ]})
    svc.review_item('owner', job['import_job_id'], job['items'][0]['import_item_id'], 'ACCEPT')
    svc.commit_import('owner', job['import_job_id'])
    svc.set_source_connection('owner', 'same-source', False)
    svc.set_source_connection('owner', 'same-source', True)
    svc.delete_source('owner', 'same-source')
    with pytest.raises(ValueError, match='PROFILE_SOURCE_DISCONNECTED'):
        svc.create_import('owner', {'source_fingerprint': 'same-source', 'items': [], 'content_hash': 'new'})
    connection = svc.create_provider_connection('owner', {
        'provider': 'CTRIP', 'method': 'FILE_UPLOAD', 'account_holder_confirmed': True,
    })
    svc.upload_provider_export('owner', connection['connection_id'], {'account_holder_confirmed': True, 'items': []})
    svc.disconnect_provider_connection('owner', connection['connection_id'])
    svc.disconnect_provider_connection('owner', connection['connection_id'], True)
    monkeypatch.setenv('GO_CTRIP_PROFILE_AUTHORIZATION_URL', 'https://accounts.ctrip.example/authorize')
    official = svc.create_provider_connection('owner', {'provider': 'CTRIP', 'account_holder_confirmed': True})
    state = parse_qs(urlparse(official['authorization_url']).query)['state'][0]
    svc.complete_provider_connection(official['connection_id'], {'state': state,
        'account_holder_verified': True, 'provider_account_subject': 'holder',
        'authorization_evidence_reference': 'adapter://isolated-only', 'items': []})
    assert probe_reads == [official['connection_id']]
    assert len(borrowed_sessions) >= 3


@pytest.mark.parametrize('change,error', [
    ({'status': 'DISCONNECTED'}, 'PROFILE_PROVIDER_STATE_ALREADY_USED'),
    ({'user_id': 'different-owner'}, 'PROFILE_PROVIDER_CONNECTION_NOT_FOUND'),
])
def test_callback_reloads_owner_and_state_after_account_fence(monkeypatch, change, error):
    monkeypatch.setenv('GO_CTRIP_PROFILE_AUTHORIZATION_URL', 'https://accounts.ctrip.example/authorize')
    connection = svc.create_provider_connection('owner', {'provider': 'CTRIP', 'account_holder_confirmed': True})
    state = parse_qs(urlparse(connection['authorization_url']).query)['state'][0]
    real_lock = management.lock_vault_account

    def change_after_probe(session, owner):
        real_lock(session, owner)
        session.execute(update(ProfileImportJobRow).where(
            ProfileImportJobRow.import_job_id == connection['connection_id']).values(**change)
            .execution_options(synchronize_session=False))

    monkeypatch.setattr(module, 'lock_vault_account', change_after_probe)
    with pytest.raises(ValueError, match=error):
        svc.complete_provider_connection(connection['connection_id'], {'state': state,
            'account_holder_verified': True, 'provider_account_subject': 'holder',
            'authorization_evidence_reference': 'adapter://isolated-only', 'items': []})


def test_concurrent_new_same_source_job_cannot_survive_completed_revocation(monkeypatch):
    svc.create_import('owner', {'source_fingerprint': 'phantom-source', 'items': []})
    deletion_ready, release_delete, creator_started = Event(), Event(), Event()
    real_audit = svc._audit

    def pause_before_commit(*args, **kwargs):
        result = real_audit(*args, **kwargs)
        if args[4] == 'PROFILE_SOURCE_DELETED':
            deletion_ready.set()
            assert release_delete.wait(5), 'test did not release deletion transaction'
        return result

    def create_again():
        creator_started.set()
        return svc.create_import('owner', {'source_fingerprint': 'phantom-source',
            'items': [], 'content_hash': 'new-content'})

    monkeypatch.setattr(svc, '_audit', pause_before_commit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        deletion = pool.submit(svc.delete_source, 'owner', 'phantom-source')
        assert deletion_ready.wait(5)
        creation = pool.submit(create_again)
        try:
            assert creator_started.wait(5)
        finally:
            release_delete.set()
        assert deletion.result(timeout=5)['status'] == 'DISCONNECTED'
        with pytest.raises(ValueError, match='PROFILE_SOURCE_DISCONNECTED'):
            creation.result(timeout=5)
    with SessionLocal() as session:
        jobs = session.scalars(select(ProfileImportJobRow).where(
            ProfileImportJobRow.user_id == 'owner',
            ProfileImportJobRow.source_fingerprint == 'phantom-source')).all()
        assert len(jobs) == 1 and jobs[0].metadata_json['values_deleted'] is True
