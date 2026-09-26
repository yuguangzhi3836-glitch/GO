"""Fresh installation and real historical upgrade boundaries, with no live DB."""
import sqlite3
import pytest
from alembic import command
from alembic.config import Config
from go_hotel.core.config import settings

pytestmark = pytest.mark.no_db


def config(tmp_path, monkeypatch):
    db = tmp_path / 'history.db'
    url = 'sqlite+pysqlite:///' + str(db)
    monkeypatch.setattr(settings, 'database_url', url)
    cfg = Config('alembic.ini'); cfg.set_main_option('sqlalchemy.url', url)
    return db, cfg


def test_fresh_database_can_apply_entire_chain_without_stamp(tmp_path, monkeypatch):
    db, cfg = config(tmp_path, monkeypatch)
    command.upgrade(cfg, 'head')
    with sqlite3.connect(db) as s:
        assert s.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0139_hosted_publication_review'
        media_columns={r[1] for r in s.execute('PRAGMA table_info(hosted_media_asset)')}
        assert {'submitted_by','submitter_binding_hash'} <= media_columns
        assert s.execute("SELECT name FROM sqlite_master WHERE name='hosted_publication_review'").fetchone()
        columns = {r[1] for r in s.execute('PRAGMA table_info(connector_runtime_reconciliation)')}
        assert {'claimed_by', 'lease_expires_at', 'resolution_payload_json', 'superseded_reason'} <= columns
        assert s.execute("SELECT name FROM sqlite_master WHERE name='vertical_payment_deadline'").fetchone()


def test_0076_contains_only_its_historical_columns_and_constraints(tmp_path, monkeypatch):
    db, cfg = config(tmp_path, monkeypatch)
    command.stamp(cfg, '0075_442bc0d513d1')
    command.upgrade(cfg, '0076_126e14322d21')
    with sqlite3.connect(db) as s:
        columns = {r[1] for r in s.execute('PRAGMA table_info(connector_runtime_reconciliation)')}
        assert columns == {'reconciliation_id', 'runtime_operation_id', 'state', 'attempt_count',
            'max_attempts', 'next_attempt_at', 'manual_review_reason', 'updated_at'}
        values = ('r1', 'op1', 'PENDING', 1, 8, None, 'retain-history', '2026-09-09')
        s.execute('INSERT INTO connector_runtime_reconciliation VALUES (?,?,?,?,?,?,?,?)', values)
        with pytest.raises(sqlite3.IntegrityError):
            s.execute('INSERT INTO connector_runtime_reconciliation VALUES (?,?,?,?,?,?,?,?)', ('r2', *values[1:]))
    # Isolate the real0113/0114 additive upgrade boundary over an as-of0076 row.
    command.stamp(cfg, '0112_ti_p0_20260829')
    command.upgrade(cfg, '0114_ext_truth_incident_hard')
    with sqlite3.connect(db) as s:
        assert s.execute('SELECT runtime_operation_id,attempt_count,manual_review_reason,escalation_level FROM connector_runtime_reconciliation').fetchone() == ('op1', 1, 'retain-history', 0)
        assert s.execute('SELECT claimed_by,resolution_payload_json FROM connector_runtime_reconciliation').fetchone() == (None, None)
    command.downgrade(cfg, '0112_ti_p0_20260829')
    with sqlite3.connect(db) as s:
        assert {r[1] for r in s.execute('PRAGMA table_info(connector_runtime_reconciliation)')} == columns
        assert s.execute('SELECT reconciliation_id,manual_review_reason FROM connector_runtime_reconciliation').fetchone() == ('r1', 'retain-history')


def test_migration_does_not_depend_on_current_business_metadata(tmp_path, monkeypatch):
    import sqlalchemy as sa
    from go_hotel.db.models import Base
    db, cfg = config(tmp_path, monkeypatch)
    monkeypatch.setattr(Base, 'metadata', sa.MetaData())
    command.stamp(cfg, '0075_442bc0d513d1')
    command.upgrade(cfg, '0076_126e14322d21')
    with sqlite3.connect(db) as s:
        created = {r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'connector_runtime_authorization', 'connector_runtime_operation', 'connector_webhook_receipt',
            'connector_runtime_observation', 'connector_runtime_reconciliation', 'connector_runtime_safety_event'} <= created


def test_rail_response_timestamps_survive_database_timezone_roundtrip():
    from datetime import datetime, UTC, timezone, timedelta
    from go_hotel.db.models import RailOrderRow
    from go_hotel.rail.service import rail_service
    instant=datetime(2026,9,9,3,0,0,123456)
    order=RailOrderRow(order_id='time-order',account_id='owner',status='PAYMENT_PENDING',
        total_amount_minor=100,currency='CNY',passengers=[],current_journey={},
        created_at=instant,updated_at=instant)
    before=rail_service._order(order)
    order.created_at=instant.replace(tzinfo=UTC)
    order.updated_at=instant.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
    assert rail_service._order(order)==before
    assert before['created_at']==before['updated_at']=='2026-09-09T03:00:00.123456+00:00'


