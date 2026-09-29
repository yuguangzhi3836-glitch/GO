"""A latest-source lookup must not hydrate the order's entire decision history."""
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import FlightOrderRow as Order, VerticalSourceDecisionRow as Decision
from go_hotel.services import vertical_source_runtime as sources
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payments

pytestmark = pytest.mark.no_db
STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)
INDEX = 'ix_vertical_source_latest'


@pytest.fixture
def history_db(monkeypatch, tmp_path):
    database = os.environ.get('GO_TEST_DATABASE_URL')
    admin = None
    schema = None
    if database:
        url = make_url(database)
        assert url.get_backend_name() == 'postgresql'
        assert url.database == 'go_c11_isolated' and url.host == '127.0.0.1'
        admin = create_engine(url)
        schema = 'source_history_' + uuid.uuid4().hex
        with admin.begin() as c:
            c.execute(text(f'CREATE SCHEMA {schema}'))
        url = url.update_query_dict({'options': '-csearch_path=' + schema})
    else:
        url = make_url('sqlite+pysqlite:///' + str(tmp_path / 'history.db'))
    engine = create_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    try:
        Order.__table__.create(engine)
        Decision.__table__.create(engine)
        monkeypatch.setattr(sources, 'SessionLocal', factory)
        with engine.begin() as c:
            c.execute(Order.__table__.insert(), dict(order_id='target', account_id='owner',
                prebook_id='synthetic', status='PAYMENT_PENDING', total_amount_minor=16800,
                currency='CNY', created_at=STAMP, updated_at=STAMP))
        yield factory, engine
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as c:
                c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()


def decision(n, vertical='FLIGHT', business_id='target', route='OFFICIAL_DIRECT'):
    identity = f'{vertical}-{business_id}-{n}'
    return dict(vertical_source_decision_id=identity, vertical=vertical, business_id=business_id,
        selected_source_id='synthetic-source', selected_source_type='AIRLINE_OFFICIAL',
        route=route, authority_reference='isolated://authority', evidence_reference='isolated://source',
        candidate_snapshot_json=[{'synthetic_history': n}], reason_codes_json=['TEST'],
        decision_hash=identity, created_at=STAMP + timedelta(seconds=n))


def seed(engine, count):
    with engine.begin() as c:
        for start in range(0, count, 1000):
            c.execute(Decision.__table__.insert(), [decision(n) for n in range(start, min(start+1000, count))])
        c.execute(Decision.__table__.insert(), [decision(count+1, business_id='foreign'),
            decision(count+2, vertical='RIDE')])


def lookup(factory, kind):
    if kind == 'latest':
        return sources.vertical_source_runtime_service.latest('FLIGHT', 'target')
    with factory() as s:
        fact, row = payments._resolve_order_fact(s, {'business_type': 'FLIGHT_ORDER', 'business_id': 'target'}, 'owner')
        assert fact['source_decision_id'] == row.vertical_source_decision_id
        return sources.out(row)


@pytest.mark.parametrize('kind', ['latest', 'payment'])
def test_large_history_hydrates_one_decision(history_db, kind, record_property):
    factory, engine = history_db
    seed(engine, 2000)
    loaded = []
    def observed(row, context):
        loaded.append(row.vertical_source_decision_id)
    event.listen(Decision, 'load', observed)
    try:
        result = lookup(factory, kind)
    finally:
        event.remove(Decision, 'load', observed)
    assert result['vertical_source_decision_id'] == 'FLIGHT-target-1999'
    record_property('history_rows', 2000)
    record_property('hydrated_decision_rows', len(loaded))
    assert loaded == ['FLIGHT-target-1999']


def test_latest_and_payment_keep_their_existing_availability_rules(history_db):
    factory, engine = history_db
    seed(engine, 10)
    with engine.begin() as c:
        c.execute(Decision.__table__.insert(), decision(20, route='UNAVAILABLE'))
    assert lookup(factory, 'latest')['route'] == 'UNAVAILABLE'
    assert lookup(factory, 'payment')['vertical_source_decision_id'] == 'FLIGHT-target-9'


