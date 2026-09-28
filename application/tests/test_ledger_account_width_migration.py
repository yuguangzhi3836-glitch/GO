"""Lossless ledger width upgrade, using actual PG as well when CI provides it."""
import importlib.util
import os
from pathlib import Path
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from go_hotel.db.models import OmnichannelLedgerEntryRow, OmnichannelPaymentIntentRow
from go_hotel.services.unified_money_movement import business_ledger_account_code

pytestmark = pytest.mark.no_db
URLS = ['sqlite+pysqlite:///:memory:']
PG_URL = os.environ.get('GO_TEST_DATABASE_URL', '')
if PG_URL.startswith('postgresql'):
    URLS.append(PG_URL)


@pytest.fixture(params=URLS, ids=lambda url: 'postgresql' if url.startswith('postgresql') else 'sqlite')
def connection(request):
    engine = sa.create_engine(request.param)
    with engine.begin() as conn:
        schema = 'ledger_width_' + uuid.uuid4().hex
        if conn.dialect.name == 'postgresql':
            conn.exec_driver_sql(f'CREATE SCHEMA {schema}')
            conn.exec_driver_sql(f'SET LOCAL search_path TO {schema}')
        yield conn
        if conn.dialect.name == 'postgresql':
            conn.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
    engine.dispose()


def migration(conn, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/0140_ledger_account_width.py'
    spec = importlib.util.spec_from_file_location('ledger_width_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'op', Operations(MigrationContext.configure(conn)))
    return module


def historical_table(conn, width=64, nullable=False):
    metadata = sa.MetaData()
    table = sa.Table('omnichannel_ledger_entry', metadata,
                     sa.Column('ledger_entry_id', sa.String(64), primary_key=True),
                     sa.Column('account_code', sa.String(width), nullable=nullable),
                     sa.Column('amount_minor', sa.BigInteger, nullable=False))
    sa.Index('ix_ledger_account_history', table.c.account_code)
    metadata.create_all(conn)
    conn.execute(table.insert().values(ledger_entry_id='legacy', account_code='RD:legacy-obligation', amount_minor=69800))
    return table


def test_upgrade_preserves_identity_amount_index_and_supports_maximum_account(connection, monkeypatch):
    table = historical_table(connection)
    module = migration(connection, monkeypatch)
    module.upgrade(); module.upgrade()
    assert sa.inspect(connection).get_columns(table.name)[1]['type'].length == 128
    assert connection.execute(sa.select(table)).all() == [('legacy', 'RD:legacy-obligation', 69800)]
    assert sa.inspect(connection).get_indexes(table.name)[0]['column_names'] == ['account_code']
    intent = OmnichannelPaymentIntentRow.__table__.c
    full = business_ledger_account_code('B' * intent.business_type.type.length, 'i' * intent.business_id.type.length)
    assert len(full) == 106 <= OmnichannelLedgerEntryRow.__table__.c.account_code.type.length
    connection.execute(table.insert(), [dict(ledger_entry_id='maximum', account_code=full, amount_minor=69800),
                                       dict(ledger_entry_id='different-tail', account_code=full[:-1]+'x', amount_minor=98)])
    assert connection.execute(sa.select(table.c.account_code).where(table.c.ledger_entry_id == 'maximum')).scalar_one() == full
    assert connection.execute(sa.select(sa.func.count(sa.distinct(table.c.account_code)))).scalar_one() == 3


def test_downgrade_refuses_to_truncate_hosted_account(connection, monkeypatch):
    table = historical_table(connection)
    module = migration(connection, monkeypatch); module.upgrade()
    account = business_ledger_account_code('HOSTED_HOTEL_AUTHORIZATION', 'aauth_' + 'a' * 32)
    assert len(account) == 74
    connection.execute(table.insert().values(ledger_entry_id='hosted', account_code=account, amount_minor=69800))
    with pytest.raises(RuntimeError, match='LEDGER_ACCOUNT_DOWNGRADE_DATA_PRESENT'):
        module.downgrade()
    assert sa.inspect(connection).get_columns(table.name)[1]['type'].length == 128
    assert connection.execute(sa.select(table.c.account_code).where(table.c.ledger_entry_id == 'hosted')).scalar_one() == account


def test_empty_long_account_history_can_downgrade_without_losing_legacy_index(connection, monkeypatch):
    table = historical_table(connection)
    module = migration(connection, monkeypatch); module.upgrade(); module.downgrade()
    assert sa.inspect(connection).get_columns(table.name)[1]['type'].length == 64
    assert connection.execute(sa.select(table)).all() == [('legacy', 'RD:legacy-obligation', 69800)]
    assert sa.inspect(connection).get_indexes(table.name)[0]['column_names'] == ['account_code']


@pytest.mark.parametrize('width,nullable', [(63, False), (128, True)])
def test_unexpected_schema_is_rejected_before_data_changes(connection, monkeypatch, width, nullable):
    table = historical_table(connection, width, nullable)
    with pytest.raises(RuntimeError, match='LEDGER_ACCOUNT_SCHEMA_MISMATCH'):
        migration(connection, monkeypatch).upgrade()
    assert connection.execute(sa.select(table)).all() == [('legacy', 'RD:legacy-obligation', 69800)]


def test_isolated_history_without_payment_table_is_unchanged(connection, monkeypatch):
    module = migration(connection, monkeypatch); module.upgrade(); module.downgrade()
    assert not sa.inspect(connection).has_table('omnichannel_ledger_entry')