def test_rail_width_upgrade_preserves_history_and_refuses_lossy_downgrade(tmp_path, monkeypatch):
    db, cfg = config(tmp_path, monkeypatch)
    with sqlite3.connect(db) as s:
        s.execute('CREATE TABLE rail_order_runtime (order_id VARCHAR(64) PRIMARY KEY, '
                  'status VARCHAR(32) NOT NULL, booking_reference VARCHAR(24))')
        s.execute('CREATE INDEX rail_ref_index ON rail_order_runtime(booking_reference)')
        s.execute("INSERT INTO rail_order_runtime VALUES ('old','TICKETED','old-reference')")
    command.stamp(cfg, '0131_vertical_payment_deadline')
    command.upgrade(cfg, 'head')
    state = 'PAYMENT_CONFIRMED_AWAITING_SUPPLIER'
    reference = 'provider-' + 'r' * 110
    with sqlite3.connect(db) as s:
        assert s.execute('SELECT status,booking_reference FROM rail_order_runtime').fetchone() == ('TICKETED','old-reference')
        columns = {r[1]: r[2] for r in s.execute('PRAGMA table_info(rail_order_runtime)')}
        assert columns['status']=='VARCHAR(64)' and columns['booking_reference']=='VARCHAR(128)'
        s.execute('INSERT INTO rail_order_runtime VALUES (?,?,?)', ('long',state,reference))
    with pytest.raises(RuntimeError, match='RAIL_RUNTIME_DOWNGRADE_WOULD_TRUNCATE_HISTORY'):
        command.downgrade(cfg, '0131_vertical_payment_deadline')
    with sqlite3.connect(db) as s:
        assert s.execute("SELECT status,booking_reference FROM rail_order_runtime WHERE order_id='long'").fetchone() == (state,reference)
        assert s.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0132_rail_runtime_field_widths'
        s.execute("DELETE FROM rail_order_runtime WHERE order_id='long'")
    command.downgrade(cfg, '0131_vertical_payment_deadline')
    with sqlite3.connect(db) as s:
        assert s.execute('SELECT status,booking_reference FROM rail_order_runtime').fetchone() == ('TICKETED','old-reference')
        assert s.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='rail_ref_index'").fetchone()
        columns = {r[1]: r[2] for r in s.execute('PRAGMA table_info(rail_order_runtime)')}
        assert columns['status']=='VARCHAR(32)' and columns['booking_reference']=='VARCHAR(24)'


def test_flight_width_absent_sqlite_table_is_not_fabricated(tmp_path, monkeypatch):
    db, cfg = config(tmp_path, monkeypatch)
    command.stamp(cfg, '0133_flight_change_plan')
    command.upgrade(cfg, '0134_flight_status_width')
    with sqlite3.connect(db) as s:
        assert s.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0134_flight_status_width'
        assert not s.execute("SELECT name FROM sqlite_master WHERE name='flight_order_runtime'").fetchone()
    command.downgrade(cfg, '0133_flight_change_plan')
    with sqlite3.connect(db) as s:
        assert s.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0133_flight_change_plan'
        assert not s.execute("SELECT name FROM sqlite_master WHERE name='flight_order_runtime'").fetchone()


def test_flight_width_preserves_sqlite_history_and_blocks_lossy_downgrade(tmp_path, monkeypatch):
    db, cfg = config(tmp_path, monkeypatch)
    with sqlite3.connect(db) as s:
        s.execute('CREATE TABLE flight_order_runtime (order_id VARCHAR(64) PRIMARY KEY, status VARCHAR(32) NOT NULL)')
        s.execute('CREATE INDEX flight_status_history_index ON flight_order_runtime(status)')
        s.execute("INSERT INTO flight_order_runtime VALUES ('old','PAYMENT_PENDING')")
    command.stamp(cfg, '0133_flight_change_plan')
    command.upgrade(cfg, '0134_flight_status_width')
    state = 'PAYMENT_CONFIRMED_AWAITING_SUPPLIER'
    with sqlite3.connect(db) as s:
        assert s.execute('SELECT * FROM flight_order_runtime').fetchone() == ('old', 'PAYMENT_PENDING')
        assert {r[1]: r[2] for r in s.execute('PRAGMA table_info(flight_order_runtime)')}['status'] == 'VARCHAR(64)'
        assert s.execute("SELECT name FROM sqlite_master WHERE name='flight_status_history_index'").fetchone()
        s.execute('UPDATE flight_order_runtime SET status=?', (state,))
    with pytest.raises(RuntimeError, match='FLIGHT_STATUS_DOWNGRADE_WOULD_TRUNCATE_HISTORY'):
        command.downgrade(cfg, '0133_flight_change_plan')
    with sqlite3.connect(db) as s:
        assert s.execute('SELECT status FROM flight_order_runtime').fetchone() == (state,)
        assert s.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0134_flight_status_width'
        s.execute("UPDATE flight_order_runtime SET status='PAYMENT_PENDING'")
    command.downgrade(cfg, '0133_flight_change_plan')
    with sqlite3.connect(db) as s:
        assert s.execute('SELECT * FROM flight_order_runtime').fetchone() == ('old', 'PAYMENT_PENDING')
        assert {r[1]: r[2] for r in s.execute('PRAGMA table_info(flight_order_runtime)')}['status'] == 'VARCHAR(32)'
        assert s.execute("SELECT name FROM sqlite_master WHERE name='flight_status_history_index'").fetchone()


