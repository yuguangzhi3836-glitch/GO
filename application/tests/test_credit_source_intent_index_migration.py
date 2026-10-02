"""Exercise the online PostgreSQL DDL against a populated, isolated ledger."""

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text


def test_credit_source_intent_index_postgres_upgrade_and_downgrade():
    url = os.environ.get("GO_TEST_DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("PostgreSQL migration test requires GO_TEST_DATABASE_URL")

    path = Path(__file__).resolve().parents[1] / "alembic/versions/0144_credit_source_intent_index.py"
    spec = importlib.util.spec_from_file_location("credit_source_intent_index_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = "credit_index_test_" + uuid.uuid4().hex
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
            conn.execute(text(f"CREATE TABLE {schema}.catalog_credit_source "
                              "(capture_id VARCHAR(64) PRIMARY KEY, payment_intent_id VARCHAR(64) NOT NULL)"))
            conn.execute(text(f"INSERT INTO {schema}.catalog_credit_source VALUES ('capture-1', 'intent-1')"))
        with engine.connect() as conn:
            conn.execute(text(f"SET search_path TO {schema}, public"))
            conn.commit()
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            assert conn.scalar(text("SELECT count(*) FROM pg_indexes WHERE schemaname=:schema "
                                    "AND indexname=:name"),
                               {"schema": schema, "name": migration.INDEX}) == 1
            conn.commit()
            migration.downgrade()
            assert conn.scalar(text("SELECT count(*) FROM pg_indexes WHERE schemaname=:schema "
                                    "AND indexname=:name"),
                               {"schema": schema, "name": migration.INDEX}) == 0
            assert conn.scalar(text(f"SELECT count(*) FROM {schema}.catalog_credit_source")) == 1
            conn.rollback()
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
