"""Pool boundaries, not a throughput benchmark. No business schema mutation."""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError
from sqlalchemy.pool import QueuePool

from go_hotel.core.config import Settings
from go_hotel.db.session import create_runtime_engine

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize("field,value", [
    ("database_pool_size", 0),
    ("database_pool_size", -1),
    ("database_max_overflow", -1),
    ("database_pool_timeout_seconds", 0),
    ("database_pool_timeout_seconds", float("inf")),
    ("database_pool_timeout_seconds", float("nan")),
    ("database_pool_recycle_seconds", -2),
])
def test_unbounded_or_invalid_pool_configuration_is_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_environment_pool_controls_are_effective(monkeypatch):
    monkeypatch.setenv("DATABASE_POOL_SIZE", "2")
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "0")
    monkeypatch.setenv("DATABASE_POOL_TIMEOUT_SECONDS", "0.1")
    config = Settings(_env_file=None, database_url="postgresql+psycopg://unused@localhost/unused")
    engine = create_runtime_engine(config)
    try:
        assert engine.pool.size() == 2
        assert engine.pool.timeout() == 0.1
    finally:
        engine.dispose()


def assert_bounded_pool_and_recovery(engine):
    # Occupy every slot. An additional thread must time out before executing SQL.
    with engine.connect() as first, engine.connect() as second:
        assert first.scalar(text("SELECT 1")) == second.scalar(text("SELECT 1")) == 1
        def excess_request():
            with engine.connect() as excess:
                return excess.scalar(text("SELECT 1"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            with pytest.raises(TimeoutError):
                executor.submit(excess_request).result(timeout=5)
        assert engine.pool.checkedout() == 2
    assert engine.pool.checkedout() == 0
    with engine.connect() as recovered:
        assert recovered.scalar(text("SELECT 1")) == 1


def test_real_queue_pool_exhaustion_and_release(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pool.db'}", poolclass=QueuePool,
                           pool_size=2, max_overflow=0, pool_timeout=0.05)
    try:
        assert_bounded_pool_and_recovery(engine)
    finally:
        engine.dispose()


def test_sqlite_memory_compatibility():
    engine = create_runtime_engine(Settings(_env_file=None, database_url="sqlite:///:memory:"))
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE probe (value INTEGER)"))
            conn.execute(text("INSERT INTO probe VALUES (7)"))
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT value FROM probe")) == 7
    finally:
        engine.dispose()


def test_postgres_actual_runtime_pool_exhaustion_and_release():
    url = os.environ.get("GO_POOL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("isolated PostgreSQL pool fixture not supplied")
    config = Settings(_env_file=None, database_url=url, database_pool_size=2,
                      database_max_overflow=0, database_pool_timeout_seconds=0.1)
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.host in {"localhost", "127.0.0.1"}
    assert parsed.database == "go_capacity_isolated"
    engine = create_runtime_engine(config)
    try:
        assert_bounded_pool_and_recovery(engine)
    finally:
        engine.dispose()
