"""A delayed completion/release must not mutate a replacement claim or receipt."""
import os
import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import IdempotencyRow
from go_hotel.domain.models import now_utc
from go_hotel.repositories import sql

pytestmark = pytest.mark.no_db


@pytest.fixture
def isolated_claims(monkeypatch, tmp_path):
    database = os.environ.get('GO_TEST_DATABASE_URL')
    admin = None
    schema = None
    if database:
        url = make_url(database)
        assert url.get_backend_name() == 'postgresql'
        assert url.database == 'go_c11_isolated' and url.host == '127.0.0.1'
        admin = create_engine(url)
        schema = 'claim_race_' + uuid.uuid4().hex
        with admin.begin() as c:
            c.execute(text(f'CREATE SCHEMA {schema}'))
        url = url.update_query_dict({'options': '-csearch_path=' + schema})
    else:
        url = make_url('sqlite+pysqlite:///' + str(tmp_path / 'claims.db'))
    engine = create_engine(url)
    competitor = create_engine(url)
    IdempotencyRow.__table__.create(engine)
    monkeypatch.setattr(sql, 'SessionLocal', sessionmaker(bind=engine))
    try:
        yield sql.SqlRepository(), engine, competitor
    finally:
        engine.dispose()
        competitor.dispose()
        if admin is not None:
            with admin.begin() as c:
                c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()


def intervene_before_mutation(engine, kind, action):
    """Commit a competing change just before the delayed caller's final DML."""
    fired = []

    def before(conn, cursor, statement, parameters, context, executemany):
        compiled = getattr(context, 'compiled', None)
        command = getattr(compiled, 'statement', None)
        if (not fired and getattr(command, 'is_' + kind, False)
                and command.table.name == IdempotencyRow.__tablename__):
            fired.append(True)
            action()

    event.listen(engine, 'before_cursor_execute', before)
    return before, fired


def test_delayed_completion_cannot_overwrite_replacement_claim(isolated_claims):
    repo, engine, competitor = isolated_claims
    original = {'amount_minor': 100}
    replacement = {'amount_minor': 200}
    assert repo.claim_idempotency('RIDE_CREATE_ORDER', 'same-key', original)[0] == 'CLAIMED'
    table = IdempotencyRow.__table__

    def replace_claim():
        with competitor.begin() as c:
            c.execute(table.delete().where(table.c.operation == 'RIDE_CREATE_ORDER', table.c.idempotency_key == 'same-key'))
            c.execute(table.insert().values(operation='RIDE_CREATE_ORDER', idempotency_key='same-key',
                request_hash=repo.hash_payload(replacement), response_code=102,
                response_body={'status': 'IN_PROGRESS'}, resource_id=None, created_at=now_utc()))

    listener, fired = intervene_before_mutation(engine, 'update', replace_claim)
    try:
        with pytest.raises(ValueError, match='IDEMPOTENCY_CLAIM_LOST'):
            repo.complete_idempotency('RIDE_CREATE_ORDER', 'same-key', original, {'order_id': 'old-order'})
    finally:
        event.remove(engine, 'before_cursor_execute', listener)
    assert fired
    current = repo.get_idempotency('RIDE_CREATE_ORDER', 'same-key')
    assert current['request_hash'] == repo.hash_payload(replacement)
    assert current['response_code'] == 102 and current['response'] == {'status': 'IN_PROGRESS'}


def test_delayed_release_cannot_delete_completed_receipt(isolated_claims):
    repo, engine, competitor = isolated_claims
    body = {'amount_minor': 100}
    assert repo.claim_idempotency('RIDE_CREATE_ORDER', 'same-key', body)[0] == 'CLAIMED'
    table = IdempotencyRow.__table__

    def complete_receipt():
        with competitor.begin() as c:
            c.execute(table.update().where(table.c.operation == 'RIDE_CREATE_ORDER', table.c.idempotency_key == 'same-key')
                .values(response_code=200, response_body={'order_id': 'confirmed-order'}, resource_id='confirmed-order'))

    listener, fired = intervene_before_mutation(engine, 'delete', complete_receipt)
    try:
        repo.release_idempotency_claim('RIDE_CREATE_ORDER', 'same-key', body)
    finally:
        event.remove(engine, 'before_cursor_execute', listener)
    assert fired
    state, record = repo.claim_idempotency('RIDE_CREATE_ORDER', 'same-key', body)
    assert state == 'REPLAY' and record['response'] == {'order_id': 'confirmed-order'}


def test_completion_and_release_keep_existing_claim_contract(isolated_claims):
    repo, _, _ = isolated_claims
    body = {'amount_minor': 100}
    with pytest.raises(ValueError, match='IDEMPOTENCY_CLAIM_LOST'):
        repo.complete_idempotency('RIDE_CREATE_ORDER', 'missing', body, {})
    repo.release_idempotency_claim('RIDE_CREATE_ORDER', 'missing', body)
    assert repo.claim_idempotency('RIDE_CREATE_ORDER', 'same-key', body)[0] == 'CLAIMED'
    with pytest.raises(ValueError, match='IDEMPOTENCY_CLAIM_LOST'):
        repo.complete_idempotency('RIDE_CREATE_ORDER', 'same-key', {'amount_minor': 200}, {})
    repo.release_idempotency_claim('RIDE_CREATE_ORDER', 'same-key', {'amount_minor': 200})
    assert repo.get_idempotency('RIDE_CREATE_ORDER', 'same-key')['response_code'] == 102
    result = {'order_id': 'order-1'}
    assert repo.complete_idempotency('RIDE_CREATE_ORDER', 'same-key', body, result, 'order-1') == result
    repo.release_idempotency_claim('RIDE_CREATE_ORDER', 'same-key', body)
    assert repo.get_idempotency('RIDE_CREATE_ORDER', 'same-key')['response'] == result
    # Explicit reconciliation can still replace a receipt for the same payload.
    reconciled = {'order_id': 'order-1', 'reconciled': True}
    repo.complete_idempotency('RIDE_CREATE_ORDER', 'same-key', body, reconciled, 'order-1')
    assert repo.get_idempotency('RIDE_CREATE_ORDER', 'same-key')['response'] == reconciled
    assert repo.claim_idempotency('RIDE_CREATE_ORDER', 'releasable', body)[0] == 'CLAIMED'
    repo.release_idempotency_claim('RIDE_CREATE_ORDER', 'releasable', body)
    assert repo.get_idempotency('RIDE_CREATE_ORDER', 'releasable') is None
