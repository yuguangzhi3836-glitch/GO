import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from test_correctness import baseline, db


def test_index_upgrade_downgrade_preserves_duplicate_sources(db):
    path = Path(__file__).resolve().parents[2] / 'application/alembic/versions/0135_credit_source_intent_index.py'
    spec = importlib.util.spec_from_file_location('source_index_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    name = 'ix_catalog_credit_source_payment_intent_id'
    with db.engine.begin() as c:
        c.execute(text('DROP INDEX IF EXISTS ' + name))
        c.execute(text("INSERT INTO catalog_credit_source VALUES ('a','credit','same',100,0,0), ('b','credit','same',100,0,0)"))
        with Operations.context(MigrationContext.configure(c)):
            migration.upgrade()
            index = next(i for i in inspect(c).get_indexes('catalog_credit_source') if i['name'] == name)
            assert index['column_names'] == ['payment_intent_id'] and not index['unique']
            migration.downgrade()
            assert name not in {i['name'] for i in inspect(c).get_indexes('catalog_credit_source')}
            migration.upgrade()
        assert c.scalar(text('SELECT count(*) FROM catalog_credit_source')) == 2
