import importlib.util
from pathlib import Path
import pytest
from sqlalchemy import create_engine,inspect,text
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_verification_migration_and_nonempty_downgrade_guard(tmp_path):
    path=Path(__file__).resolve().parents[1]/'alembic/versions/0142_registration_verification.py'
    spec=importlib.util.spec_from_file_location('registration_migration',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    engine=create_engine('sqlite:///'+str(tmp_path/'migration.db'))
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            m.upgrade()
            assert set(inspect(connection).get_table_names())=={'registration_challenge','registration_rate'}
            connection.execute(text("INSERT INTO registration_rate VALUES ('test',1,999999)"))
            with pytest.raises(RuntimeError,match='DATA_PRESENT'):m.downgrade()
            assert 'registration_challenge' in inspect(connection).get_table_names()
            connection.execute(text('DELETE FROM registration_rate'))
            m.downgrade()
            assert not inspect(connection).get_table_names()
