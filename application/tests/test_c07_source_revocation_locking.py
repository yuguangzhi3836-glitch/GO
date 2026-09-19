"""Deterministic read-committed interleavings; not PostgreSQL runtime evidence."""
from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from go_hotel.db.models import ProfileFactRow, ProfileImportItemRow, ProfileImportJobRow
from go_hotel.db.session import SessionLocal
from go_hotel.services import personal_travel_vault as module

svc = module.personal_travel_vault_service
USER = 'c07-source-owner'


def pending_import(fingerprint='source-race'):
    job = svc.create_import(USER, {
        'source_type': 'MANUAL', 'source_fingerprint': fingerprint,
        'items': [
            {'entity_type': 'TRAVELER', 'traveler_ref': 'me',
             'value': {'full_name': 'Delete Test', 'relationship_type': 'SELF'}, 'confidence_bps': 10000},
            {'field_type': 'PASSPORT_NUMBER', 'traveler_ref': 'me',
             'value': 'TEST123456', 'confidence_bps': 10000},
        ],
    })
    for item in job['items']:
        svc.review_item(USER, job['import_job_id'], item['import_item_id'], 'ACCEPT')
    return job


def test_commit_just_before_source_lock_is_included_in_deletion(monkeypatch):
    job = pending_import()
    original = module.mutation_session
    nested = False
    queries = []

    @contextmanager
    def read_committed_interleaving():
        nonlocal nested
        if nested:
            with original() as session:
                yield session
            return
        # SQLite BEGIN IMMEDIATE would serialize the test before the vulnerable
        # read. Omit it only in this injection harness to model READ COMMITTED.
        with SessionLocal() as session:
            real_scalars = session.scalars

            def before_source_jobs(statement, *args, **kwargs):
                nonlocal nested
                entities = [item.get('entity') for item in statement.column_descriptions]
                if ProfileImportJobRow in entities:
                    queries.append(str(statement.compile(dialect=postgresql.dialect())))
                    if not nested:
                        nested = True
                        svc.commit_import(USER, job['import_job_id'])
                return real_scalars(statement, *args, **kwargs)

            monkeypatch.setattr(session, 'scalars', before_source_jobs)
            yield session
            session.commit()

    monkeypatch.setattr(module, 'mutation_session', read_committed_interleaving)
    result = svc.delete_source(USER, job['source_fingerprint'])
    assert result['deleted_facts'] == 1
    assert 'ORDER BY profile_import_job.import_job_id FOR UPDATE' in queries[0]
    with SessionLocal() as session:
        facts = session.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id == USER)).all()
        assert len(facts) == 1 and facts[0].status == 'DELETED'
        items = session.scalars(select(ProfileImportItemRow).where(
            ProfileImportItemRow.import_job_id == job['import_job_id'])).all()
        assert all(item.candidate_value_ciphertext is None for item in items)


def test_source_delete_locks_all_jobs_in_order_before_reading_facts(monkeypatch):
    first = pending_import()
    second = svc.create_import(USER, {
        'source_type': 'MANUAL', 'source_fingerprint': first['source_fingerprint'],
        'items': [], 'content_hash': 'second-content',
    })
    statements = []
    original = module.mutation_session

    @contextmanager
    def observe_queries():
        with original() as session:
            real_scalars = session.scalars

            def observe(statement, *args, **kwargs):
                statements.append(str(statement.compile(dialect=postgresql.dialect())))
                return real_scalars(statement, *args, **kwargs)

            monkeypatch.setattr(session, 'scalars', observe)
            yield session

    monkeypatch.setattr(module, 'mutation_session', observe_queries)
    svc.delete_source(USER, first['source_fingerprint'])
    assert 'FROM profile_import_job' in statements[0]
    assert 'ORDER BY profile_import_job.import_job_id FOR UPDATE' in statements[0]
    assert 'FROM profile_fact' in statements[1]
    for job in (first, second):
        with pytest.raises(ValueError, match='PROFILE_SOURCE_DISCONNECTED'):
            svc.commit_import(USER, job['import_job_id'])


def test_provider_delete_defers_import_job_lock_until_ordered_source_lock(monkeypatch):
    connection = svc.create_provider_connection(USER, {
        'provider': 'CTRIP', 'method': 'FILE_UPLOAD', 'account_holder_confirmed': True,
    })
    preview = svc.upload_provider_export(USER, connection['connection_id'], {
        'account_holder_confirmed': True, 'items': [],
    })['preview']
    operations = []
    original = module.mutation_session

    @contextmanager
    def observe_locks():
        with original() as session:
            real_get, real_scalars = session.get, session.scalars

            def observe_get(entity, ident, *args, **kwargs):
                if entity is ProfileImportJobRow:
                    operations.append(('get', ident, kwargs.get('with_for_update', False)))
                return real_get(entity, ident, *args, **kwargs)

            def observe_scalars(statement, *args, **kwargs):
                operations.append(('select', str(statement.compile(dialect=postgresql.dialect()))))
                return real_scalars(statement, *args, **kwargs)

            monkeypatch.setattr(session, 'get', observe_get)
            monkeypatch.setattr(session, 'scalars', observe_scalars)
            yield session

    monkeypatch.setattr(module, 'mutation_session', observe_locks)
    assert svc.disconnect_provider_connection(USER, connection['connection_id'], True)['status'] == 'DELETED'
    assert operations[0] == ('get', connection['connection_id'], True)
    assert ('get', preview['import_job_id'], True) not in operations
    locks = [op[1] for op in operations if op[0] == 'select' and 'FOR UPDATE' in op[1]]
    assert len(locks) == 1 and 'ORDER BY profile_import_job.import_job_id FOR UPDATE' in locks[0]