def test_source_reads_are_fresh_and_do_not_commit_callers_transaction(history_db):
    factory, engine = history_db
    seed(engine, 10)
    with factory() as s:
        service = sources.vertical_source_runtime_service
        assert service.latest_in(s, 'FLIGHT', 'target')['vertical_source_decision_id'] == 'FLIGHT-target-9'
        s.execute(Decision.__table__.insert(), decision(20))
        assert service.latest_in(s, 'FLIGHT', 'target')['vertical_source_decision_id'] == 'FLIGHT-target-20'
        assert service.latest_in(s, 'FLIGHT', 'missing') is None
        s.rollback()
    assert lookup(factory, 'latest')['vertical_source_decision_id'] == 'FLIGHT-target-9'


@pytest.mark.parametrize('broken', ['missing', 'unavailable', 'missing_evidence', 'wrong_owner'])
def test_payment_source_guards_remain_fail_closed(history_db, broken):
    factory, engine = history_db
    if broken != 'missing':
        row = decision(1)
        if broken == 'unavailable': row['route'] = 'UNAVAILABLE'
        if broken == 'missing_evidence': row['evidence_reference'] = None
        with engine.begin() as c: c.execute(Decision.__table__.insert(), row)
    owner = 'foreign-owner' if broken == 'wrong_owner' else 'owner'
    expected = 'PAYMENT_PAYER_ORDER_MISMATCH' if broken == 'wrong_owner' else 'AUTHORIZED_VERTICAL_SOURCE_DECISION_REQUIRED'
    with factory() as s, pytest.raises(ValueError, match=expected):
        payments._resolve_order_fact(s, {'business_type': 'FLIGHT_ORDER', 'business_id': 'target'}, owner)


def migration_module():
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/0145_source_latest_index.py'
    spec = importlib.util.spec_from_file_location('source_latest_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


@pytest.mark.parametrize('existing_correct', [True, False])
def test_migration_checks_existing_metadata_index(history_db, existing_correct):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    factory, engine = history_db
    migration = migration_module()
    with engine.connect() as c:
        if not existing_correct:
            c.execute(text(f'DROP INDEX {INDEX}'))
            c.execute(text(f'CREATE INDEX {INDEX} ON vertical_source_decision (business_id)'))
        c.commit()
        context = MigrationContext.configure(c)
        migration.op = Operations(context)
        if existing_correct:
            with context.begin_transaction():
                migration.upgrade()
        else:
            with pytest.raises(RuntimeError, match='SOURCE_LATEST_INDEX_DEFINITION_MISMATCH'), context.begin_transaction():
                migration.upgrade()


def test_populated_postgres_migration_and_latest_query_plan(history_db, record_property):
    factory, engine = history_db
    if engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL online migration and execution plan evidence')
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    migration = migration_module()
    seed(engine, 10000)
    with engine.connect() as c:
        c.execute(text(f'DROP INDEX {INDEX}'))
        c.commit()
        context = MigrationContext.configure(c)
        migration.op = Operations(context)
        # Match env.py: introspection must belong to Alembic's transaction so
        # its autocommit block can commit before CREATE INDEX CONCURRENTLY.
        with context.begin_transaction():
            migration.upgrade()
        assert c.scalar(text('SELECT indisvalid AND indisready FROM pg_index WHERE indexrelid=to_regclass(:name)'), {'name': INDEX})
        migration.upgrade()  # A verified healthy index is reusable on retry.
        c.execute(text('ANALYZE vertical_source_decision'))
        for available_only in (False, True):
            statement = (select(Decision).where(Decision.vertical == 'FLIGHT', Decision.business_id == 'target')
                .order_by(Decision.created_at.desc()).limit(1))
            if available_only: statement = statement.where(Decision.route != 'UNAVAILABLE')
            plan = c.execute(text('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' +
                str(statement.compile(engine, compile_kwargs={'literal_binds': True})))).scalar_one()[0]['Plan']
            assert plan['Node Type'] == 'Limit' and plan['Actual Rows'] == 1
            scan = plan['Plans'][0]
            assert scan['Node Type'] == 'Index Scan' and scan['Index Name'] == INDEX
            assert scan['Scan Direction'] == 'Backward' and scan['Actual Rows'] == 1
            record_property('available_only_' + str(available_only), str(plan))
        c.commit()
        migration.downgrade()
        assert c.scalar(text('SELECT to_regclass(:name)'), {'name': INDEX}) is None
        assert c.scalar(text('SELECT count(*) FROM vertical_source_decision')) == 10002
        c.rollback()
