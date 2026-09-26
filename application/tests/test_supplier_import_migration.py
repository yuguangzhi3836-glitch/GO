import sqlite3

import pytest
from alembic import command
from alembic.config import Config

from go_hotel.core.config import settings

pytestmark = pytest.mark.no_db


def test_import_migration_roundtrip_protects_authorization_history(tmp_path, monkeypatch):
    path = tmp_path / 'supplier-import-history.db'
    url = 'sqlite+pysqlite:///' + str(path)
    monkeypatch.setattr(settings, 'database_url', url)
    cfg = Config('alembic.ini')
    cfg.set_main_option('sqlalchemy.url', url)
    command.stamp(cfg, '0137_hosted_unknown_episode')
    command.upgrade(cfg, 'head')
    with sqlite3.connect(path) as session:
        revision = session.execute('SELECT version_num FROM alembic_version').fetchone()[0]
        assert revision == '0139_hosted_publication_review' and len(revision) <= 32
        session.execute("INSERT INTO hotel_partner_import_authorization "
                        "(authorization_id, property_id, supplier_id, provider, state_hash, status, requested_by, created_at, expires_at) "
                        "VALUES ('auth-1', 'property-1', 'supplier-1', 'CTRIP', 'opaque-test-hash', 'CONSUMED', 'owner', '2026-09-18', '2026-09-19')")
    with pytest.raises(RuntimeError, match='SUPPLIER_IMPORT_DOWNGRADE_DATA_PRESENT'):
        command.downgrade(cfg, '0137_hosted_unknown_episode')
    with sqlite3.connect(path) as session:
        assert session.execute('SELECT authorization_id FROM hotel_partner_import_authorization').fetchone() == ('auth-1',)
        # Empty 0139 is rolled back; 0138 refuses losing the authorization row.
        assert session.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0138_supplier_library_import'
        session.execute('DELETE FROM hotel_partner_import_authorization')
    command.downgrade(cfg, '0137_hosted_unknown_episode')
    with sqlite3.connect(path) as session:
        assert session.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0137_hosted_unknown_episode'
        assert not session.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'hotel_partner_import_%'").fetchall()
