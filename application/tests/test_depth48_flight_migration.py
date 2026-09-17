"""Real additive upgrade and lossless rollback guard on an isolated database."""
import sqlite3
import pytest
from alembic import command
from tests.test_depth25_migration_history import config

pytestmark = pytest.mark.no_db


def test_flight_plan_upgrade_preserves_parent_and_refuses_data_loss(tmp_path, monkeypatch):
    db, cfg = config(tmp_path, monkeypatch)
    command.upgrade(cfg, '0132_rail_runtime_field_widths')
    with sqlite3.connect(db) as s:
        before = set(s.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    command.upgrade(cfg, 'head')
    with sqlite3.connect(db) as s:
        after = set(s.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        assert after - before == {('flight_change_plan',), ('flight_change_resolution',), ('go_ai_execution',),
                                  ('hosted_money_unknown_episode',), ('hosted_money_unknown_episode_audit',)}
        s.execute("INSERT INTO flight_change_plan VALUES ('quote','order','owner','{}',?,?)", ('a'*64,'2026-09-13'))
    with pytest.raises(RuntimeError, match='DATA_PRESENT'):
        command.downgrade(cfg, '0132_rail_runtime_field_widths')
    with sqlite3.connect(db) as s:
        assert s.execute('SELECT plan_hash FROM flight_change_plan').fetchone() == ('a'*64,)
        assert s.execute('SELECT version_num FROM alembic_version').fetchone() == ('0133_flight_change_plan',)
        s.execute('DELETE FROM flight_change_plan')
    command.downgrade(cfg, '0132_rail_runtime_field_widths')
    with sqlite3.connect(db) as s:
        assert set(s.execute("SELECT name FROM sqlite_master WHERE type='table'")) == before