def hosted_publication_migration():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'alembic/versions/0139_hosted_publication_review.py'
    spec=importlib.util.spec_from_file_location('hosted_publication_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('media_present',[False,True])
def test_hosted_publication_migration_preserves_legacy_media_and_absent_table(tmp_path,media_present):
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine=sa.create_engine('sqlite+pysqlite:///'+str(tmp_path/'publication.db'))
    migration=hosted_publication_migration()
    with engine.begin() as connection:
        if media_present:
            connection.execute(sa.text('CREATE TABLE hosted_media_asset (media_asset_id VARCHAR(64) PRIMARY KEY)'))
            connection.execute(sa.text("INSERT INTO hosted_media_asset VALUES ('historical-unverified')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert sa.inspect(connection).has_table('hosted_media_asset')==media_present
            if media_present:
                assert connection.execute(sa.text('SELECT media_asset_id,submitted_by,submitter_binding_hash FROM hosted_media_asset')).one()==('historical-unverified',None,None)
            migration.downgrade()
        assert not sa.inspect(connection).has_table('hosted_publication_review')
        if media_present:assert connection.execute(sa.text('SELECT * FROM hosted_media_asset')).one()==('historical-unverified',)
    engine.dispose()


@pytest.mark.parametrize('evidence',['media','review'])
def test_hosted_publication_downgrade_refuses_losing_authority_history(tmp_path,evidence):
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine=sa.create_engine('sqlite+pysqlite:///'+str(tmp_path/'publication-history.db'))
    migration=hosted_publication_migration()
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE hosted_media_asset (media_asset_id VARCHAR(64) PRIMARY KEY)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            if evidence=='media':connection.execute(sa.text("INSERT INTO hosted_media_asset VALUES ('original','server-submitter','authority-hash')"))
            else:
                connection.execute(sa.text("INSERT INTO hosted_publication_review VALUES ('review','hotel','{}','hash','checker','binding','APPROVE','isolated://proof','2026-09-26')"))
            with pytest.raises(RuntimeError,match='DOWNGRADE_DATA_PRESENT'):migration.downgrade()
        assert {'submitted_by','submitter_binding_hash'}<={c['name'] for c in sa.inspect(connection).get_columns('hosted_media_asset')}
        assert sa.inspect(connection).has_table('hosted_publication_review')
    engine.dispose()


@pytest.mark.parametrize('existing',['metadata','wrong_column'])
def test_hosted_publication_migration_validates_existing_metadata_schema(tmp_path,existing):
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from go_hotel.db.models import HostedMediaAssetRow,HostedPublicationReviewRow
    engine=sa.create_engine('sqlite+pysqlite:///'+str(tmp_path/'metadata.db'))
    with engine.begin() as connection:
        if existing=='metadata':
            HostedMediaAssetRow.__table__.create(connection)
            HostedPublicationReviewRow.__table__.create(connection)
        else:
            connection.execute(sa.text('CREATE TABLE hosted_media_asset (media_asset_id VARCHAR(64) PRIMARY KEY, submitted_by INTEGER)'))
        with Operations.context(MigrationContext.configure(connection)):
            if existing=='metadata':hosted_publication_migration().upgrade()
            else:
                with pytest.raises(RuntimeError,match='SCHEMA_MISMATCH'):hosted_publication_migration().upgrade()
    engine.dispose()


@pytest.mark.parametrize('timezone',[True,False])
def test_hosted_publication_postgres_schema_requires_timezone_type(timezone):
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import TIMESTAMP
    actual={'type':TIMESTAMP(timezone=timezone),'nullable':False}
    expected=sa.Column('decided_at',sa.DateTime(timezone=True),nullable=False)
    if timezone:hosted_publication_migration().compatible(actual,expected,'postgresql')
    else:
        with pytest.raises(RuntimeError,match='SCHEMA_MISMATCH'):hosted_publication_migration().compatible(actual,expected,'postgresql')
