import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import select, update
from go_hotel.autonomy.operations import application_executor
from go_hotel.db.models import AutonomyTaskRow, IdentityUserRow, OutboxRow
from go_hotel.db.session import SessionLocal
from go_hotel.security.service import identity_service


PREFIX = '/internal/v1/autonomy'


def login(client, username='go_admin', password='change-me-admin'):
    reply = client.post('/v1/auth/login', json={'username': username, 'password': password})
    assert reply.status_code == 200, reply.text
    client.cookies.clear()
    return {'Authorization': 'Bearer ' + reply.json()['data']['access_token']}


def test_all14_observations_execute_against_application_database(client):
    headers = login(client)
    response = client.get(PREFIX + '/cells', headers=headers)
    assert response.status_code == 200 and 'no-store' in response.headers['Cache-Control']
    assert len(response.json()['data']) == 14
    cells = ['C%02d' % n for n in range(1, 15)]
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as s:
        s.add(OutboxRow(event_id='depth08-failed-delivery', event_type='TEST', aggregate_id='test',
            payload={'private': 'must-not-appear'}, status='DEAD', attempt_count=5,
            available_at=now, created_at=now))
    body = {'idempotency_key': 'operator-cycle-1', 'cell_ids': cells}
    queued = client.post(PREFIX + '/observe', json=body, headers=headers)
    assert queued.status_code == 200, queued.text
    original_ids = {r['task_id'] for r in queued.json()['data']}
    runtime = application_executor()
    for _ in cells:
        result = runtime.run_once('integration-worker')
        assert result['status'] == 'SUCCEEDED', result
        assert result['next_step'] == 2
        assert result['result_json']['production_certification'] is False
    assert runtime.run_once('idle') is None
    replay = client.post(PREFIX + '/observe', json=body, headers=headers).json()['data']
    assert {r['task_id'] for r in replay} == original_ids
    assert all(r['status'] == 'SUCCEEDED' for r in replay)
    c12 = next(r for r in replay if r['cell_id'] == 'C12')
    assert c12['result_json']['attention'] == [{'source': 'transactional_outbox', 'state': 'DEAD', 'count': 1}]
    assert 'must-not-appear' not in json.dumps(replay)
    detail = client.get(PREFIX + '/tasks/' + c12['task_id'], headers=headers).json()['data']
    assert len(detail['checkpoints']) == 2 and len(detail['events']) > 3
    assert 'lease_token' not in detail


@pytest.mark.parametrize('identity', ['anonymous', 'supplier', 'read_only'])
def test_queue_mutation_requires_go_admin_rules_permission(client, identity):
    if identity == 'anonymous':
        headers, code = {}, 401
    elif identity == 'supplier':
        headers, code = login(client, 'supplier_owner', 'change-me-supplier'), 403
    else:
        identity_service.ensure_user('reader-depth08', 'StrongReader123!', 'GO_ADMIN', None, ['GO_READ_ONLY'])
        headers, code = login(client, 'reader-depth08', 'StrongReader123!'), 403
        assert client.get(PREFIX + '/cells', headers=headers).status_code == 200
    reply = client.post(PREFIX + '/observe', json={'idempotency_key': 'reject', 'cell_ids': ['C01']}, headers=headers)
    assert reply.status_code == code
    with SessionLocal() as s:
        assert s.scalar(select(AutonomyTaskRow.task_id)) is None


@pytest.mark.parametrize('change', [
    {'cell_ids': ['C01', 'C01']}, {'cell_ids': ['C99']}, {'capability': 'REFUND'},
    {'environment': 'PRODUCTION'}, {'require_autonomous_execution': False}, {'payload': {'shell': 'do-something'}},
])
def test_api_rejects_client_supplied_execution_authority(client, change):
    headers = login(client)
    reply = client.post(PREFIX + '/observe', headers=headers,
                         json={'idempotency_key': 'reject', 'cell_ids': ['C01'], **change})
    assert reply.status_code == 422


def test_queued_observation_holds_if_admin_role_is_revoked(client):
    headers = login(client)
    queued = client.post(PREFIX + '/observe', headers=headers,
        json={'idempotency_key': 'revoked', 'cell_ids': ['C01']}).json()['data'][0]
    with SessionLocal.begin() as s:
        s.execute(update(IdentityUserRow).where(IdentityUserRow.username == 'go_admin').values(roles=['GO_READ_ONLY']))
    runtime = application_executor()
    assert runtime.run_once('a')['last_code'] == 'SUBMITTER_AUTHORITY_REVOKED'
    assert runtime.inspect(queued['task_id'])['checkpoints'] == []


