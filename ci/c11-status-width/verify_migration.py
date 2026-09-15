"""Verify only the candidate flight status migration in disposable loopback PG."""
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, String, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from go_hotel.db.models import FlightOrderRow

url = make_url(os.environ["GO_C11_RUNTIME_DATABASE_URL"])
assert url.get_backend_name() == "postgresql"
assert url.host in {"127.0.0.1", "localhost", "::1"} and url.database == "go_c11_isolated"
root = Path(__file__).resolve().parents[2]
cfg = Config()
cfg.set_main_option("script_location", str(root / "application/alembic"))
assert ScriptDirectory.from_config(cfg).get_heads() == ["0134_flight_status_width"]
path = root / "application/alembic/versions/0134_flight_status_width.py"
spec = importlib.util.spec_from_file_location("flight_width_migration", path)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
assert migration.down_revision == "0133_flight_change_plan"
assert FlightOrderRow.__table__.c.status.type.length == 64
engine = create_engine(url, connect_args={"connect_timeout": 5})
schema = "c11_width_" + uuid4().hex
long_status = "PAYMENT_CONFIRMED_AWAITING_SUPPLIER"
report = {"source_commit": os.environ["GO_C11_SOURCE_COMMIT"],
          "environment": "disposable loopback PostgreSQL",
          "scope": "0133-shaped flight table -> 0134 incremental migration; not full historical migration replay",
          "hong_kong": "NOT_ACCESSED", "production": "HOLD"}
try:
    with engine.begin() as c:
        c.execute(text("CREATE SCHEMA " + schema))
        c.execute(text("SET LOCAL search_path TO " + schema))
        report["postgres_version"] = c.scalar(text("SHOW server_version"))
        table = FlightOrderRow.__table__.to_metadata(MetaData())
        table.c.status.type = String(32)
        table.create(c)
        now = datetime.now(timezone.utc)
        c.execute(table.insert().values(
            order_id="width-sentinel", account_id="isolated-owner",
            prebook_id="isolated-prebook", status="PAYMENT_PENDING",
            total_amount_minor=12345, currency="CNY", passengers=[],
            ticket_numbers=[], current_itinerary=[], created_at=now, updated_at=now))
        def snapshot():
            return dict(c.execute(select(table)).mappings().one())
        before = snapshot()
        before_indexes = inspect(c).get_indexes("flight_order_runtime")
        with Operations.context(MigrationContext.configure(c)):
            migration.upgrade()
        assert next(x for x in inspect(c).get_columns("flight_order_runtime") if x["name"] == "status")["type"].length == 64
        assert snapshot() == before
        assert inspect(c).get_indexes("flight_order_runtime") == before_indexes
        c.execute(table.update().values(status=long_status))
        assert snapshot()["status"] == long_status
        try:
            with Operations.context(MigrationContext.configure(c)):
                migration.downgrade()
        except RuntimeError as exc:
            assert str(exc) == "FLIGHT_STATUS_DOWNGRADE_WOULD_TRUNCATE_HISTORY"
        else:
            raise AssertionError("unsafe downgrade accepted")
        assert snapshot()["status"] == long_status
        assert next(x for x in inspect(c).get_columns("flight_order_runtime") if x["name"] == "status")["type"].length == 64
        c.execute(table.update().values(status="PAYMENT_PENDING"))
        with Operations.context(MigrationContext.configure(c)):
            migration.downgrade()
        assert next(x for x in inspect(c).get_columns("flight_order_runtime") if x["name"] == "status")["type"].length == 32
        assert snapshot() == before
        with Operations.context(MigrationContext.configure(c)):
            migration.upgrade()
        c.execute(table.update().values(status=long_status))
        assert snapshot()["status"] == long_status
        report.update(status="PASS", original_row_retained=True, indexes_retained=True,
                      long_status_roundtrip=True, unsafe_downgrade_rejected=True,
                      safe_downgrade_and_reupgrade=True, model_column_capacity=64)
finally:
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS " + schema + " CASCADE"))
    engine.dispose()
print(json.dumps(report))