def test_api_pause_resume_cancel_and_revision_conflict(client):
    headers = login(client)
    control = PREFIX + '/cells/C01/control'
    assert client.post(control, headers=headers, json={'paused': True, 'expected_version': 1}).status_code == 200
    assert client.post(control, headers=headers, json={'paused': False, 'expected_version': 1}).status_code == 409
    task = client.post(PREFIX + '/observe', headers=headers,
        json={'idempotency_key': 'held', 'cell_ids': ['C01']}).json()['data'][0]
    assert task['status'] == 'HOLD'
    assert client.post(control, headers=headers, json={'paused': False, 'expected_version': 2}).status_code == 200
    route = PREFIX + '/tasks/' + task['task_id']
    assert client.post(route + '/resume', headers=headers).json()['data']['status'] == 'QUEUED'
    assert client.post(route + '/cancel', headers=headers).json()['data']['status'] == 'CANCELLED'
    assert application_executor().run_once('idle') is None


def test_worker_cli_process_consumes_persisted_queue(client):
    headers = login(client)
    task = client.post(PREFIX + '/observe', headers=headers,
        json={'idempotency_key': 'subprocess', 'cell_ids': ['C12']}).json()['data'][0]
    from go_hotel.db.session import engine
    # Legacy test modules overwrite DATABASE_URL during collection. Bind the
    # child to this fixture's actual engine, not the process-wide last writer.
    env = {**os.environ, 'PYTHONPATH': 'src', 'APP_ENV': 'local',
           'DATABASE_URL': engine.url.render_as_string(hide_password=False)}
    worker = subprocess.run([sys.executable, '-m', 'go_hotel.workers.autonomy_worker', '--once'],
                             env=env, capture_output=True, text=True, timeout=30)
    assert worker.returncode == 0, worker.stderr
    result = json.loads(worker.stdout)
    assert result['task_id'] == task['task_id'] and result['status'] == 'SUCCEEDED'
    again = subprocess.run([sys.executable, '-m', 'go_hotel.workers.autonomy_worker', '--once'],
                            env=env, capture_output=True, text=True, timeout=30)
    assert again.returncode == 0 and not again.stdout.strip()


@pytest.mark.no_db
def test_migration_roundtrip_preserves_prior_data_and_protects_execution_evidence(tmp_path):
    from alembic import command
    from alembic.config import Config
    from go_hotel.core.config import settings
    from sqlalchemy import create_engine, inspect
    db = tmp_path / 'migration.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE retained_business_data (id text PRIMARY KEY, state text)')
        conn.execute("INSERT INTO retained_business_data VALUES ('existing','REFUNDED')")
    config = Config('alembic.ini')
    original = settings.database_url
    settings.database_url = 'sqlite+pysqlite:///' + str(db)
    try:
        command.stamp(config, '0123_catalog_credit_exclusion')
        command.upgrade(config, '0124_autonomy_durable')
        engine = create_engine(settings.database_url)
        inspector = inspect(engine)
        names = {'autonomy_task', 'autonomy_step', 'autonomy_event', 'autonomy_cell_control', 'autonomy_qualification'}
        assert names <= set(inspector.get_table_names())
        assert {r['name'] for r in inspector.get_indexes('autonomy_task')} == {'ix_autonomy_task_queue', 'ix_autonomy_task_cell'}
        assert {c['name'] for c in inspector.get_unique_constraints('autonomy_event')} == {'uq_autonomy_event_sequence'}
        command.downgrade(config, '0123_catalog_credit_exclusion')
        command.upgrade(config, '0124_autonomy_durable')
        with sqlite3.connect(db) as conn:
            assert conn.execute('SELECT * FROM retained_business_data').fetchone() == ('existing', 'REFUNDED')
            conn.execute("INSERT INTO autonomy_cell_control VALUES ('TEST','C01',1,2,'operator',0)")
        with pytest.raises(RuntimeError, match='AUTONOMY_DATA_PRESENT'):
            command.downgrade(config, '0123_catalog_credit_exclusion')
        with sqlite3.connect(db) as conn:
            assert conn.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0124_autonomy_durable'
            assert conn.execute('SELECT count(*) FROM autonomy_cell_control').fetchone()[0] == 1
        engine.dispose()
    finally:
        settings.database_url = original
